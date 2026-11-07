"""传感器健康度体检与特征降级。

动机（来自实验结果）：M2 的检测指标明显弱于 M1，且"训练数据少"这个假设已被证伪
（短训练窗事件检出率 0.696 > 总体 0.440）。真正的瓶颈是**传感器数据质量**：
M2 有多个站室外温度传感器冻结/常值/越界（README 与本地探查都记录过）。
坏传感器会 ① 从输入里直接吃进错误信号；② 让分箱自适应阈值失去意义。

本模块做三件事：
  1. 逐列体检：缺失率、常值/冻结、越界、分辨率、尖峰；
  2. 特征降级：把与坏传感器相关的派生特征一并剔除（不是只删那一列）；
  3. 阈值降级：室外温度不健康时强制关闭工况自适应阈值。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# 物理合理区间
BOUNDS = {
    "outdoor_temperature": (-50.0, 55.0),
    "p_net_supply_temperature": (-20.0, 200.0),
    "p_net_return_temperature": (-20.0, 200.0),
    "p_hc1_return_temperature": (-20.0, 200.0),
    "s_hc1_supply_temperature": (-20.0, 200.0),
    "s_hc1_supply_temperature_setpoint": (-20.0, 200.0),
    "s_dhw_supply_temperature": (-20.0, 200.0),
    "s_dhw_upper_storage_temperature": (-20.0, 200.0),
    "s_dhw_lower_storage_temperature": (-20.0, 200.0),
    "p_net_meter_heat_power": (0.0, 1e7),
    "p_net_meter_flow": (0.0, 1e9),
}

# 每列被判坏时，需要一并剔除的派生特征
DEPENDENTS = {
    "outdoor_temperature": ["outdoor_temperature", "curve_residual", "load_index",
                            "is_heating_season", "miss_rate"],
    "p_net_supply_temperature": ["p_net_supply_temperature", "dt_primary", "power_per_dt"],
    "p_net_return_temperature": ["p_net_return_temperature", "dt_primary", "power_per_dt"],
    "p_net_meter_heat_power": ["p_net_meter_heat_power", "power_per_dt", "load_index"],
    "p_net_meter_flow": ["p_net_meter_flow", "flow_norm", "miss_rate"],
    "s_hc1_supply_temperature": ["s_hc1_supply_temperature", "err_supply", "dt_hc1",
                                 "curve_residual", "stuck_score", "miss_rate"],
    "s_hc1_supply_temperature_setpoint": ["s_hc1_supply_temperature_setpoint", "err_supply"],
    "p_hc1_return_temperature": ["p_hc1_return_temperature", "dt_hc1"],
    "p_hc1_return_temperature_setpoint": ["p_hc1_return_temperature_setpoint", "err_return"],
    "s_dhw_supply_temperature": ["s_dhw_supply_temperature", "err_dhw"],
    "s_dhw_supply_temperature_setpoint": ["s_dhw_supply_temperature_setpoint", "err_dhw"],
    "s_dhw_upper_storage_temperature": ["s_dhw_upper_storage_temperature", "err_storage_upper",
                                        "storage_delta"],
    "s_dhw_lower_storage_temperature": ["s_dhw_lower_storage_temperature", "storage_delta"],
}

# 论文/README 中人工记录的已知坏传感器（用作外部验证的"标准答案"）
KNOWN_BAD_OUTDOOR = {
    ("M1", 19): "README：室外温度传感器损坏（探查发现 -64~191.7℃ 越界）",
    ("M2", 18): "README：室外温度不可用/不合理",
    ("M2", 41): "README：室外温度不可用/不合理",
    ("M2", 61): "README：室外温度不可用/不合理",
    ("M2", 3): "探查：室外温度近似常数",
    ("M2", 47): "探查：室外温度近似常数",
}

# 判定阈值（30 min 重采样）
MIN_COVERAGE = 0.30
FLAT_RUN_HOURS = 72.0          # 连续不变超过 3 天 → 冻结
OUT_RATIO = 0.02               # 越界比例
MAX_UNIQUE_TEMP = 30           # 温度类列分辨率过低
SPIKE_RATIO = 0.02


@dataclass
class ColHealth:
    col: str
    coverage: float
    n_unique: int
    std: float
    longest_flat_h: float
    out_of_range_ratio: float
    spike_ratio: float
    verdict: str = "ok"
    reasons: list = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.verdict in ("ok", "idle")


def _longest_flat_run(values: np.ndarray, dt_hours: float = 0.5) -> float:
    if len(values) == 0:
        return 0.0
    best = cur = 1
    prev = values[0]
    for v in values[1:]:
        if np.isnan(v) and np.isnan(prev):
            cur += 1
        elif v == prev:
            cur += 1
        else:
            best = max(best, cur)
            cur = 1
        prev = v
    best = max(best, cur)
    return best * dt_hours


def check_column(s: pd.Series, dt_hours: float = 0.5) -> ColHealth:
    """按测点类型分规则判定：设定值/状态量天然可以长期不变，流量/功率夏季可长期为 0。"""
    name = str(s.name)
    v = pd.to_numeric(s, errors="coerce")
    n = len(v)
    cov = float(v.notna().mean()) if n else 0.0
    vv = v.dropna()
    n_unique = int(vv.nunique())
    std = float(vv.std(ddof=0)) if len(vv) else 0.0
    flat_h = _longest_flat_run(v.to_numpy("float64"), dt_hours)

    is_setpoint = name.endswith("_setpoint")
    is_status = any(k in name for k in ("_mode", "status", "valve_position"))
    is_flowish = any(k in name for k in ("meter_flow", "meter_energy", "meter_volume", "heat_power"))
    is_outdoor = name == "outdoor_temperature"

    # 冻结阈值：室外温度 3 天（天气不可能 3 天不变）；其余温度 7 天
    flat_limit = FLAT_RUN_HOURS if is_outdoor else (168.0 if is_flowish or "temperature" in name else 168.0)

    lo, hi = BOUNDS.get(name, (None, None))
    if lo is not None and len(vv):
        out_ratio = float(((vv < lo) | (vv > hi)).mean())
    else:
        out_ratio = 0.0

    spike_ratio = 0.0
    if len(vv) > 100:
        d = np.abs(np.diff(vv.to_numpy("float64")))
        med = np.median(d)
        if med > 1e-9:
            # 同时要求绝对跳变足够大，避免稳态下微小噪声被误判
            thr_abs = 5.0 if "temperature" in name else max(0.5 * std, 1e-6)
            spike_ratio = float(((d > 20 * med) & (d > thr_abs)).mean())

    h = ColHealth(name, cov, n_unique, std, flat_h, out_ratio, spike_ratio)
    mean_val = float(np.nanmean(vv)) if len(vv) else np.nan

    if cov < MIN_COVERAGE:
        h.verdict, h.reasons = "missing", [f"覆盖率 {cov:.2f} < {MIN_COVERAGE}"]
    elif out_ratio > OUT_RATIO:
        h.verdict, h.reasons = "out_of_range", [f"{out_ratio:.1%} 数值超出 [{lo},{hi}]"]
    elif is_setpoint or is_status:
        # 设定值/状态量长期不变是正常控制行为，不做常值判定
        if spike_ratio > SPIKE_RATIO:
            h.verdict, h.reasons = "noisy", [f"{spike_ratio:.1%} 突跳"]
        return h
    elif is_flowish and flat_h > flat_limit and abs(np.nan_to_num(mean_val)) < 1e-6:
        h.verdict, h.reasons = "idle", ["长期为 0（季节停运/无负荷，非传感器故障）"]
    elif flat_h > flat_limit:
        kind = "constant" if n_unique <= 2 else "frozen"
        h.verdict, h.reasons = kind, [f"连续 {flat_h:.0f}h 数值不变（阈值 {flat_limit:.0f}h）"]
    elif "temperature" in name and n_unique < MAX_UNIQUE_TEMP and std > 1e-9:
        h.verdict, h.reasons = "coarse", [f"温度列仅 {n_unique} 个不同取值"]
    elif spike_ratio > SPIKE_RATIO:
        h.verdict, h.reasons = "noisy", [f"{spike_ratio:.1%} 相邻点突跳"]
    return h


def assess_frame(df: pd.DataFrame, cols: list[str] | None = None,
                 dt_hours: float = 0.5) -> dict[str, ColHealth]:
    """对一帧数据做逐列体检。"""
    cols = cols or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    return {c: check_column(df[c], dt_hours) for c in cols if c in df.columns}


# 建模时"严重到必须降级"的判定：
#   任何传感器的缺失/越界；室外温度额外包括冻结/常值/低分辨率（它同时决定自适应阈值）。
# 其余传感器的"冻结"多为夏季停运/稳态（实测约 33 个站的主网温度在夏季连续 29 天不变），
# 属于正常工况，不能当作故障剔除，否则会误删大量有效信号。
SEVERE_ALWAYS = {"missing", "out_of_range"}
SEVERE_OUTDOOR = {"missing", "out_of_range", "frozen", "constant", "coarse"}


def is_severe(col: str, h: ColHealth) -> bool:
    if h.verdict in SEVERE_ALWAYS:
        return True
    if col == "outdoor_temperature" and h.verdict in SEVERE_OUTDOOR:
        return True
    return False


def derive_drops(health: dict[str, ColHealth], feature_cols: list[str]) -> list[str]:
    """把"严重故障"的传感器及其派生特征加入剔除名单。"""
    drop = set()
    for col, h in health.items():
        if not is_severe(col, h):
            continue
        for feat in DEPENDENTS.get(col, [col]):
            if feat in feature_cols:
                drop.add(feat)
    return sorted(drop)


def outdoor_ok(health: dict[str, ColHealth]) -> bool:
    h = health.get("outdoor_temperature")
    return bool(h is not None and h.healthy)


def station_health(tag: str, sid: int, dt_hours: float = 0.5) -> dict[str, ColHealth]:
    from .data import load_substation
    df = load_substation(tag, sid)
    df = df.loc[df.index.min() + pd.Timedelta(days=30):]
    return assess_frame(df, dt_hours=dt_hours)
