import csv
import hashlib
import io
import json
import os
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.datasets import MAX_CSV_BYTES
from backend.example_request import example_request
from backend.registry import ROOT, ModelRegistry
from backend.schemas import FIELDS, OPTIONAL_FIELDS, InferenceInput
from backend.model_adapter import ModelService, prepare_frame
from backend.storage import LocalStore


@pytest.fixture
def client():
    with TestClient(create_app(), base_url="http://127.0.0.1:8765") as client:
        yield client


@pytest.fixture
def station(client):
    response = client.post("/api/stations", json=station_body())
    assert response.status_code == 201, response.text
    return response.json()["data"]


def station_body(**changes):
    return {"name": "本站测试换热站", "code": "ST-TEST-1", "enterpriseId": "ent-1", "networkId": "net-1",
            "segmentId": "seg-1", "timezone": "Asia/Shanghai", **changes}


def manifest(station, optional=False, **changes):
    fields = (*FIELDS, *OPTIONAL_FIELDS) if optional else FIELDS
    return {"name": "测试运行数据", "stationId": station["id"], "timezone": station["timezone"],
            "encoding": "utf-8-sig", "delimiter": ",", "timeColumn": "时间",
            "columnMapping": {f: f for f in fields},
            "sourceUnits": {f: "W" if f.endswith("heat_power") else "m3/h" if f.endswith("flow") else "degC" for f in fields}, **changes}


def rows(count=4, optional=False):
    result = []
    generated = example_request(count)
    for i in range(count):
        values = generated["samples"][i]["values"]
        values["p_net_meter_heat_power"] *= 1000
        values["p_net_meter_flow"] /= 1000
        if optional:
            values.update(dict(zip(OPTIONAL_FIELDS, [40.0, 55.0, 50.0, 60.0, 40.0, 60.0])))
        timestamp = (pd.Timestamp("2026-11-01T00:00:00+08:00") + pd.Timedelta(minutes=30 * i)).isoformat()
        result.append([timestamp, *values.values()])
    return result


def encode(rows, *, optional=False, delimiter=",", headers=None):
    text = io.StringIO(newline="")
    writer = csv.writer(text, delimiter=delimiter)
    writer.writerow(headers or ["时间", *FIELDS, *(OPTIONAL_FIELDS if optional else ())])
    writer.writerows(rows)
    return text.getvalue().encode("utf-8-sig")


def upload(client, station, records=None, body=None, raw=None, optional=False):
    body = body or manifest(station, optional)
    raw = raw if raw is not None else encode(records if records is not None else rows(optional=optional), optional=optional, delimiter=body["delimiter"])
    return client.post("/api/datasets/import", files={"file": ("../../运行数据.csv", raw, "text/csv")},
                       data={"manifest": json.dumps(body, ensure_ascii=False)})


def error(response, code, status=422):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert response.json()["requestId"]


def test_station_binding_hierarchy_unique_code_and_organization_storage(client, station):
    assert client.get("/api/stations?segmentId=seg-1").json()["data"]["items"] == [station]
    assert client.get("/api/stations?segmentId=seg-2").json()["data"]["total"] == 0
    error(client.post("/api/stations", json=station_body(code="st-test-1")), "STATION_CODE_CONFLICT", 409)
    error(client.post("/api/stations", json=station_body(segmentId="seg-4")), "SOURCE_MISMATCH")
    error(client.post("/api/stations", json=station_body(timezone="bad-zone")), "INVALID_REQUEST")
    error(client.post("/api/stations", json=station_body(name="   ")), "INVALID_REQUEST")
    ent = client.post("/api/enterprises", json={"name": "新企业", "code": "NEW-E"}).json()["data"]
    net = client.post("/api/networks", json={"name": "新管网", "code": "NEW-N", "enterpriseId": ent["id"]}).json()["data"]
    seg = client.post("/api/segments", json={"name": "新管段", "code": "NEW-S", "networkId": net["id"]}).json()["data"]
    made = client.post("/api/stations", json=station_body(enterpriseId=ent["id"], networkId=net["id"], segmentId=seg["id"]))
    assert made.status_code == 201
    assert ent in client.get("/api/organizations").json()["data"]["enterprises"]
    error(client.post("/api/enterprises", json={"name": "重复", "code": "new-e"}), "ORGANIZATION_CONFLICT", 409)
    error(client.post("/api/networks", json={"name": "孤立", "code": "ORPHAN", "enterpriseId": "missing"}), "ORGANIZATION_CONFLICT", 409)


def test_import_units_timezone_metadata_paging_fields_and_original_file(client, station):
    records = rows(6)
    raw = encode(records)
    response = upload(client, station, raw=raw)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["status"] == "ready"
    assert data["sourceChecksum"] == hashlib.sha256(raw).hexdigest()
    assert data["sourceUnits"]["p_net_meter_heat_power"] == "W"
    assert data["rawRowCount"] == data["normalizedRowCount"] == 6
    assert data["sampling"]["sourceMedianMinutes"] == 30
    assert data["sampling"]["coverageRatio"] == 1
    first = client.get(f"/api/datasets/{data['id']}/samples?pageSize=2").json()["data"]
    assert first["total"] == 6 and len(first["items"]) == 2
    assert first["items"][0]["timestamp"].endswith("+08:00")
    assert first["items"][0]["values"]["p_net_meter_heat_power"] == pytest.approx(100)
    assert first["items"][0]["values"]["p_net_meter_flow"] == pytest.approx(2500)
    second = client.get(f"/api/datasets/{data['id']}/samples?page=2&pageSize=2&fields=outdoor_temperature").json()["data"]
    assert second["items"][0]["timestamp"] == records[2][0]
    assert set(second["items"][0]["values"]) == {"outdoor_temperature"}
    assert client.get(f"/api/datasets/{data['id']}").json()["data"] == data
    assert client.get("/api/datasets?stationId=unknown").json()["data"]["items"] == []
    assert list(client.app.state.store.sources.iterdir())[0].read_bytes() == raw
    assert all(p.name == data["id"] + ".csv" for p in client.app.state.store.sources.iterdir())


def test_import_resamples_sorts_deduplicates_first_and_never_interpolates(client, station):
    records = rows(4)
    records[0][0], records[1][0], records[2][0], records[3][0] = ["2026-11-01 00:10", "2026-11-01 00:20", "2026-11-01 00:20", "2026-11-01 02:00"]
    records[0][4], records[1][4], records[2][4] = 100000, 120000, 999999
    records = [records[3], *records[:3]]
    data = upload(client, station, records).json()["data"]
    assert data["normalizedRowCount"] == 2
    points = client.get(f"/api/datasets/{data['id']}/samples").json()["data"]["items"]
    assert points[0]["values"]["p_net_meter_heat_power"] == 110
    assert [p["timestamp"][11:16] for p in points] == ["00:00", "02:00"]
    assert data["sampling"]["blockCount"] == 2
    assert data["sampling"]["expectedBinCount"] == 5
    assert data["sampling"]["coverageRatio"] == pytest.approx(0.4)
    assert any(i["code"] == "DUPLICATE_TIMESTAMP" and i["count"] == 1 for i in data["issues"])


@pytest.mark.parametrize("optional", [False, True])
def test_missing_invalid_counts_and_null_values_are_distinct(client, station, optional):
    records = rows(4, optional)
    records[0][1], records[1][1] = "", "NaN"
    data = upload(client, station, records, optional=optional).json()["data"]
    points = client.get(f"/api/datasets/{data['id']}/samples").json()["data"]["items"]
    assert points[0]["values"][FIELDS[0]] is None and points[0]["quality"][FIELDS[0]] == "missing"
    assert points[1]["values"][FIELDS[0]] is None and points[1]["quality"][FIELDS[0]] == "invalid"
    column = next(c for c in data["columns"] if c["field"] == FIELDS[0])
    assert (column["validCount"], column["missingCount"], column["invalidCount"]) == (2, 1, 1)
    assert not any(i["blocking"] for i in data["issues"])
    if optional:
        assert points[0]["values"][OPTIONAL_FIELDS[0]] == 40


@pytest.mark.parametrize("case,code", [("unit", "UNIT_UNSUPPORTED"), ("timezone", "TIMEZONE_MISMATCH"),
    ("duplicate_mapping", "INVALID_REQUEST"), ("unknown_mapping", "INVALID_REQUEST"),
    ("time_reused", "INVALID_REQUEST"), ("missing_units", "INVALID_REQUEST")])
def test_manifest_validation_creates_no_dataset(client, station, case, code):
    body = manifest(station)
    if case == "unit": body["sourceUnits"]["p_net_meter_heat_power"] = "kWh"
    elif case == "timezone": body["timezone"] = "Etc/UTC"
    elif case == "duplicate_mapping": body["columnMapping"]["second"] = FIELDS[0]
    elif case == "unknown_mapping": body["columnMapping"]["unknown"] = "pressure"
    elif case == "time_reused": body["columnMapping"]["时间"] = body["columnMapping"].pop(FIELDS[0])
    elif case == "missing_units": del body["sourceUnits"][FIELDS[0]]
    error(upload(client, station, body=body), code)
    assert client.get("/api/datasets").json()["data"]["total"] == 0
    assert not list(client.app.state.store.sources.iterdir())


@pytest.mark.parametrize("case", ["missing_header", "missing_mapping", "missing_values", "no_valid_times", "header_only", "missing_time_column", "hourly"])
def test_invalid_datasets_preserve_quality_report_and_raw_source(client, station, case):
    body, records, headers = manifest(station), rows(6), ["时间", *FIELDS]
    if case == "missing_header":
        headers.remove(FIELDS[0])
        for row in records: del row[1]
    elif case == "missing_mapping": del body["columnMapping"][FIELDS[0]]
    elif case == "missing_values":
        for row in records: row[1] = ""
    elif case == "no_valid_times":
        for row in records: row[0] = "not a date"
    elif case == "header_only": records = []
    elif case == "missing_time_column": body["timeColumn"] = "不存在的列"
    elif case == "hourly":
        for i, row in enumerate(records): row[0] = f"2026-11-01T{i:02d}:00:00+08:00"
    response = upload(client, station, body=body, raw=encode(records, headers=headers))
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["status"] == "invalid" and any(i["blocking"] for i in data["issues"])
    if case == "hourly": assert data["sampling"]["sourceMedianMinutes"] == 60
    assert client.get(f"/api/datasets/{data['id']}").json()["data"] == data
    assert list(client.app.state.store.sources.iterdir())


@pytest.mark.parametrize("raw", [b"", b"\xff\xfe invalid", b"a,a\n1,2\n", b"time,a\n1,2,3\n", b'"unterminated'])
def test_malformed_csv_is_rejected(client, station, raw):
    error(upload(client, station, raw=raw), "CSV_FORMAT_INVALID")


def test_upload_limits_origin_and_multipart_shape(client, station):
    error(upload(client, station, raw=b"x" * (MAX_CSV_BYTES + 1)), "REQUEST_TOO_LARGE", 413)
    error(client.post("/api/datasets/import", json={}), "INVALID_REQUEST", 400)
    error(client.post("/api/datasets/import", files={"file": ("x.csv", encode(rows()))}, data={"manifest": "{"}), "INVALID_REQUEST")
    response = client.post("/api/datasets/import", files={"file": ("x.csv", encode(rows()))}, data={"manifest": json.dumps(manifest(station))}, headers={"origin": "https://evil.example"})
    error(response, "ORIGIN_REJECTED", 403)


def test_range_queries_are_closed_zoned_and_field_checked(client, station):
    data = upload(client, station).json()["data"]
    url = f"/api/datasets/{data['id']}/samples"
    result = client.get(url, params={"start": rows()[1][0], "end": rows()[2][0]}).json()["data"]
    assert result["total"] == 2
    error(client.get(url, params={"start": "2026-11-01 00:00", "end": rows()[2][0]}), "TIME_RANGE_INVALID")
    error(client.get(url, params={"start": rows()[3][0], "end": rows()[0][0]}), "TIME_RANGE_INVALID")
    error(client.get(url, params={"fields": "pressure"}), "INVALID_REQUEST")
    error(client.get(url, params={"fields": f"{FIELDS[0]},{FIELDS[0]}"}), "INVALID_REQUEST")
    error(client.get("/api/datasets/unknown/samples"), "NOT_FOUND", 404)
    error(client.get(url + "?page=0"), "INVALID_REQUEST")


def test_huge_time_gap_does_not_create_millions_of_empty_bins(client, station):
    records = rows(2)
    records[0][0], records[1][0] = "1900-01-01T00:00:00+08:00", "2200-01-01T00:00:00+08:00"
    data = upload(client, station, records).json()["data"]
    assert data["normalizedRowCount"] == 2


def test_sensor_quality_blocks_long_constant_outdoor_but_not_setpoints_or_idle(client, station):
    records = rows(150, optional=True)
    for row in records:
        row[1] = 5
        row[4] = 0
        row[5] = 0
    data = upload(client, station, records, optional=True).json()["data"]
    assert data["status"] == "invalid"
    assert any(i["code"] == "OUTDOOR_SENSOR_UNHEALTHY" for i in data["issues"])
    assert not any(i["blocking"] and i["field"] in {"p_net_meter_heat_power", "p_net_meter_flow", "s_hc1_supply_temperature_setpoint"} for i in data["issues"])
    assert data["sensorQuality"]["checkedBlockCount"] == 1


def test_restart_recovers_station_dataset_samples_and_registry_without_manifest(client, station, monkeypatch):
    data = upload(client, station, optional=True).json()["data"]
    directory = client.app.state.store.directory
    client.app.state.worker.close()  # Release the M2 service lease before reopening the same data directory.
    with TestClient(create_app(data_dir=directory), base_url="http://127.0.0.1") as restarted:
        assert restarted.get("/api/stations").json()["data"]["items"] == [station]
        assert restarted.get(f"/api/datasets/{data['id']}").json()["data"] == data
        assert restarted.get(f"/api/datasets/{data['id']}/samples").json()["data"]["total"] == 4
    manifest_path = ROOT / "backend/config/registry.example.json"
    with TestClient(create_app(manifest_path, data_dir=directory), base_url="http://127.0.0.1") as registered:
        assert registered.get("/api/models").json()["data"]["items"][0]["status"] == "ready"
    with TestClient(create_app(data_dir=directory), base_url="http://127.0.0.1") as recovered:
        assert recovered.get("/api/models").json()["data"]["items"][0]["id"] == "station-nbm-m1-7"


def test_same_model_version_cannot_change_during_restart(client, tmp_path):
    directory = client.app.state.store.directory
    create_app(ROOT / "backend/config/registry.example.json", data_dir=directory)
    config = json.loads((ROOT / "backend/config/registry.example.json").read_text(encoding="utf-8"))
    config["models"][0]["artifactChecksum"] = "0" * 64
    manifest_path = tmp_path / "changed.json"
    manifest_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="同版本"):
        create_app(manifest_path, data_dir=directory)


def test_storage_failure_leaves_no_ready_dataset(client, station, monkeypatch):
    source_dir = client.app.state.store.sources
    original = Path.open
    def no_space(path, *args, **kwargs):
        if path.parent == source_dir and args and args[0] == "xb":
            raise OSError("simulated disk full")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", no_space)
    error(upload(client, station), "STORAGE_WRITE_FAILED", 500)
    assert client.get("/api/datasets").json()["data"]["total"] == 0
    assert not list(source_dir.iterdir())


def test_orphan_cleanup_only_removes_old_server_named_unreferenced_file(client, station):
    imported = upload(client, station).json()["data"]
    directory = client.app.state.store.directory
    sources = client.app.state.store.sources
    old = sources / ("a" * 32 + ".csv")
    recent = sources / ("b" * 32 + ".csv")
    unrelated = sources / "my-data.csv"
    for path in (old, recent, unrelated): path.write_bytes(b"not referenced")
    for path in (old, unrelated, sources / (imported["id"] + ".csv")): os.utime(path, (time.time() - 90000,) * 2)
    LocalStore(directory)
    assert not old.exists() and recent.exists() and unrelated.exists()
    assert (sources / (imported["id"] + ".csv")).exists()


@pytest.mark.parametrize("missing_optional", [False, True])
def test_optional_measurements_reach_real_model_unchanged(missing_optional):
    registry = ModelRegistry(ROOT / "backend/config/registry.example.json")
    payload = example_request()
    payload["units"].update(dict.fromkeys(OPTIONAL_FIELDS, "degC"))
    for sample in payload["samples"]:
        sample["values"].update(dict(zip(OPTIONAL_FIELDS, [None] * 6 if missing_optional else [40., 55., 50., 60., 40., 60.])))
    request = InferenceInput.model_validate(payload)
    actual = ModelService(registry).infer(request)
    frame, _ = prepare_frame(request)
    _, model = registry.resolve(payload["modelId"], payload["modelVersion"])
    expected = model.detect(frame)
    assert [point["score"] for point in actual["points"]] == pytest.approx(list(expected.score))
    assert any(w["code"] == "OPTIONAL_INPUTS_OMITTED" for w in actual["warnings"]) is missing_optional


@pytest.mark.parametrize("timestamp", ["2026-03-29 02:30", "2026-10-25 02:30"])
def test_dst_nonexistent_or_ambiguous_local_import_time_is_not_guessed(client, timestamp):
    station = client.post("/api/stations", json=station_body(timezone="Europe/Berlin")).json()["data"]
    records = rows(1)
    records[0][0] = timestamp
    data = upload(client, station, records).json()["data"]
    assert data["status"] == "invalid" and data["normalizedRowCount"] == 0
    assert any(i["code"] == "INVALID_TIMESTAMP" for i in data["issues"])


def test_dst_repeated_wall_times_are_preserved_but_blocked_for_model(client):
    station = client.post("/api/stations", json=station_body(timezone="Europe/Berlin")).json()["data"]
    records = rows(2)
    records[0][0], records[1][0] = "2026-10-25T02:00:00+02:00", "2026-10-25T02:00:00+01:00"
    data = upload(client, station, records).json()["data"]
    assert data["status"] == "invalid" and data["normalizedRowCount"] == 2
    assert any(i["code"] == "DST_TIME_AMBIGUOUS" and i["blocking"] for i in data["issues"])
