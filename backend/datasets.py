"""Explicit CSV normalization. Never interpolates, trains, or changes model state."""
import csv
import hashlib
import io
import math
import re
from collections import Counter
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .errors import ServiceError
from .schemas import ALL_FIELDS, ALL_UNITS, FIELDS, ImportManifest
from .storage import LocalStore, now

MAX_CSV_BYTES = 20 * 1024 * 1024
IMPORT_VERSION = "csv-utf8-units-30min-quality-v1"
LABELS = {
    "outdoor_temperature": "室外温度", "p_net_supply_temperature": "一次侧供水温度",
    "p_net_return_temperature": "一次侧回水温度", "p_net_meter_heat_power": "瞬时热功率",
    "p_net_meter_flow": "瞬时流量", "p_hc1_return_temperature": "二次侧采暖回水温度",
    "s_hc1_supply_temperature": "二次侧采暖供水温度", "s_hc1_supply_temperature_setpoint": "供水温度设定值",
    "p_hc1_return_temperature_setpoint": "二次侧回水温度设定值",
    "s_dhw_supply_temperature": "生活热水供水温度", "s_dhw_supply_temperature_setpoint": "生活热水供水温度设定值",
    "s_dhw_upper_storage_temperature": "储水箱上部温度", "s_dhw_lower_storage_temperature": "储水箱下部温度",
    "s_dhw_upper_storage_temperature_setpoint": "储水箱上部温度设定值",
}


def instant(value: str, *, timezone_name: str | None = None) -> pd.Timestamp:
    """Full ISO date/time only. Never infer today's date from a time-only cell."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
        raise ValueError("完整日期时间格式不正确")
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("无效时间")
    if stamp.tzinfo is None:
        if timezone_name is None:
            raise ValueError("时间必须带时区偏移")
        stamp = stamp.tz_localize(ZoneInfo(timezone_name), ambiguous="raise", nonexistent="raise")
    elif timezone_name:
        stamp = stamp.tz_convert(ZoneInfo(timezone_name))
    # SQLite's integer is signed 64-bit; match pandas nanosecond representability.
    _ = stamp.value
    return stamp


def time_query(start, end):
    try:
        a = instant(start) if start is not None else None
        b = instant(end) if end is not None else None
        if a is not None and b is not None and a >= b:
            raise ValueError("起始时间必须早于结束时间")
    except Exception as exc:
        raise ServiceError("TIME_RANGE_INVALID", "查询时间必须为带时区的完整 ISO8601，且开始早于结束。") from exc
    return (a.value // 1000 if a is not None else None, b.value // 1000 if b is not None else None)


def split_ranges(index):
    if not len(index):
        return []
    wall = index.tz_localize(None)
    delta = 30 * 60 * 1_000_000_000
    physical, local = list(map(int, index.as_unit("ns").asi8)), list(map(int, wall.as_unit("ns").asi8))
    starts = [0, *[i for i in range(1, len(index)) if physical[i] - physical[i - 1] != delta
                  or local[i] - local[i - 1] != delta]]
    return list(zip(starts, [*starts[1:], len(index)]))


def unit_factor(field, unit):
    choices = {"kW": {"W": 0.001, "kW": 1.0, "MW": 1000.0},
               "L/h": {"L/h": 1.0, "m3/h": 1000.0}, "degC": {"degC": 1.0}}
    try:
        return choices[ALL_UNITS[field]][unit]
    except KeyError as exc:
        raise ServiceError("UNIT_UNSUPPORTED", "字段单位不支持；功率使用 W/kW/MW、流量使用 L/h/m3/h、温度使用 degC。",
                           details=[{"field": field, "reason": "不支持此物理量的单位"}]) from exc


class DatasetService:
    def __init__(self, store: LocalStore):
        self.store = store

    def import_csv(self, raw: bytes, manifest: ImportManifest):
        if len(raw) > MAX_CSV_BYTES:
            raise ServiceError("REQUEST_TOO_LARGE", "CSV 文件不能超过 20 MiB。", 413)
        station = self.store.station(manifest.stationId)
        if manifest.timezone != station["timezone"]:
            raise ServiceError("TIMEZONE_MISMATCH", "导入时区与本站登记时区不一致。")
        mapping = manifest.columnMapping
        targets = set(mapping.values())
        if len(targets) != len(mapping) or not targets.issubset(ALL_FIELDS) or manifest.timeColumn in mapping \
                or any(not source.strip() for source in mapping):
            raise ServiceError("INVALID_REQUEST", "字段映射必须唯一，使用受支持的标准测点，且不能复用时间列。")
        if not set(manifest.sourceUnits).issubset(set(FIELDS) | targets) or not targets.issubset(manifest.sourceUnits):
            raise ServiceError("INVALID_REQUEST", "请为所有映射字段声明原始单位，不添加未映射的可选字段。")
        factors = {f: unit_factor(f, unit) for f, unit in manifest.sourceUnits.items()}
        columns = [f for f in ALL_FIELDS if f in set(FIELDS) | targets]
        try:
            text = raw.decode(manifest.encoding)
            if "\x00" in text:
                raise ValueError("不是文本 CSV")
            reader = csv.reader(io.StringIO(text.lstrip("\ufeff"), newline=""), delimiter=manifest.delimiter, strict=True)
            headers = next(reader)
            if not headers or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
                raise ValueError("表头重复或为空")
            data = []
            for row in reader:
                if not row or (len(row) == 1 and not row[0].strip()):
                    continue
                if len(row) != len(headers):
                    raise ValueError("CSV 列数与表头不一致")
                data.append(row)
        except (UnicodeError, csv.Error, ValueError, StopIteration) as exc:
            raise ServiceError("CSV_FORMAT_INVALID", "CSV 无法解析，请检查 UTF-8 编码、分隔符、唯一表头和每行列数。") from exc

        issues = []

        def issue(code, field, count, message, blocking=False):
            if count:
                issues.append({"code": code, "field": field, "count": int(count), "message": message, "blocking": blocking})

        sources = {target: source for source, target in mapping.items()}
        for field in FIELDS:
            if field not in sources or sources[field] not in headers:
                issue("REQUIRED_FIELD_MISSING", field, 1, f"缺少核心测点：{LABELS[field]}。", True)
        for field in targets - set(FIELDS):
            if sources[field] not in headers:
                issue("OPTIONAL_FIELD_MISSING", field, 1, f"找不到已映射可选列：{LABELS[field]}，该列保留空值。")
        if manifest.timeColumn not in headers:
            issue("TIME_COLUMN_MISSING", None, 1, "找不到时间列，请重新确认映射。", True)
        positions = {h: i for i, h in enumerate(headers)}
        invalid_counts, missing_counts = Counter(), Counter()
        stamps, values, invalid_flags = [], [], []
        bad_time = 0
        for row in data:
            if manifest.timeColumn not in positions:
                continue
            try:
                stamp = instant(row[positions[manifest.timeColumn]].strip(), timezone_name=station["timezone"])
            except Exception:
                bad_time += 1
                continue
            record, invalid = {}, {}
            for field in columns:
                source = sources.get(field)
                cell = row[positions[source]].strip() if source in positions else ""
                record[field], invalid[field] = np.nan, False
                if not cell:
                    missing_counts[field] += 1
                    continue
                try:
                    number = float(cell) * factors[field]
                    if not math.isfinite(number) or (number < 0 if ALL_UNITS[field] != "degC" else not -60 <= number <= 220):
                        raise ValueError("数值越界")
                    record[field] = number
                except (ValueError, OverflowError):
                    invalid[field] = True
                    invalid_counts[field] += 1
            stamps.append(stamp)
            values.append(record)
            invalid_flags.append(invalid)
        issue("INVALID_TIMESTAMP", None, bad_time, "无效、含糊或不存在的本地时间行已排除。")
        index = pd.DatetimeIndex(stamps) if stamps else pd.DatetimeIndex([], tz=station["timezone"])
        frame = pd.DataFrame(values, index=index, columns=columns, dtype=float)
        invalid = pd.DataFrame(invalid_flags, index=index, columns=columns, dtype=bool)
        duplicate_count = int(frame.index.duplicated(keep="first").sum())
        keep = ~frame.index.duplicated(keep="first")
        frame, invalid = frame.loc[keep].sort_index(kind="stable"), invalid.loc[keep].sort_index(kind="stable")
        issue("DUPLICATE_TIMESTAMP", None, duplicate_count, "相同时间仅保留 CSV 中第一行，其余重复行已排除。")
        if len(frame) > 1:
            times = list(map(int, frame.index.as_unit("ns").asi8))
            cadence = float(np.median([(b - a) / 60e9 for a, b in zip(times, times[1:])]))
        else:
            cadence = None
        for field in columns:
            issue("INVALID_VALUE", field, invalid_counts[field], f"{LABELS[field]}有非数值、非有限或越界原始值，已标记无效并留空。")
            issue("MISSING_VALUE", field, missing_counts[field], f"{LABELS[field]}存在缺失原始值。")
            if field in FIELDS and len(frame) and frame[field].isna().mean() > 0.8:
                issue("CORE_COVERAGE_BLOCKED", field, int(frame[field].isna().sum()), f"{LABELS[field]}核心测点缺失/无效超过 80%。", True)
        if len(frame):
            # Group only occupied wall-time bins: two distant rows must not allocate
            # every empty half-hour between them. Preserve UTC offsets at DST folds.
            half_hour_ns = 30 * 60 * 1_000_000_000
            bins = []
            for stamp in frame.index:
                offset = int(stamp.utcoffset().total_seconds()) * 1_000_000_000
                bins.append(((stamp.value + offset) // half_hour_ns) * half_hour_ns - offset)
            bin_index = pd.to_datetime(bins, utc=True).tz_convert(station["timezone"])
            normalized = frame.groupby(bin_index, sort=True).mean()
            bad_bins = invalid.groupby(bin_index, sort=True).max().reindex(normalized.index).fillna(False)
            overflow = ~np.isfinite(normalized) & normalized.notna()
            if overflow.to_numpy().any():
                issue("NORMALIZATION_OVERFLOW", None, int(overflow.sum().sum()), "重采样产生非有限值，相关值已置空。", True)
                normalized = normalized.mask(overflow)
            keep = normalized.notna().any(axis=1)
            normalized, bad_bins = normalized.loc[keep], bad_bins.loc[keep]
        else:
            normalized = frame
            bad_bins = invalid
        if not len(normalized):
            issue("DATA_EMPTY", None, 1, "没有可读取的标准化采样，请检查时间、字段映射和数值。", True)
        if cadence is None:
            issue("SAMPLING_CADENCE_UNKNOWN", None, 1, "有效时间点不足，无法判断来源采样周期。")
        elif cadence > 30.000001:
            issue("SAMPLING_INTERVAL_UNSUPPORTED", None, len(frame), "来源采样间隔超过 30 分钟，当前持续性模型无已验证的升采样策略；可查看但不能正式检测。", True)
        if normalized.index.tz_localize(None).has_duplicates:
            issue("DST_TIME_AMBIGUOUS", None, 1, "数据跨越重复的夏令时墙上时间，请拆分该区间后检测。", True)
        ranges = split_ranges(normalized.index)
        for a, b in ranges:
            block = normalized.iloc[a:b]
            for field in FIELDS:
                if block[field].isna().mean() > 0.8:
                    issue("BLOCK_COVERAGE_BLOCKED", field, int(block[field].isna().sum()), f"某连续块的{LABELS[field]}缺失超过 80%，无法检测。", True)
        # Merge repeated issues across blocks for a usable, bounded report.
        report = self._sensor_report(normalized, ranges, issue)
        if report["insufficientBlockCount"]:
            issue("SENSOR_CONTEXT_SHORT", None, report["insufficientBlockCount"], "部分连续块不足 72 小时，未据此判定长期冻结/低分辨率，后续检测仍需核对模型上下文。")
        aggregated = {}
        for entry in issues:
            key = (entry["code"], entry["field"])
            if key in aggregated:
                aggregated[key]["count"] += entry["count"]
            else:
                aggregated[key] = entry
        issues = list(aggregated.values())
        samples, column_counts = [], {f: Counter() for f in columns}
        for timestamp, row in normalized.iterrows():
            record, flags = {}, {}
            for field in columns:
                number = row[field]
                flag = "invalid" if bool(bad_bins.at[timestamp, field]) else "missing" if pd.isna(number) else "valid"
                record[field] = None if pd.isna(number) else float(number)
                flags[field] = flag
                column_counts[field][flag] += 1
            samples.append({"time_us": int(timestamp.value // 1000), "timestamp": timestamp.isoformat(), "values": record, "quality": flags})
        expected_bins = int((normalized.index[-1].value - normalized.index[0].value) // (30 * 60 * 10**9) + 1) if len(normalized) else 0
        metadata = {
            "id": uuid4().hex, "version": "1", "stationId": station["id"], "name": manifest.name,
            "status": "invalid" if any(i["blocking"] for i in issues) else "ready",
            "timezone": station["timezone"], "start": samples[0]["timestamp"] if samples else None,
            "end": samples[-1]["timestamp"] if samples else None, "rawRowCount": len(data), "normalizedRowCount": len(samples),
            "columns": [{"field": f, "label": LABELS[f], "unit": ALL_UNITS[f],
                         "validCount": column_counts[f]["valid"], "missingCount": column_counts[f]["missing"],
                         "invalidCount": column_counts[f]["invalid"]} for f in columns],
            "issues": issues, "preprocessingVersion": IMPORT_VERSION, "sourceChecksum": hashlib.sha256(raw).hexdigest(),
            "columnMapping": mapping, "sourceUnits": manifest.sourceUnits, "createdAt": now(),
            "sampling": {"sourceMedianMinutes": cadence, "normalizedMinutes": 30, "blockCount": len(ranges),
                         "maxBlockPoints": max((b - a for a, b in ranges), default=0),
                         "expectedBinCount": expected_bins, "occupiedBinCount": len(samples),
                         "coverageRatio": len(samples) / expected_bins if expected_bins else 0}, "sensorQuality": report,
        }
        return self.store.save_dataset(metadata, samples, raw)

    @staticmethod
    def _sensor_report(frame, ranges, issue):
        # This module only inspects. It never drops learned features or mutates a model.
        from ml.src.quality import assess_frame, is_severe
        checks = []
        eligible = 0
        for a, b in ranges:
            if b - a < 145:  # At least 72 hours of continuous half-hour evidence.
                continue
            eligible += 1
            health = assess_frame(frame.iloc[a:b])
            for field, state in health.items():
                if state.verdict != "ok":
                    checks.append({"field": field, "verdict": state.verdict, "start": frame.index[a].isoformat(),
                                   "end": frame.index[b - 1].isoformat(), "reasons": state.reasons})
                    if state.verdict == "idle":
                        continue
                    blocking = field == "outdoor_temperature" and is_severe(field, state)
                    issue("OUTDOOR_SENSOR_UNHEALTHY" if blocking else "SENSOR_QUALITY_NOTICE", field, b - a,
                          f"{LABELS[field]}传感器检查：{'；'.join(state.reasons)}。" + ("当前模型依赖该测点，需核查后重新导入。" if blocking else "请结合现场工况核查。"), blocking)
        return {"policyVersion": "sensor-check-continuous-72h-v1", "minimumContinuousPoints": 145,
                "checkedBlockCount": eligible, "insufficientBlockCount": len(ranges) - eligible, "findings": checks}
