"""事件协议层：严格按 PreDist 论文 §4.1–§4.4 实现"每个事件一个正常行为模型"的评估。

核心约定（与论文一致）：
  - 异常事件：测试窗 = [t_report - 7d, t_report]（终点是报修时刻 → 任何检出都是"提前"）
  - 正常事件：测试窗 = [Event start, Event end]
  - 训练集：Training start → Training end，剔除故障/维修段，且不含测试窗数据
  - 点级分数 > t_AE(训练分数 99% 分位) → criticality C += 1，否则 C -= 1（下限 0）
  - C_max ≥ C_thr ⇒ 判为该事件异常（TP / FP）
  - 指标：点级 Accuracy A、事件级 F0.5、Earliness E（W=24h）、lead time
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .common import GRACE_HOURS
from .data import load_config, load_disturbances, load_faults, load_normal_events, MFR_TAGS

TEST_WINDOW_DAYS = 7
MIN_TRAIN_DAYS = 14
REPORT_GRACE_HOURS = 48       # 报修前 48h 也是故障段（论文 §2.2 第 5 条）
REPAIR_GRACE_HOURS = 24       # 无维修记录时假设报修后 24h 修复

# 论文/官方 YAML 中排除的特征
EXCLUDE_PATTERNS = (
    "p_net_meter_energy",      # 累计电量，用功率代替
    "p_net_meter_volume",      # 累计体积，用流量代替
    "_control_unit_mode",      # 字符串模式量
    "_room_temperature_setpoint",
    "__dup",                   # 重名列
)


@dataclass
class Event:
    manufacturer: str
    event_id: int
    sid: int
    kind: str                      # 'fault' | 'normal'
    report_date: pd.Timestamp | None
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_start: pd.Timestamp | None
    train_end: pd.Timestamp | None
    anomaly_start: pd.Timestamp | None = None
    anomaly_end: pd.Timestamp | None = None
    fault_label: str | None = None
    monitoring_potential: float = np.nan
    config_type: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.manufacturer}_E{self.event_id}_S{self.sid}_{self.kind}"


# ---------------------------------------------------------------- 事件筛选
def select_events(min_train_days: int = MIN_TRAIN_DAYS) -> pd.DataFrame:
    """按论文 §4.1 的 5 条纳入条件筛事件，返回事件表。"""
    rows = []
    for tag in MFR_TAGS:
        cfg = load_config(tag)
        cfg_map = dict(zip(cfg["sid"].astype("int64"), cfg.get("configuration_type", "")))

        f = load_faults(tag)
        f = f[f["efd_possible"]].copy()
        f = f[f["train_start"].notna()]
        # Training end 缺失（M1 Event 69）→ 用 report-14d 补齐，记录该决策
        f["train_end_filled"] = f["train_end"].isna()
        f["train_end"] = f["train_end"].fillna(f["report_date"] - pd.Timedelta(days=min_train_days))
        f["train_days"] = (f["train_end"] - f["train_start"]).dt.total_seconds() / 86400
        f = f[f["train_days"] >= min_train_days]
        # 同一站同一故障类型多次报修只保留第一次
        f = f.sort_values("report_date").drop_duplicates(subset=["sid", "fault_label"], keep="first")

        for _, r in f.iterrows():
            rep = r["report_date"]
            rows.append(Event(
                manufacturer=tag, event_id=int(r["event_id"]), sid=int(r["sid"]), kind="fault",
                report_date=rep,
                test_start=rep - pd.Timedelta(days=TEST_WINDOW_DAYS), test_end=rep,
                train_start=r["train_start"], train_end=r["train_end"],
                anomaly_start=r.get("anomaly_start"), anomaly_end=r.get("anomaly_end"),
                fault_label=str(r.get("fault_label")), monitoring_potential=r.get("monitoring_potential", np.nan),
                config_type=cfg_map.get(int(r["sid"]), ""),
                extra={"problem": r.get("problem"), "train_end_filled": bool(r["train_end_filled"])},
            ))

        n = load_normal_events(tag)
        n = n[n["train_start"].notna()]
        for _, r in n.iterrows():
            rows.append(Event(
                manufacturer=tag, event_id=int(r["event_id"]), sid=int(r["sid"]), kind="normal",
                report_date=None,
                test_start=r["event_start"], test_end=r["event_end"],
                train_start=r["train_start"], train_end=r["train_end"],
                config_type=cfg_map.get(int(r["sid"]), ""),
            ))

    ev = pd.DataFrame([e.__dict__ for e in rows])
    return ev


# ---------------------------------------------------------------- 训练/测试数据
def _disturbance_mask(index: pd.DatetimeIndex, disturbances: pd.DataFrame,
                      sid: int, pad_hours: float = 4.0) -> np.ndarray:
    mask = np.zeros(len(index), dtype=bool)
    d = disturbances[disturbances["sid"] == sid]
    for t in d["event_start"].dropna():
        lo = np.searchsorted(index.values, np.datetime64(t - pd.Timedelta(hours=pad_hours)))
        hi = np.searchsorted(index.values, np.datetime64(t + pd.Timedelta(hours=pad_hours)))
        mask[max(0, lo):min(len(index), hi)] = True
    return mask


def build_train_frame(df: pd.DataFrame, ev: Event, disturbances: pd.DataFrame) -> pd.DataFrame:
    """取训练区间，剔除故障段与维修扰动段。"""
    lo, hi = ev.train_start, ev.train_end
    if lo is None or hi is None or pd.isna(lo) or pd.isna(hi):
        return df.iloc[0:0]
    seg = df.loc[lo:hi]
    if len(seg) < 200:
        return seg.iloc[0:0]

    keep = np.ones(len(seg), dtype=bool)
    idx = seg.index

    # 1) 本事件自身的故障段
    if ev.kind == "fault" and pd.notna(ev.anomaly_start):
        end = ev.anomaly_end if pd.notna(ev.anomaly_end) else ev.report_date + pd.Timedelta(hours=REPAIR_GRACE_HOURS)
        guard = end + pd.Timedelta(hours=4)
        keep &= ~((idx >= ev.anomaly_start) & (idx <= guard))
    elif ev.kind == "fault":
        # 报修前看不到异常 → 剔除报修前 48h 到报修后 24h
        keep &= ~((idx >= ev.report_date - pd.Timedelta(hours=REPORT_GRACE_HOURS))
                  & (idx <= ev.report_date + pd.Timedelta(hours=REPAIR_GRACE_HOURS)))

    # 2) 训练区间内的历史故障/维修扰动（±4h）
    keep &= ~_disturbance_mask(idx, disturbances, ev.sid, pad_hours=4.0)

    return seg[keep]


def build_test_frame(df: pd.DataFrame, ev: Event) -> pd.DataFrame:
    seg = df.loc[ev.test_start:ev.test_end]
    return seg


def maintenance_mask(index: pd.DatetimeIndex, sid: int, disturbances: pd.DataFrame) -> np.ndarray:
    """criticality 在"预期异常/维修"期间保持不变（论文 §4.2）。"""
    mask = np.zeros(len(index), dtype=bool)
    d = disturbances[(disturbances["sid"] == sid)]
    for _, r in d.iterrows():
        t = r["event_start"]
        if pd.isna(t):
            continue
        dur = 4.0 if str(r.get("type", "")).strip().lower() in ("task", "activity") else 1.0
        lo = np.searchsorted(index.values, np.datetime64(t - pd.Timedelta(hours=1)))
        hi = np.searchsorted(index.values, np.datetime64(t + pd.Timedelta(hours=dur)))
        mask[max(0, lo):min(len(index), hi)] = True
    return mask


# ---------------------------------------------------------------- 特征准备（论文 §2.3）
def is_excluded(col: str) -> bool:
    return any(p in col for p in EXCLUDE_PATTERNS)


def prepare_xy(train_df: pd.DataFrame, test_df: pd.DataFrame, drop_cols: list[str] | None = None):
    """论文口径的预处理：剔恒定列 / 缺失>80% / 零值占比>50% 列，均值填补，标准化，分位裁剪。

    drop_cols: 由传感器体检给出的、需要降级剔除的特征（含其派生特征）。
    """
    drop_set = set(drop_cols or ())
    cand = [c for c in train_df.columns
            if c not in ("timestamp",) and c not in drop_set and not is_excluded(c)
            and pd.api.types.is_numeric_dtype(train_df[c])]
    Xtr = train_df[cand].astype("float64")
    Xte = test_df.reindex(columns=cand).astype("float64")

    miss = Xtr.isna().mean()
    std = Xtr.std(ddof=0)
    zero_frac = (Xtr == 0).mean()
    keep = [c for c in cand
            if miss.get(c, 1.0) <= 0.8 and std.get(c, 0.0) > 1e-9 and zero_frac.get(c, 1.0) <= 0.5]
    if len(keep) < 3:
        return None

    Xtr = Xtr[keep]
    Xte = Xte[keep] if not Xte.empty else pd.DataFrame(columns=keep)

    mu = Xtr.mean()
    Xtr = Xtr.fillna(mu)
    Xte = Xte.fillna(mu)
    lo_q, hi_q = Xtr.quantile(0.001), Xtr.quantile(0.999)
    Xtr = Xtr.clip(lo_q, hi_q, axis=1)
    if not Xte.empty:
        Xte = Xte.clip(lo_q, hi_q, axis=1)
    sd = Xtr.std(ddof=0).replace(0, 1.0)
    Xtr = (Xtr - mu) / sd
    if not Xte.empty:
        Xte = (Xte - mu) / sd
    return Xtr.to_numpy("float64"), Xte.to_numpy("float64"), keep


# ---------------------------------------------------------------- 持续性判据与指标
def criticality_from_mask(alarm: np.ndarray, maintenance: np.ndarray | None = None) -> np.ndarray:
    """由点级报警布尔序列生成 criticality 路径（+1 / -1，下限 0；维修期不变）。"""
    c = 0
    path = np.zeros(len(alarm), dtype=np.int32)
    for i in range(len(alarm)):
        if maintenance is not None and maintenance[i]:
            path[i] = c
            continue
        if alarm[i]:
            c += 1
        else:
            c = max(0, c - 1)
        path[i] = c
    return path


def criticality_path(score: np.ndarray, t_ae: float, maintenance: np.ndarray | None = None) -> np.ndarray:
    return criticality_from_mask(score > t_ae, maintenance)


def outdoor_quality_ok(outdoor: pd.Series) -> bool:
    """判断室外温度是否可用于分箱自适应阈值（M2 有多个站传感器坏/常值）。"""
    x = pd.to_numeric(outdoor, errors="coerce").to_numpy("float64")
    if len(x) < 200:
        return False
    finite = np.isfinite(x)
    if finite.mean() < 0.7:
        return False
    v = x[finite]
    if v.std(ddof=0) < 0.5:                      # 近乎常数 → 传感器冻结/未接
        return False
    if np.unique(np.round(v, 1)).size < 50:      # 分辨率过低
        return False
    p1, p99 = np.nanpercentile(v, [1, 99])
    if p99 - p1 < 2.0:                           # 季节跨度太小，无法分箱
        return False
    if v.min() < -45 or v.max() > 55:            # 超物理范围
        return False
    return True


def adaptive_threshold(train_outdoor: pd.Series, train_score: np.ndarray,
                       test_outdoor: pd.Series, q: float = 0.99, n_bins: int = 5) -> np.ndarray:
    """工况自适应阈值：按室外温度分箱，各箱独立取训练分数 q 分位。

    供热站负荷随室外温度大幅漂移，全站共用单一阈值会在极端天气下大量误报/漏报。
    但前提是室外温度数据本身可信——质量不达标时退化为全局阈值（否则会放大误报）。
    """
    global_thr = float(np.quantile(train_score, q))
    out_tr = pd.to_numeric(train_outdoor, errors="coerce").to_numpy("float64")
    out_te = pd.to_numeric(test_outdoor, errors="coerce").to_numpy("float64")
    ok = np.isfinite(out_tr)
    if not outdoor_quality_ok(train_outdoor) or ok.sum() < 200:
        return np.full(len(out_te), global_thr)
    edges = np.unique(np.nanquantile(out_tr[ok], np.linspace(0, 1, n_bins + 1)))
    if len(edges) < 3:
        return np.full(len(out_te), global_thr)
    bins_tr = np.digitize(out_tr, edges[1:-1])
    bins_te = np.digitize(np.nan_to_num(out_te, nan=np.nanmedian(out_tr[ok])), edges[1:-1])
    thr_map = {}
    for b in np.unique(bins_tr):
        m = bins_tr == b
        if m.sum() >= 100:
            thr_map[int(b)] = float(np.quantile(train_score[m], q))
    default = float(np.median(list(thr_map.values()))) if thr_map else global_thr
    return np.array([thr_map.get(int(b), default) for b in bins_te], dtype="float64")


def cusum_path(score: np.ndarray, t_ae: float, k: float = 0.5, maintenance: np.ndarray | None = None) -> np.ndarray:
    """CUSUM 变体：累积标准化超额，替代 ±1 计数，可更早触发。

    z = (score - t_ae) / (0.5*t_ae + eps)；S = max(0, S + z - k)，输出 int(S)。
    """
    z = (score - t_ae) / (0.5 * abs(t_ae) + 1e-9)
    out = np.zeros(len(score), dtype=np.int32)
    s = 0.0
    for i in range(len(score)):
        if maintenance is not None and maintenance[i]:
            out[i] = int(s)
            continue
        s = max(0.0, s + z[i] - k)
        out[i] = int(s)
    return out


def event_metrics(c_paths: dict[str, tuple[np.ndarray, str]], c_thr: int) -> dict:
    """给定 C_thr，算事件级混淆矩阵 + 点级 A + 事件级误报率。"""
    tp = fp = fn = tn = 0
    accs = []
    for key, (path, kind) in c_paths.items():
        cmax = int(path.max()) if len(path) else 0
        if kind == "fault":
            if cmax >= c_thr:
                tp += 1
            else:
                fn += 1
        else:
            if cmax >= c_thr:
                fp += 1
            else:
                tn += 1
            # 点级 accuracy：正常事件中 C < C_thr 的点占比（≈1-点级误报率）
            accs.append(float((path < c_thr).mean()) if len(path) else 1.0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f05 = (1.25 * precision * recall / (0.25 * precision + recall)) if precision + recall else 0.0
    return {
        "c_thr": c_thr, "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "f0_5": f05,
        "A": float(np.mean(accs)) if accs else np.nan,
        "FAR_event": fp / (fp + tn) if fp + tn else np.nan,
    }


def metrics_with_lead(c_paths: dict, times: dict, report_times: dict, c_thr: int) -> dict:
    """完整指标：事件级 + 点级 + 提前量（需要每个事件的时间戳序列）。"""
    out = event_metrics(c_paths, c_thr)
    leads, ears = [], []
    for key, (path, kind) in c_paths.items():
        if kind != "fault":
            continue
        if len(path) == 0 or path.max() < c_thr:
            ears.append(0.0)
            continue
        idx = int(np.argmax(path >= c_thr))
        t_det = times[key][idx]
        lead_h = (report_times[key] - t_det).total_seconds() / 3600.0
        leads.append(lead_h)
        ears.append(float(min(1.0, max(0.0, lead_h / 24.0))))
    out["E"] = float(np.mean(ears)) if ears else np.nan
    out["lead_days_mean"] = float(np.mean(leads) / 24.0) if leads else np.nan
    out["lead_days_median"] = float(np.median(leads) / 24.0) if leads else np.nan
    out["n_detected"] = len(leads)
    return out
