"""数据加载层：把两家厂商、93 个站的原始 CSV 统一成同一套字段/单位/时间粒度。

用法:
    from src.data import load_substation, load_faults, load_normal_events
    df = load_substation("M1", 10)          # 已重采样为 30min，float32，带缓存
"""
from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd

from .common import CACHE, DATA, MFR_DIRS, MFR_TAGS, RESAMPLE, UNIT_SCALE

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

# 控制单元模式 / 泵状态 等文本量 -> 固定编码（跨站可比）
CAT_MAP = {
    "aus": 0.0, "off": 0.0, "0": 0.0,
    "ein": 1.0, "on": 1.0, "1": 1.0,
    "tag": 2.0, "day": 2.0,
    "nacht": 3.0, "night": 3.0,
    "auto": 4.0, "automatik": 4.0, "automatic": 4.0,
    "hand": 5.0, "manual": 5.0,
    "komfort": 6.0, "comfort": 6.0,
    "absenk": 7.0, "absenkung": 7.0, "setback": 7.0,
    "sommer": 8.0, "summer": 8.0,
    "winter": 9.0,
    "urlaub": 10.0, "holiday": 10.0,
    "stoerung": 11.0, "störung": 11.0, "fault": 11.0,
    "true": 1.0, "false": 0.0,
}

TEMP_COLS_SUFFIX = ("temperature",)


def norm_col(c: str) -> str:
    c = str(c).strip().lower()
    c = re.sub(r"\s+", "_", c)
    c = re.sub(r"([^a-z0-9_.])", "_", c)
    c = re.sub(r"_+", "_", c).strip("_")
    return c


def _dedupe_cols(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c}__dup{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def _to_float(s: pd.Series) -> pd.Series:
    """object 列 -> float；纯文本类别按 CAT_MAP 编码，未知记 -1。"""
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() >= 0.5:
        return num.astype("float64")
    txt = s.astype(str).str.strip().str.lower()
    return txt.map(lambda v: CAT_MAP.get(v, -1.0 if v not in ("nan", "none", "") else np.nan))


def read_raw(path, tag: str) -> pd.DataFrame:
    """读入单个站的 CSV，标准化列名/单位/时间戳，重采样到 30min。"""
    df = pd.read_csv(path, sep=";", low_memory=False)

    df.columns = _dedupe_cols([norm_col(c) for c in df.columns])
    if "timestamp" not in df.columns:
        raise ValueError(f"{path}: 找不到 timestamp 列, 实为 {list(df.columns)[:5]}")

    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.drop(columns=["timestamp"])
    df.index = pd.DatetimeIndex(ts.values)
    df = df[~df.index.isna()]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]

    # 类型统一：全部转为 float32（文本类别编码为固定数值）
    out = {}
    for c in df.columns:
        col = df[c]
        if col.dtype == object:
            col = _to_float(col)
        out[c] = pd.to_numeric(col, errors="coerce")
    df = pd.DataFrame(out, index=df.index)

    # 单位换算
    for c, k in UNIT_SCALE[tag].items():
        if c in df.columns and k != 1.0:
            df[c] = df[c] * k

    # 物理合理区间裁剪（避免明显传感器错误把标准化带偏）
    for c in df.columns:
        if c.endswith(TEMP_COLS_SUFFIX) or "temperature" in c:
            df[c] = df[c].where(df[c].between(-60, 220))
        elif "valve_position" in c:
            df[c] = df[c].where(df[c].between(-5, 105))
        elif c in ("p_net_meter_heat_power", "p_net_meter_flow", "p_net_meter_energy"):
            df[c] = df[c].where(df[c] >= -1e-6)

    # 重采样：数值取均值（30min 粒度足够做故障预警，且显著降内存）
    num = df.select_dtypes(include=[np.number])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        num = num.resample(RESAMPLE, label="left", closed="left").mean()
    # 完全没有数据的格子（整段数据缺口）直接删除，避免制造海量空行
    num = num.dropna(how="all")
    return num.astype("float32")


def substation_ids(tag: str) -> list[int]:
    d = DATA / MFR_DIRS[MFR_TAGS.index(tag)] / "operational_data"
    ids = []
    for p in d.glob("substation_*.csv"):
        try:
            ids.append(int(p.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(ids)


def cache_path(tag: str, sid: int):
    return CACHE / f"{tag}_s{sid}.pkl"


def load_substation(tag: str, sid: int, use_cache: bool = True) -> pd.DataFrame:
    """读取并缓存单个站；缓存为 pickle，二次读取 <0.5s。"""
    cp = cache_path(tag, sid)
    if use_cache and cp.exists():
        try:
            return pd.read_pickle(cp)
        except Exception:  # 缓存损坏时回退重读
            pass
    path = DATA / MFR_DIRS[MFR_TAGS.index(tag)] / "operational_data" / f"substation_{sid}.csv"
    df = read_raw(path, tag)
    df.to_pickle(cp)
    return df


# ---------------------------------------------------------------- 标签
def _read_semi(name: str, tag: str) -> pd.DataFrame:
    path = DATA / MFR_DIRS[MFR_TAGS.index(tag)] / name
    df = pd.read_csv(path, sep=";")
    df.columns = [c.strip() for c in df.columns]
    return df


def load_faults(tag: str) -> pd.DataFrame:
    df = _read_semi("faults.csv", tag)
    rename = {
        "event id": "event_id", "substation id": "sid", "report date": "report_date",
        "problem en": "problem", "event description en": "description",
        "possible anomaly start": "anomaly_start", "possible anomaly end": "anomaly_end",
        "training start": "train_start", "training end": "train_end",
        "efd_possible": "efd_possible", "fault label": "fault_label",
        "monitoring potential": "monitoring_potential",
    }
    df = df.rename(columns={c: rename.get(str(c).strip().lower(), str(c)) for c in df.columns})
    for c in ("report_date", "anomaly_start", "anomaly_end", "train_start", "train_end"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    df["sid"] = pd.to_numeric(df["sid"], errors="coerce").astype("Int64")
    df["efd_possible"] = df["efd_possible"].astype(str).str.lower().isin(["true", "1", "yes"])
    df["monitoring_potential"] = pd.to_numeric(df["monitoring_potential"], errors="coerce")
    df["manufacturer"] = tag
    return df


def load_normal_events(tag: str) -> pd.DataFrame:
    df = _read_semi("normal_events.csv", tag)
    rename = {
        "event id": "event_id", "substation id": "sid",
        "event start": "event_start", "event end": "event_end",
        "training start": "train_start", "training end": "train_end",
    }
    df = df.rename(columns={c: rename.get(str(c).strip().lower(), str(c)) for c in df.columns})
    for c in ("event_start", "event_end", "train_start", "train_end"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    df["sid"] = pd.to_numeric(df["sid"], errors="coerce").astype("Int64")
    df["manufacturer"] = tag
    return df


def load_disturbances(tag: str) -> pd.DataFrame:
    df = _read_semi("disturbances.csv", tag)
    rename = {"substation id": "sid", "event start": "event_start", "type": "type"}
    df = df.rename(columns={c: rename.get(str(c).strip().lower(), str(c)) for c in df.columns})
    if "event_start" in df.columns:
        df["event_start"] = pd.to_datetime(df["event_start"], errors="coerce")
    df["sid"] = pd.to_numeric(df["sid"], errors="coerce").astype("Int64")
    df["manufacturer"] = tag
    return df


def load_config(tag: str) -> pd.DataFrame:
    df = _read_semi("configuration_types.csv", tag)
    df.columns = [norm_col(c) for c in df.columns]
    c_map = {c: c for c in df.columns}
    if "substation_id" in c_map:
        df = df.rename(columns={"substation_id": "sid"})
    df["sid"] = pd.to_numeric(df["sid"], errors="coerce").astype("Int64")
    df["manufacturer"] = tag
    return df


def all_labels() -> pd.DataFrame:
    """合并两家的故障与正常事件，附带制造商标记，便于跨站建模。"""
    parts = []
    for tag in MFR_TAGS:
        f = load_faults(tag)
        f["kind"] = "fault"
        n = load_normal_events(tag)
        n["kind"] = "normal"
        parts.append(pd.concat([f, n], ignore_index=True, sort=False))
    out = pd.concat(parts, ignore_index=True, sort=False)
    return out
