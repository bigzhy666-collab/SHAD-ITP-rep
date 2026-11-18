import copy
import json
from pathlib import Path
from threading import Event, Thread

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import MAX_BODY_BYTES, create_app
from backend.errors import ServiceError
from backend.example_request import example_request
from backend.model_adapter import ModelService, confirmed_segments, prepare_frame
from backend.registry import ROOT, ModelRegistry
from backend.schemas import InferenceInput


@pytest.fixture(scope="module")
def registry():
    return ModelRegistry(ROOT / "backend/config/registry.example.json")


@pytest.fixture
def client(registry):
    with TestClient(create_app(registry=registry), base_url="http://127.0.0.1:8765") as client:
        yield client


def assert_error(response, code, status=422):
    assert response.status_code == status, response.text
    payload = response.json()
    assert payload["requestId"]
    assert payload["error"]["code"] == code
    assert "Traceback" not in response.text
    assert str(ROOT) not in response.text


def test_runtime_does_not_advertise_unimplemented_business_capabilities(client):
    runtime = client.get("/api/runtime").json()["data"]
    assert runtime["contractVersion"] == "1.0"
    assert runtime["capabilities"]["dataImport"] is True
    assert runtime['capabilities'] == {'organizationManagement': True, 'dataImport': True, 'anomalyDetection': True, 'offlineDetection': True,
                                       'causeDiagnosis': False, 'reportPersistence': True}
    assert runtime["modelInterface"] == {"available": True, "persisted": False, "maxSamples": 5000}


def test_default_registry_does_not_auto_bind_example():
    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        assert client.get("/api/models").json()["data"]["items"] == []
        assert client.get("/api/stations").json()["data"]["items"] == []


def test_registry_model_metadata_and_filtering(client):
    models = client.get("/api/models?stationId=station-example-m1-7&pageSize=1").json()["data"]
    model = models["items"][0]
    assert models["total"] == 1
    assert model["status"] == "ready"
    assert model["cThr"] >= 1
    assert model["isDemo"] is True
    assert len(model["trainingFeatureColumns"]) > 8
    assert model["trainedAt"] is None
    assert "artifact" not in model
    assert client.get("/api/models?stationId=other").json()["data"]["total"] == 0
    assert client.get("/api/stations?segmentId=other").json()["data"]["total"] == 0
    assert client.get("/api/stations?segmentId=seg-example").json()["data"]["total"] == 1
    assert_error(client.get("/api/models?pageSize=501"), "INVALID_REQUEST")


def test_actual_artifact_http_matches_direct_detect_every_point(client, registry):
    payload = example_request()
    response = client.post("/api/model-inferences", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["persisted"] is False
    frame, index = prepare_frame(InferenceInput.model_validate(payload))
    _, model = registry.resolve(payload["modelId"], payload["modelVersion"])
    direct = model.detect(frame)
    assert data["summary"]["pointCount"] == len(direct)
    for i, point in enumerate(data["points"]):
        assert point["timestamp"] == index[i].isoformat()
        row = direct.iloc[i]
        for field in ("score", "threshold", "health"):
            assert point[field] == pytest.approx(float(row[field]), rel=1e-10, abs=1e-12)
        for field in ("alarm", "confirmed"):
            assert point[field] == bool(row[field])
        assert point["criticality"] == int(row["criticality"])
    # Original segment routine, on the same block, supplies an independent oracle.
    from scripts.score_station import segments
    expected_segments = segments(direct).to_dict("records")
    assert len(data["segments"]) == len(expected_segments)
    for got, expected in zip(data["segments"], expected_segments):
        assert pd.Timestamp(got["start"]).tz_localize(None) == expected["start"]
        assert pd.Timestamp(got["end"]).tz_localize(None) == expected["end"]
        for field in ("hours", "peak_score", "max_criticality"):
            assert got[field] == pytest.approx(expected[field])
        assert got["cause"] is None and got["solution"] is None


def test_gaps_are_independent_actual_model_calls(client, registry):
    payload = example_request()
    payload["samples"] = payload["samples"][:20] + payload["samples"][30:]
    data = client.post("/api/model-inferences", json=payload).json()["data"]
    assert data["summary"]["blockCount"] == 2
    assert {p["blockId"] for p in data["points"]} == {"block-1", "block-2"}
    second = copy.deepcopy(payload)
    second["samples"] = second["samples"][20:]
    direct_second = ModelService(registry).infer(InferenceInput.model_validate(second))
    assert [p["criticality"] for p in data["points"][20:]] == [p["criticality"] for p in direct_second["points"]]
    assert [p["score"] for p in data["points"][20:]] == pytest.approx([p["score"] for p in direct_second["points"]])
    assert {w["code"] for w in data["warnings"]} >= {"DATA_GAPS", "FEATURE_CONTEXT_SHORT", "DEMO_MODEL"}


@pytest.mark.parametrize("kind,code", [
    ("station", "STATION_BINDING_REQUIRED"), ("model", "NOT_FOUND"),
    ("version", "NOT_FOUND"), ("timezone", "TIMEZONE_MISMATCH"),
    ("units", "UNIT_UNSUPPORTED"), ("missing", "REQUIRED_FIELD_MISSING"),
    ("extra_field", "REQUIRED_FIELD_MISSING"), ("empty_core", "DATA_QUALITY_BLOCKED"),
    ("invalid_value", "DATA_QUALITY_BLOCKED"), ("duplicate", "TIME_RANGE_INVALID"),
    ("unsorted", "TIME_RANGE_INVALID"), ("naive", "TIME_RANGE_INVALID"),
    ("off_grid", "TIME_RANGE_INVALID"), ("arbitrary_path", "INVALID_REQUEST"),
    ("threshold_override", "INVALID_REQUEST"), ("numeric_string", "INVALID_REQUEST"),
    ("boolean", "INVALID_REQUEST"), ("empty", "INVALID_REQUEST"),
])
def test_rejects_invalid_input(client, kind, code):
    payload = example_request()
    if kind == "station": payload["stationId"] = "unknown"
    elif kind == "model": payload["modelId"] = "unknown"
    elif kind == "version": payload["modelVersion"] = "new-version"
    elif kind == "timezone": payload["timezone"] = "Asia/Shanghai"
    elif kind == "units": payload["units"]["p_net_meter_flow"] = "m3/h"
    elif kind == "missing": del payload["samples"][0]["values"]["outdoor_temperature"]
    elif kind == "extra_field": payload["samples"][0]["values"]["pressure"] = 1.0
    elif kind == "empty_core":
        for sample in payload["samples"]: sample["values"]["outdoor_temperature"] = None
    elif kind == "invalid_value": payload["samples"][0]["values"]["p_net_meter_flow"] = -1.0
    elif kind == "duplicate": payload["samples"][1] = payload["samples"][0]
    elif kind == "unsorted": payload["samples"].reverse()
    elif kind == "naive": payload["samples"][0]["timestamp"] = "2017-11-18T00:00:00"
    elif kind == "off_grid": payload["samples"][0]["timestamp"] = "2017-11-18T00:01:00+00:00"
    elif kind == "arbitrary_path": payload["modelPath"] = "C:/untrusted.pkl"
    elif kind == "threshold_override": payload["cThr"] = 1
    elif kind == "numeric_string": payload["samples"][0]["values"]["outdoor_temperature"] = "5"
    elif kind == "boolean": payload["samples"][0]["values"]["outdoor_temperature"] = True
    elif kind == "empty": payload["samples"] = []
    assert_error(client.post("/api/model-inferences", json=payload), code, 404 if kind in ("model", "version") else 422)


def test_wrong_station_cannot_use_registered_model(registry):
    registry = copy.copy(registry)
    registry.stations = {**registry.stations, "other": {**next(iter(registry.stations.values())), "id": "other"}}
    payload = example_request()
    payload["stationId"] = "other"
    with pytest.raises(ServiceError, match="所属站点"):
        ModelService(registry).infer(InferenceInput.model_validate(payload))


def test_request_limits_and_json_parse_errors(client):
    assert_error(client.post("/api/model-inferences", content="{"), "INVALID_REQUEST", 400)
    assert_error(client.post("/api/model-inferences", content="{}", headers={"content-length": str(MAX_BODY_BYTES + 1)}), "REQUEST_TOO_LARGE", 413)
    assert_error(client.post("/api/model-inferences", content=b"x" * (MAX_BODY_BYTES + 1)), "REQUEST_TOO_LARGE", 413)
    payload = example_request(5001)
    assert_error(client.post("/api/model-inferences", json=payload), "INVALID_REQUEST")
    raw = json.dumps(example_request()).replace('"outdoor_temperature": 5.0', '"outdoor_temperature": NaN', 1)
    assert_error(client.post("/api/model-inferences", content=raw, headers={"content-type": "application/json"}), "INVALID_REQUEST")


def test_local_only_host_and_origin(client):
    assert_error(client.get("/api/runtime", headers={"host": "evil.example"}), "LOCAL_ACCESS_REQUIRED", 403)
    assert_error(client.post("/api/model-inferences", json=example_request(), headers={"origin": "https://evil.example"}), "ORIGIN_REJECTED", 403)
    assert_error(client.post("/api/model-inferences", json=example_request(), headers={"origin": "null"}), "ORIGIN_REJECTED", 403)
    assert_error(client.post("/api/model-inferences", json=example_request(), headers={"sec-fetch-site": "cross-site"}), "ORIGIN_REJECTED", 403)
    response = client.post("/api/model-inferences", json=example_request(), headers={"origin": "http://127.0.0.1:8765"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["x-request-id"] == response.json()["requestId"]


def test_dev_origin_is_explicit_and_loopback_only(registry):
    with TestClient(create_app(registry=registry, dev_origins=("http://127.0.0.1:5173",)), base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/model-inferences", json=example_request(), headers={"origin": "http://127.0.0.1:5173"}).status_code == 200
    app = create_app(registry=registry, dev_origins=("https://evil.example",))
    with pytest.raises(ValueError, match="本机"):
        with TestClient(app): pass


def test_capability_and_api404_are_json_not_spa(client):
    assert_error(client.post("/api/detections", json={}), "INVALID_REQUEST", 422)
    assert_error(client.post("/api/diagnoses", json={}), "CAPABILITY_UNAVAILABLE", 503)
    assert_error(client.get("/api/not-a-route", headers={"accept": "text/html"}), "NOT_FOUND", 404)
    assert client.get("/api/detections").json()["data"]["items"] == []
    spec = client.get("/api/openapi.json").json()
    assert "/api/model-inferences" in spec["paths"]
    assert spec["components"]["schemas"]["InferenceInput"]["additionalProperties"] is False


@pytest.mark.parametrize("change", ["checksum", "escape", "missing"])
def test_trusted_manifest_rejects_tamper_or_path_escape(tmp_path, change):
    config = json.loads((ROOT / "backend/config/registry.example.json").read_text(encoding="utf-8"))
    model = config["models"][0]
    if change == "checksum": model["artifactChecksum"] = "0" * 64
    elif change == "escape": model["artifact"] = "../../somewhere.pkl"
    else: model["artifact"] = "missing.pkl"
    manifest = tmp_path / "registry.json"
    manifest.write_text(json.dumps(config), encoding="utf-8")
    registry = ModelRegistry(manifest)
    assert registry.list_models(None)[0]["status"] == "unavailable"
    with pytest.raises(ServiceError) as error:
        registry.resolve(model["id"], model["version"])
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_same_version_cannot_silently_replace_artifact(tmp_path):
    config = json.loads((ROOT / "backend/config/registry.example.json").read_text(encoding="utf-8"))
    artifact = tmp_path / "M1_s7.pkl"
    artifact.write_bytes((ROOT / "ml/models/M1_s7.pkl").read_bytes())
    manifest = tmp_path / "registry.json"
    manifest.write_text(json.dumps(config), encoding="utf-8")
    registry = ModelRegistry(manifest, artifact_root=tmp_path)
    registry.resolve("station-nbm-m1-7", "example-1")
    artifact.write_bytes(b"modified")
    with pytest.raises(ServiceError): registry.resolve("station-nbm-m1-7", "example-1")


def test_reject_duplicate_registration(tmp_path):
    config = json.loads((ROOT / "backend/config/registry.example.json").read_text(encoding="utf-8"))
    config["models"] *= 2
    manifest = tmp_path / "registry.json"
    manifest.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"): ModelRegistry(manifest)


def test_segment_criticality_semantics_and_zero_duration():
    points = [
        {"blockId": "block-1", "timestamp": "2026-11-01T00:00:00+08:00", "score": 4.0, "criticality": 3, "confirmed": True},
        {"blockId": "block-2", "timestamp": "2026-11-01T01:00:00+08:00", "score": 3.0, "criticality": 3, "confirmed": True},
    ]
    events = confirmed_segments(points)
    assert len(events) == 2
    assert [e["hours"] for e in events] == [0, 0]
    assert events[0]["boundary"] == "touches_range_start"
    assert events[1]["boundary"] == "touches_range_end"


def test_no_anomaly_is_success_not_failure(registry, monkeypatch):
    _, model = registry.resolve("station-nbm-m1-7", "example-1")
    def normal(frame):
        return pd.DataFrame({"score": 0.1, "threshold": 1.0, "alarm": False,
                             "criticality": 0, "health": 0.9, "confirmed": False}, index=frame.index)
    monkeypatch.setattr(model, "detect", normal)
    data = ModelService(registry).infer(InferenceInput.model_validate(example_request()))
    assert data["segments"] == [] and data["summary"]["eventCount"] == 0


@pytest.mark.parametrize("kind", ["nan", "missing", "criticality", "failure"])
def test_model_failures_are_explicit_not_mock_fallback(registry, monkeypatch, kind):
    _, model = registry.resolve("station-nbm-m1-7", "example-1")
    real_detect = model.detect
    def broken(frame):
        if kind == "failure": raise RuntimeError("private internal path")
        output = real_detect(frame)
        if kind == "nan": output.iloc[0, 0] = np.nan
        elif kind == "missing": output = output.drop(columns=["health"])
        elif kind == "criticality": output["criticality"] = -1
        return output
    monkeypatch.setattr(model, "detect", broken)
    with pytest.raises(ServiceError) as exc:
        ModelService(registry).infer(InferenceInput.model_validate(example_request()))
    assert exc.value.code == ("MODEL_EXECUTION_FAILED" if kind == "failure" else "MODEL_OUTPUT_INVALID")


def test_busy_does_not_execute_a_second_model_request(registry, monkeypatch):
    service = ModelService(registry)
    _, model = registry.resolve("station-nbm-m1-7", "example-1")
    real_detect = model.detect
    entered, release = Event(), Event()
    def slow(frame):
        entered.set()
        assert release.wait(5)
        return real_detect(frame)
    monkeypatch.setattr(model, "detect", slow)
    request = InferenceInput.model_validate(example_request())
    errors = []
    def worker():
        try: service.infer(request)
        except Exception as exc: errors.append(exc)
    thread = Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(ServiceError) as exc: service.infer(request)
        assert exc.value.code == "MODEL_BUSY" and exc.value.retryable
    finally:
        release.set()
        thread.join(5)
    assert not errors and not thread.is_alive()


def test_static_frontend_and_history_routes_stay_separate(tmp_path):
    (tmp_path / "index.html").write_text("<html>SHAD test build</html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('local');", encoding="utf-8")
    with TestClient(create_app(frontend_dir=tmp_path), base_url="http://127.0.0.1") as client:
        assert "SHAD test build" in client.get("/overview", headers={"accept": "text/html"}).text
        assert client.get("/app.js").status_code == 200
        assert_error(client.get("/missing.js", headers={"accept": "text/html"}), "NOT_FOUND", 404)
        assert_error(client.get("/api/missing", headers={"accept": "text/html"}), "NOT_FOUND", 404)


def test_chunked_body_limit_does_not_trust_content_length(client):
    def chunks():
        for _ in range(6):
            yield b"x" * (1024 * 1024)
    assert_error(client.post("/api/model-inferences", content=chunks()), "REQUEST_TOO_LARGE", 413)


def test_missing_core_in_short_block_cannot_hide_in_global_good_quality(client):
    payload = example_request()
    payload["samples"] = payload["samples"][:59] + [{**payload["samples"][-1], "timestamp": "2017-11-20T00:00:00+00:00"}]
    payload["samples"][-1]["values"]["outdoor_temperature"] = None
    assert_error(client.post("/api/model-inferences", json=payload), "DATA_QUALITY_BLOCKED")


def test_wall_time_is_used_and_dst_repetition_rejected():
    payload = example_request(4)
    payload["timezone"] = "Asia/Shanghai"
    frame, stamps = prepare_frame(InferenceInput.model_validate(payload))
    assert frame.index[0].hour == 8 and frame.index.tz is None
    assert stamps[0].utcoffset().total_seconds() == 8 * 3600
    payload["timezone"] = "America/New_York"
    repeated = ["2026-11-01T01:00:00-04:00", "2026-11-01T01:30:00-04:00",
                "2026-11-01T01:00:00-05:00", "2026-11-01T01:30:00-05:00"]
    for sample, timestamp in zip(payload["samples"], repeated): sample["timestamp"] = timestamp
    with pytest.raises(ServiceError, match="夏令时"):
        prepare_frame(InferenceInput.model_validate(payload))


def test_inconsistent_sklearn_pickle_is_not_silently_loaded(monkeypatch, registry):
    import warnings
    from sklearn.exceptions import InconsistentVersionWarning
    registry.resolve("station-nbm-m1-7", "example-1")
    from src import inference
    def mismatched(path):
        warnings.warn(InconsistentVersionWarning(estimator_name="MLPRegressor",
                      current_sklearn_version="1.9.1", original_sklearn_version="0.0.0"))
    monkeypatch.setattr(inference, "load_model", mismatched)
    new_registry = ModelRegistry(ROOT / "backend/config/registry.example.json")
    with pytest.raises(ServiceError) as exc:
        new_registry.resolve("station-nbm-m1-7", "example-1")
    assert exc.value.code == "MODEL_UNAVAILABLE"


def test_confirmed_event_continues_when_alarm_falls_before_criticality_decays(registry, monkeypatch):
    _, model = registry.resolve("station-nbm-m1-7", "example-1")
    def decay(frame):
        alarms = np.arange(len(frame)) < model.c_thr + 1
        criticality, count = [], 0
        for alarm in alarms:
            count = count + 1 if alarm else max(0, count - 1)
            criticality.append(count)
        score = np.where(alarms, 1.1, 0.9)
        return pd.DataFrame({"score": score, "threshold": 1.0, "alarm": alarms,
                             "criticality": criticality, "health": np.clip(1 - score, 0, 1),
                             "confirmed": np.array(criticality) >= model.c_thr}, index=frame.index)
    monkeypatch.setattr(model, "detect", decay)
    data = ModelService(registry).infer(InferenceInput.model_validate(example_request()))
    assert any(not p["alarm"] and p["confirmed"] for p in data["points"])
    event = data["segments"][0]
    assert event["end"] == data["points"][model.c_thr + 1]["timestamp"]
