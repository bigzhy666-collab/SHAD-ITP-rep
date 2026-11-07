# 传感器体检报告

对 61 个站、1599 个站-测点组合做健康度判定；判定规则：缺失/常值/冻结/越界/分辨率/尖峰。

## 1. 判定结果分布

| verdict | 站-测点组合数 |
|---|---|
| ok | 1028 |
| frozen | 245 |
| missing | 183 |
| noisy | 139 |
| coarse | 4 |

## 2. 室外温度（影响自适应阈值）外部验证

- 人工标注的已知坏传感器（README + 本地探查）：6 个
- 检出命中：6 个 → [('M1', 19), ('M2', 3), ('M2', 18), ('M2', 41), ('M2', 47), ('M2', 61)]
- 漏报：0 个 → []
- 体检新发现（未被人工记录）：7 个 → [('M1', 5), ('M1', 31), ('M2', 7), ('M2', 17), ('M2', 21), ('M2', 28), ('M2', 45)]
- precision = 0.46，recall = 1.00

## 3. 关键传感器存在问题的站（影响建模）

| manufacturer | sid | column |
|---|---|---|
| M1 | 5 | outdoor_temperature |
| M1 | 19 | outdoor_temperature |
| M1 | 31 | outdoor_temperature |
| M2 | 3 | outdoor_temperature |
| M2 | 7 | outdoor_temperature |
| M2 | 17 | outdoor_temperature |
| M2 | 18 | outdoor_temperature |
| M2 | 21 | outdoor_temperature |
| M2 | 28 | outdoor_temperature |
| M2 | 41 | outdoor_temperature |
| M2 | 45 | outdoor_temperature |
| M2 | 47 | outdoor_temperature |
| M2 | 61 | outdoor_temperature |

## 4. 判定标准

| 判定 | 规则 |
|---|---|
| missing | 覆盖率 < 30% |
| constant | 不同取值 ≤ 2 且连续不变 > 72h |
| frozen | 连续 > 72h 数值完全不变 |
| out_of_range | > 2% 数值超出物理区间 |
| coarse | 温度列不同取值 < 30 个 |
| noisy | > 2% 相邻点突跳超过 20 倍中位差 |

## 5. 对建模的影响

见 `src/quality.py::DEPENDENTS`：坏传感器会连带剔除其派生特征
（例如室外温度坏 → 同时剔除 curve_residual / load_index / is_heating_season / miss_rate），
并且室外温度不健康时强制关闭工况自适应阈值。