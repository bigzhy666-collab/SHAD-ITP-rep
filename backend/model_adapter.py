"""Pure adapter reused by the future persisted task worker; never trains a model."""
from threading import Lock
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .errors import ServiceError
from .registry import ModelRegistry
from .schemas import ALL_FIELDS, ALL_UNITS, FIELDS, OPTIONAL_FIELDS, PREPROCESSING_VERSION, InferenceInput


def prepare_frame(request: InferenceInput) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    declared = set(request.units)
    if not set(FIELDS).issubset(declared) or not declared.issubset(ALL_FIELDS) or \
            any(unit != ALL_UNITS[field] for field, unit in request.units.items()):
        raise ServiceError("UNIT_UNSUPPORTED", "此接口仅接受标准单位 degC、kW、L/h；CSV 单位转换在导入阶段完成。")
    rows, stamps = [], []
    for i, sample in enumerate(request.samples):
        if set(sample.values) != declared:
            raise ServiceError("REQUIRED_FIELD_MISSING", "每个采样必须包含全部核心字段，并与单位声明中的受支持可选字段一致。",
                               details=[{"field": f"samples.{i}.values", "reason": "字段不完整或多余"}])
        try:
            stamp = pd.Timestamp(sample.timestamp)
            if stamp.tzinfo is None:
                raise ValueError("missing timezone offset")
            stamp = stamp.tz_convert(ZoneInfo(request.timezone))
            if stamp.minute % 30 or stamp.second or stamp.microsecond or stamp.nanosecond:
                raise ValueError("not on 30 minute boundary")
        except Exception as exc:
            raise ServiceError("TIME_RANGE_INVALID", "时间必须带时区偏移，并对齐站点时区的 30 分钟刻度。",
                               details=[{"field": f"samples.{i}.timestamp", "reason": "时间格式或刻度非法"}]) from exc
        row = dict(sample.values)
        for field, value in row.items():
            if value is None:
                continue
            invalid = value < 0 if field in ("p_net_meter_heat_power", "p_net_meter_flow") \
                else not -60 <= value <= 220
            if invalid:
                raise ServiceError("DATA_QUALITY_BLOCKED", "标准化采样包含越界值；请先完成数据质量处理。",
                                   details=[{"field": f"samples.{i}.values.{field}", "reason": "数值越界"}])
        stamps.append(stamp)
        rows.append(row)
    index = pd.DatetimeIndex(stamps)
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ServiceError("TIME_RANGE_INVALID", "采样时间必须严格递增且不重复。")
    wall_index = index.tz_localize(None)
    if wall_index.has_duplicates or not wall_index.is_monotonic_increasing:
        raise ServiceError("TIME_RANGE_INVALID", "该区间跨越重复的夏令时墙上时间，请拆分区间后检测。")
    columns = [f for f in ALL_FIELDS if f in declared]
    return pd.DataFrame(rows, index=wall_index, columns=columns, dtype="float64"), index


def blocks(frame: pd.DataFrame, index: pd.DatetimeIndex):
    # Both physical time and model wall time must be continuous.
    breaks = np.ones(len(frame), dtype=bool)
    if len(frame) > 1:
        half_hour = pd.Timedelta(minutes=30)
        breaks[1:] = (np.diff(index) != half_hour) | (np.diff(frame.index) != half_hour)
    starts = np.flatnonzero(breaks)
    for block_number, (start, end) in enumerate(zip(starts, [*starts[1:], len(frame)]), 1):
        chunk = frame.iloc[start:end]
        bad = chunk[list(FIELDS)].isna().mean()
        if (bad > 0.8).any():
            raise ServiceError("DATA_QUALITY_BLOCKED", "连续块内核心字段缺失超过 80%，无法可靠检测。",
                               details=[{"field": f, "reason": "连续块缺失超过 80%"}
                                        for f in FIELDS if bad[f] > 0.8])
        yield f"block-{block_number}", chunk, index[start:end]


def validate_output(output, frame: pd.DataFrame, c_thr: int):
    names = ("score", "threshold", "alarm", "criticality", "health", "confirmed")
    valid = isinstance(output, pd.DataFrame) and len(output) == len(frame) \
        and output.index.equals(frame.index) and all(k in output for k in names)
    if not valid:
        raise ServiceError("MODEL_OUTPUT_INVALID", "模型输出结构与输入时间不一致。", 500)
    try:
        values = output[list(names)].to_numpy(dtype=float)
        score, threshold, alarm, criticality, health, confirmed = values.T
        expected_alarm = score > threshold
        expected_c, count = [], 0
        for flag in expected_alarm:
            count = count + 1 if flag else max(0, count - 1)
            expected_c.append(count)
        expected_health = np.clip(1 - score / np.where(threshold > 0, threshold, 1e-9), 0, 1)
        valid = np.isfinite(values).all() and (score >= 0).all() and (threshold > 0).all() \
            and np.array_equal(alarm, expected_alarm) and np.array_equal(criticality, expected_c) \
            and np.array_equal(confirmed, np.array(expected_c) >= c_thr) \
            and np.allclose(health, expected_health, rtol=1e-9, atol=1e-12)
    except (TypeError, ValueError, ZeroDivisionError):
        valid = False
    if not valid:
        raise ServiceError("MODEL_OUTPUT_INVALID", "模型输出包含非有限值或不一致的检测标记。", 500)


def confirmed_segments(points: list[dict]) -> list[dict]:
    segments, run = [], []

    def finish():
        if not run:
            return
        first, last = run[0], run[-1]
        at_start = first["timestamp"] == points[0]["timestamp"]
        at_end = last["timestamp"] == points[-1]["timestamp"]
        segments.append({
            "blockId": first["blockId"], "kind": "station_state_anomaly",
            "title": "换热站运行状态偏离正常水平",
            "start": first["timestamp"], "end": last["timestamp"],
            "hours": (pd.Timestamp(last["timestamp"]) - pd.Timestamp(first["timestamp"])).total_seconds() / 3600,
            "peak_score": max(p["score"] for p in run),
            "max_criticality": max(p["criticality"] for p in run),
            "affectedMetrics": None, "cause": None, "solution": None,
            "boundary": "touches_both" if at_start and at_end else
                        "touches_range_start" if at_start else "touches_range_end" if at_end else "within_range",
        })
        run.clear()

    for point in points:
        if run and point["blockId"] != run[-1]["blockId"]:
            finish()
        if point["confirmed"]:
            run.append(point)
        else:
            finish()
    finish()
    return segments


class ModelService:
    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self._execution_lock = Lock()

    def infer(self, request: InferenceInput) -> dict:
        station = self.registry.stations.get(request.stationId)
        if station is None:
            raise ServiceError("STATION_BINDING_REQUIRED", "请先由管理员登记换热站及本站模型。")
        entry = self.registry.entries.get((request.modelId, request.modelVersion))
        if entry is None:
            raise ServiceError("NOT_FOUND", "未登记此模型版本。", 404)
        if entry.stationId != request.stationId:
            raise ServiceError("SOURCE_MISMATCH", "模型与采样所属站点不一致。")
        if request.timezone != entry.trainingTimezone or request.timezone != station["timezone"]:
            raise ServiceError("TIMEZONE_MISMATCH", "输入、站点和模型的时区必须一致。")
        frame, index = prepare_frame(request)
        chunks = list(blocks(frame, index))  # Validate every block before doing any inference.
        if not self._execution_lock.acquire(blocking=False):
            raise ServiceError("MODEL_BUSY", "模型正在执行其他请求，请完成后重试。", 503, True)
        try:
            entry, model = self.registry.resolve(request.modelId, request.modelVersion)
            points = []
            for block_id, chunk, stamps in chunks:
                try:
                    output = model.detect(chunk.copy())
                except Exception as exc:
                    raise ServiceError("MODEL_EXECUTION_FAILED", "模型计算失败，请查看本机服务日志。",
                                       500, True) from exc
                validate_output(output, chunk, model.c_thr)
                for stamp, (_, row) in zip(stamps, output.iterrows()):
                    points.append({
                        "timestamp": stamp.isoformat(), "blockId": block_id,
                        "score": float(row["score"]), "threshold": float(row["threshold"]),
                        "alarm": bool(row["alarm"]), "criticality": int(row["criticality"]),
                        "health": float(row["health"]), "confirmed": bool(row["confirmed"]),
                    })
            segments = confirmed_segments(points)
            warnings = []
            if any(len(chunk) < 48 for _, chunk, _ in chunks):
                warnings.append({"code": "FEATURE_CONTEXT_SHORT", "message": "部分连续块不足 24 小时，时间窗口特征上下文不足；未补造区间外数据。"})
            if any(len(chunk) < model.c_thr for _, chunk, _ in chunks):
                warnings.append({"code": "CONFIRMATION_CONTEXT_SHORT", "message": "部分连续块不足持续性确认所需点数，无确认事件不等于状态正常。"})
            if any(f not in frame or frame[f].isna().any() for f in OPTIONAL_FIELDS):
                warnings.append({"code": "OPTIONAL_INPUTS_OMITTED", "message": "部分可选测点未提供或存在缺失；依赖这些测点的缺失特征按模型训练期补值处理。"})
            if len(chunks) > 1:
                warnings.append({"code": "DATA_GAPS", "message": "数据包含缺口，已分块检测并分别重置 criticality。"})
            if entry.isDemo:
                warnings.append({"code": "DEMO_MODEL", "message": "正在执行示例模型；结果用于接口验证，不构成本站模型适用性或诊断准确性证明。"})
            return {
                "stationId": request.stationId, "modelSnapshot": self.registry.metadata(entry, model),
                "preprocessingVersion": PREPROCESSING_VERSION,
                "range": {"start": index[0].isoformat(), "end": index[-1].isoformat()},
                "summary": {"pointCount": len(points), "alarmPointCount": sum(p["alarm"] for p in points),
                            "confirmedPointCount": sum(p["confirmed"] for p in points),
                            "eventCount": len(segments), "blockCount": len(chunks),
                            "qualityIssueCount": int(frame.isna().sum().sum())},
                "warnings": warnings, "points": points, "segments": segments,
                "persisted": False,
            }
        finally:
            self._execution_lock.release()
