"""特征工程：从原始测点构造物理量残差 + 统计窗口特征。

设计原则（写进技术方案的核心）：
 1. 物理量优先：供回温差、偏离设定值、偏离供暖曲线、功率/温差比 —— 这些是供热行业
    调试人员真正用来判断"站是不是不对劲"的量，可解释、可迁移到国内热力站。
 2. 用"残差"而非"绝对值"：供热站随室外温度、季节、昼夜、负荷变化剧烈，
    直接建模绝对温度学到的只是天气；残差把工况抵消掉，异常才凸显。
 3. 窗口统计：单个 30min 点噪声大，一段时间的残差分布（均值/方差/极值/斜率）才是状态。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import ALL_RAW

# 参与窗口聚合的工程特征
WINDOW_FEATS = [
    "err_supply", "err_return", "err_dhw", "err_storage_upper",
    "dt_primary", "dt_hc1", "storage_delta", "curve_residual",
    "power_per_dt", "flow_norm", "load_index", "stuck_score", "miss_rate",
    "outdoor_temperature", "s_hc1_supply_temperature", "s_hc1_supply_temperature_setpoint",
    "p_net_meter_heat_power", "p_net_meter_flow",
]

WINDOW_STATS = ["mean", "std", "min", "max", "p10", "p90", "absmean", "slope"]

# 紧凑物理特征集：与原始测点混用会导致维度爆炸（60+ 维），MD 协方差估不准、AE 退化为恒等映射。
# 这个子集是"调试人员真正会看的量"，约 20 维，兼顾可解释与统计稳定性。
PHYS_COLS = [
    "outdoor_temperature",
    "p_net_supply_temperature",
    "p_net_return_temperature",
    "p_net_meter_heat_power",
    "p_net_meter_flow",
    "p_hc1_return_temperature",
    "s_hc1_supply_temperature",
    "s_hc1_supply_temperature_setpoint",
    "dt_primary",
    "dt_hc1",
    "err_supply",
    "err_return",
    "err_dhw",
    "err_storage_upper",
    "storage_delta",
    "curve_residual",
    "power_per_dt",
    "flow_norm",
    "load_index",
    "stuck_score",
    "miss_rate",
    "hour_sin",
    "hour_cos",
    "dow",
    "is_night",
    "is_heating_season",
]


def add_cyclic_features(df: pd.DataFrame) -> pd.DataFrame:
    """循环时间特征（小时/星期/年内日），刻画季节与昼夜工况。"""
    df = df.copy()
    idx = df.index
    hour = idx.hour + idx.minute / 60.0
    doy = idx.dayofyear.astype(float)
    dow = idx.dayofweek.astype(float)
    df["cyc_hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["cyc_hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["cyc_dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["cyc_dow_cos"] = np.cos(2 * np.pi * dow / 7)
    df["cyc_doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["cyc_doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    return df


def build_features(df: pd.DataFrame, reference: dict | None = None,
                   mode: str = "phys2", cyclic: bool = True) -> pd.DataFrame:
    """训练/推理共用的特征构建入口（保证线上线下一致）。"""
    if mode in ("phys", "phys2"):
        out = add_point_features(df, reference=reference)
        if mode == "phys2":
            out = select_phys(out)
    else:
        out = df.copy()
    if cyclic:
        out = add_cyclic_features(out)
    return out


def select_phys(df: pd.DataFrame, extra: list[str] | None = None) -> pd.DataFrame:
    """只保留紧凑物理特征集（缺失的列自动跳过）。"""
    cols = [c for c in PHYS_COLS + (extra or []) if c in df.columns]
    return df[cols]


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name].astype("float64")
    return pd.Series(np.nan, index=df.index, dtype="float64")


def _safe_div(a: pd.Series, b: pd.Series, floor: float = 1e-6) -> pd.Series:
    return a / b.where(b.abs() > floor)


def curve_reference(ref: pd.DataFrame, n_bins: int = 24) -> pd.DataFrame:
    """用参照期数据建立"室外温度 -> 供水温度"的经验曲线（分箱中位数）。

    返回 DataFrame(index=bin_center, 列: supply_med, setpoint_med, cnt)
    """
    out = _col(ref, "outdoor_temperature")
    sup = _col(ref, "s_hc1_supply_temperature")
    sp = _col(ref, "s_hc1_supply_temperature_setpoint")
    frame = pd.DataFrame({"out": out, "sup": sup, "sp": sp}).dropna(subset=["out"])
    if len(frame) < 200 or frame["out"].nunique() < 5:
        return pd.DataFrame(columns=["supply_med", "setpoint_med", "cnt"])
    lo, hi = np.nanpercentile(frame["out"], [1, 99])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-6:
        return pd.DataFrame(columns=["supply_med", "setpoint_med", "cnt"])
    bins = np.linspace(lo, hi, n_bins + 1)
    frame["bin"] = pd.cut(frame["out"], bins, include_lowest=True)
    g = frame.groupby("bin", observed=True)
    ref_curve = pd.DataFrame({
        "supply_med": g["sup"].median(),
        "setpoint_med": g["sp"].median(),
        "cnt": g["out"].count(),
    })
    centers = np.array([iv.mid for iv in ref_curve.index], dtype=float)
    ref_curve.index = centers
    return ref_curve


def _apply_curve(df: pd.DataFrame, ref_curve: pd.DataFrame) -> pd.Series:
    """偏离供暖曲线：实际供水温度 - 同室外温度下的历史中位数。"""
    if ref_curve is None or len(ref_curve) == 0:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    out = _col(df, "outdoor_temperature")
    sup = _col(df, "s_hc1_supply_temperature")
    idx = ref_curve.index.values.astype(float)
    base = np.interp(np.clip(out.values, idx[0], idx[-1]),
                     idx, ref_curve["supply_med"].values)
    return pd.Series(sup.values - base, index=df.index, dtype="float64")


def fit_reference(ref: pd.DataFrame) -> dict:
    """从参照期（训练期）数据拟合可持久化的基准：供暖曲线 + 流量中位数。"""
    return {
        "curve": curve_reference(ref),
        "flow_median": float(np.nanmedian(_col(ref, "p_net_meter_flow").values)) if len(ref) else np.nan,
    }


def add_point_features(df: pd.DataFrame, ref: pd.DataFrame | None = None,
                       reference: dict | None = None) -> pd.DataFrame:
    """在原始测点上生成工程特征。

    ref: 参照期（训练期）数据，用于拟合供暖曲线/流量基准；
    reference: 已拟合好的基准字典（推理时从模型产物里读，保证训练/推理一致）。
    """
    df = df.copy()
    if reference is None:
        reference = fit_reference(df if ref is None else ref)
    ref_curve = reference["curve"]
    flow_ref = reference["flow_median"]

    out = df[df.columns].astype("float64")

    out["dt_primary"] = _col(df, "p_net_supply_temperature") - _col(df, "p_net_return_temperature")
    out["dt_hc1"] = _col(df, "s_hc1_supply_temperature") - _col(df, "p_hc1_return_temperature")
    out["err_supply"] = _col(df, "s_hc1_supply_temperature") - _col(df, "s_hc1_supply_temperature_setpoint")
    out["err_return"] = _col(df, "p_hc1_return_temperature") - _col(df, "p_hc1_return_temperature_setpoint")
    out["err_dhw"] = _col(df, "s_dhw_supply_temperature") - _col(df, "s_dhw_supply_temperature_setpoint")
    out["err_storage_upper"] = (_col(df, "s_dhw_upper_storage_temperature")
                                - _col(df, "s_dhw_upper_storage_temperature_setpoint"))
    out["storage_delta"] = (_col(df, "s_dhw_upper_storage_temperature")
                            - _col(df, "s_dhw_lower_storage_temperature"))
    out["curve_residual"] = _apply_curve(df, ref_curve)

    power = _col(df, "p_net_meter_heat_power")
    out["power_per_dt"] = _safe_div(power, out["dt_primary"].clip(lower=0.5))
    out["flow_norm"] = _col(df, "p_net_meter_flow") / flow_ref if np.isfinite(flow_ref) and flow_ref > 0 else np.nan
    outdoor = _col(df, "outdoor_temperature")
    out["load_index"] = _safe_div(power, (18.0 - outdoor).clip(lower=1.0))
    out["outdoor_temperature"] = outdoor

    # 传感器冻结：24h 窗口内供水温度的标准差；正常站也不会完全不变
    std24 = _col(df, "s_hc1_supply_temperature").rolling(48, min_periods=24).std()
    out["stuck_score"] = np.log1p(std24.fillna(0.0))
    # 数据质量：6h 内关键量缺失比例
    core = ["outdoor_temperature", "s_hc1_supply_temperature", "p_net_supply_temperature",
            "p_net_meter_flow"]
    miss = pd.concat([_col(df, c).isna() for c in core], axis=1).mean(axis=1)
    out["miss_rate"] = miss.rolling(12, min_periods=1).mean()

    # 时间上下文
    idx = df.index
    hour = idx.hour + idx.minute / 60.0
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["dow"] = idx.dayofweek.astype("float64")
    out["month"] = idx.month.astype("float64")
    out["is_night"] = ((idx.hour >= 22) | (idx.hour <= 6)).astype("float64")
    out["is_heating_season"] = ((outdoor < 15) | outdoor.isna()).astype("float64")

    # 一阶差分（1h / 24h），刻画"变化趋势"而非水平
    for c in ("err_supply", "dt_primary", "storage_delta", "curve_residual"):
        out[f"{c}_d1h"] = out[c].diff(2)
        out[f"{c}_d24h"] = out[c].diff(48)

    return out.astype("float32")


def _slope(y: np.ndarray) -> float:
    """窗口内的标准化线性斜率（单位: 每小时的相对变化量）。"""
    if len(y) < 4 or not np.isfinite(y).any():
        return np.nan
    yy = pd.Series(y, dtype="float64")
    if yy.isna().all():
        return np.nan
    yy = yy.interpolate(limit_direction="both").values
    scale = np.nanstd(yy)
    if not np.isfinite(scale) or scale < 1e-9:
        return 0.0
    x = np.arange(len(yy), dtype=float)
    beta = np.polyfit(x, yy, 1)[0]
    return float(beta / scale * 2.0)   # 每 30min -> 每小时


def window_features(df: pd.DataFrame, start, end, win_hours: float = 6.0,
                    stride_hours: float = 3.0) -> pd.DataFrame:
    """把 [start, end] 区间切成滑窗，对每个窗口输出 (特征, 统计量) 宽表。

    df 必须是 add_point_features 之后、按时间升序的 DataFrame。
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if pd.isna(start) or pd.isna(end) or end <= start:
        return pd.DataFrame()

    rows = 2 * win_hours   # 30min 采样 -> 每窗口行数
    step = max(1, int(2 * stride_hours))
    feats = [c for c in WINDOW_FEATS if c in df.columns]
    if not feats:
        return pd.DataFrame()

    lo = df.index.searchsorted(start, side="left")
    hi = df.index.searchsorted(end, side="right")
    if hi - lo < 8:
        return pd.DataFrame()

    vals = df[feats].to_numpy(dtype="float32")
    recs = []
    for i in range(lo, hi - 4, step):
        seg = vals[i: min(i + int(rows), hi)]
        if len(seg) < 4:
            continue
        w_start = df.index[i]
        rec = {"window_start": w_start,
               "window_end": df.index[min(i + int(rows) - 1, hi - 1)],
               "n_points": int(len(seg)),
               "coverage": float(np.isfinite(seg).mean())}
        for j, f in enumerate(feats):
            col = seg[:, j].astype("float64")
            ok = col[np.isfinite(col)]
            if ok.size == 0:
                for stat in WINDOW_STATS:
                    rec[f"{f}__{stat}"] = np.nan
                continue
            rec[f"{f}__mean"] = float(ok.mean())
            rec[f"{f}__std"] = float(ok.std(ddof=0))
            rec[f"{f}__min"] = float(ok.min())
            rec[f"{f}__max"] = float(ok.max())
            rec[f"{f}__p10"] = float(np.percentile(ok, 10))
            rec[f"{f}__p90"] = float(np.percentile(ok, 90))
            rec[f"{f}__absmean"] = float(np.abs(ok).mean())
            rec[f"{f}__slope"] = _slope(col)
        rec["outdoor_mean"] = float(np.nanmean(seg[:, feats.index("outdoor_temperature")])) \
            if "outdoor_temperature" in feats else np.nan
        rec["month"] = float(w_start.month)
        rec["hour"] = float(w_start.hour)
        recs.append(rec)

    if not recs:
        return pd.DataFrame()
    return pd.DataFrame(recs)
