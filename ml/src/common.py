"""项目公共配置：路径、字段定义、单位换算、厂商差异。

PreDist 数据集关键事实（来自 README + 数据探查）：
  - 两家厂商 M1 / M2，93 个换热站，10 分钟采样，CSV 分隔符为 ';'
  - M1 有 35 站、M2 有 58 站（论文写 61，数据包缺 22/30/32 号站）
  - M2 存在重名列（outdoor_temperature 出现两次）、含空格列名（s_hc1.2_dhw_control unit_mode）、
    且单位与 M1 不同（W / Wh / ml/h / ml），必须在加载时统一
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 路径
ROOT = Path(__file__).resolve().parents[1]          # 工作站/


def _default_data_dir() -> Path:
    """原始数据目录：优先环境变量，其次 项目根/数据、项目根的上级/数据。"""
    env = os.environ.get("PREDIST_DATA")
    if env:
        return Path(env)
    for cand in (ROOT / "数据", ROOT.parent / "数据"):
        if (cand / "manufacturer 1").is_dir():
            return cand
    return ROOT / "数据"


DATA = _default_data_dir()
CACHE = ROOT / "数据缓存"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"

for _p in (CACHE, REPORTS, FIGURES):
    _p.mkdir(parents=True, exist_ok=True)

MFR_DIRS = ["manufacturer 1", "manufacturer 2"]
MFR_TAGS = ["M1", "M2"]

# ---------------------------------------------------------------- 时间
RESAMPLE = "30min"        # 统一重采样到 30 分钟，兼顾内存与预警时效
MIN_TRAIN_DAYS = 21       # 训练窗口短于此的站点/事件不参与无监督建模
GRACE_HOURS = 6           # 事件边界外扩，避免标注抖动

# ---------------------------------------------------------------- 单位统一
# 统一到: 功率 kW, 电量 kWh, 流量 l/h, 体积 m3
UNIT_SCALE = {
    "M1": {  # 原始已是 kW / kWh / l/h / m3
        "p_net_meter_heat_power": 1.0,
        "p_net_meter_energy": 1.0,
        "p_net_meter_flow": 1.0,
        "p_net_meter_volume": 1.0,
    },
    "M2": {  # 原始 W / Wh / ml/h / ml
        "p_net_meter_heat_power": 1e-3,
        "p_net_meter_energy": 1e-3,
        "p_net_meter_flow": 1e-3,
        "p_net_meter_volume": 1e-6,
    },
}

# ---------------------------------------------------------------- 核心特征集
# 跨站通用的核心量（绝大多数站点具备），跨站迁移模型只用这一组 + 工程特征
CORE_RAW = [
    "outdoor_temperature",
    "p_net_supply_temperature",
    "p_net_return_temperature",
    "p_net_meter_heat_power",
    "p_net_meter_flow",
    "p_hc1_return_temperature",
    "s_hc1_supply_temperature",
    "s_hc1_supply_temperature_setpoint",
]

# 扩展量：具备则用，缺失记为 NaN（LightGBM 原生支持缺失）
EXTRA_RAW = [
    "p_hc1_return_temperature_setpoint",
    "s_dhw_supply_temperature",
    "s_dhw_supply_temperature_setpoint",
    "s_dhw_upper_storage_temperature",
    "s_dhw_lower_storage_temperature",
    "s_dhw_upper_storage_temperature_setpoint",
    "p_dhw_return_temperature",
    "p_dhw_return_temperature_setpoint",
    "p_net_meter_energy",
    "p_net_meter_volume",
    "p_dhw_control_valve_position",
    "p_hc1_control_valve_position_setpoint",
    "s_hc1.1_supply_temperature",
    "s_hc1.2_supply_temperature",
    "s_hc1.1_return_temperature",
    "s_hc1.2_return_temperature",
    "s_hc1.1_supply_temperature_setpoint",
    "s_hc1.2_supply_temperature_setpoint",
    "s_hc1_control_unit_mode",
    "s_dhw_control_unit_mode",
    "s_hc1_heating_pump_status_setpoint",
    "s_dhw_3_way_valve_status",
]

ALL_RAW = CORE_RAW + EXTRA_RAW

# 工程特征（在 features.py 中生成，这里给出供窗口聚合的特征清单）
ENGINEERED = [
    "dt_primary",          # 一次侧供回温差
    "dt_hc1",              # 二次侧供回温差
    "err_supply",          # 二次侧供水温度 - 设定值
    "err_return",          # 一次侧回水温度 - 设定值
    "err_dhw",             # 生活热水供水温度 - 设定值
    "err_storage_upper",   # 储水箱上部温度 - 设定值
    "storage_delta",       # 储水箱上下部温差
    "curve_residual",      # 偏离供暖曲线（供温 - 由室外温度分箱中位数预测值）
    "power_per_dt",        # 热功率 / 一次侧温差（流量健康度代理）
    "flow_norm",           # 归一化流量
    "load_index",          # 归一化热负荷（功率 / 室外温差）
    "stuck_score",         # 传感器冻结程度（24h 滚动标准差）
    "miss_rate",           # 6h 窗口缺失率
    "outdoor_temperature",
    "hour_sin", "hour_cos", "dow", "month",
    "is_night", "is_heating_season",
]

WINDOW_STATS = ["mean", "std", "min", "max", "p10", "p90", "abs_mean", "slope"]
