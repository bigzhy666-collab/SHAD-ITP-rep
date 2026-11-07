# 智慧供热 · 换热站状态预测模型（PreDist 数据集）

本目录是「智慧供热管道检测与辅助平台」项目的模型部分（不含平台、前端、接口），用换热站运行数据建立"正常行为模型"，在客户报修前发现设备或控制异常，输出异常分数、告警时刻与提前预警时长。

> 数据对象需要说明：PreDist 是换热站（站内设备与控制）数据，不是埋地管道本体数据。管道本体检测（腐蚀、泄漏定位、结构）需要声发射、负压波、分布式光纤，属于另一条技术线。

## 结果速览

| 模型 | 正常行为准确率 A | 事件级 F0.5 | 检出率（报修前） | 平均提前 |
|---|---|---|---|---|
| 论文报告（Energy 2026 摘要） | 0.98 | 0.83 | 60% | 3.9 天 |
| 本文基线（协议复现） | 0.995 | 0.753 | 44.0% | 3.80 天 |
| 本文最终模型（无监督，推荐部署） | 0.990 | 0.780 | 58.0% | 3.75 天 |
| 监督窗口模型（跨站，需历史工单） | 0.995 | 0.833 | 58.0% | 4.73 天 |

最终模型按厂商选配置：M1 用"紧凑物理特征 + 循环时间 + 工况自适应阈值"（F0.5 0.833、检出 0.654），M2 用"紧凑物理特征 + 循环时间 + 全局阈值"（F0.5 0.714、检出 0.500）。

跨站预训练加微调做过对照，结果为负（F0.5 0.661–0.753，低于不迁移的 0.769），说明这批数据下每站自学习更合适，详见[研发报告](docs/模型研发报告.md)第七节。

评估协议对齐原论文：每事件独立训练、7 天测试窗（终点为报修时刻）、99% 分位阈值、criticality 持续性判据、事件级 F0.5 / 检出率 / Earliness；共 115 个事件（故障 50、正常 65）。

## 目录结构

```
工作站/
├── src/                     # 核心代码
│   ├── common.py            # 路径、字段定义、单位换算
│   ├── data.py              # 数据加载（两家厂商统一字段/单位/重采样 + 缓存）
│   ├── features.py          # 物理残差特征、窗口统计、紧凑特征集 PHYS_COLS
│   ├── protocol.py          # 论文评估协议：事件筛选/训练窗/测试窗/criticality/指标
│   ├── models.py            # AE / PCA / IsolationForest 正常行为模型
│   ├── quality.py           # 传感器体检（缺失/冻结/越界/低分辨率/尖峰）+ 特征与阈值降级
│   ├── pretrain.py          # 跨站预训练（负结果实验，保留以便复现）
│   └── inference.py         # 【模型产物】训练/保存/加载/打分 + 国内字段映射
├── scripts/
│   ├── run_baseline.py      # 论文协议实验（--features raw|phys|phys2、--adapt-thr、--sensor-quality）
│   ├── run_supervised.py    # 跨站窗口级监督模型（二分类 + 故障类型）
│   ├── run_quality.py       # 传感器体检报告（93 站逐测点健康度 + 外部验证）
│   ├── run_pretrain.py      # 跨站预训练实验（负结果，保留复现）
│   ├── compare_runs.py      # 多方案横向对比（全量 / 短训练窗子集）
│   ├── make_figures.py      # 结果图表（指标对比/提前量/时间线/F0.5 曲线）
│   ├── train_station_model.py  # 训练单站模型并保存 .pkl
│   └── score_station.py     # 用模型给新数据打分，输出告警段
├── models/                  # 训练好的模型产物（.pkl）
├── reports/                 # 实验结果（各配置目录 + figures/）
├── docs/
│   ├── 模型研发报告.md        # 完整技术报告（结论/协议/消融/局限/复现）
│   ├── 模型卡.md             # 输入输出、使用方法、风险与落地
│   ├── 文献/基线方法与评估协议.md
│   └── 数据/国内数据源调研.md
├── 勘探/                    # 数据清点与质量报告（93 站可用性）
└── 数据缓存/                # 站点级 pickle 缓存（自动生成，可删）
```

## 快速开始

```bash
PY=python   # 需要 numpy / pandas / scikit-learn / matplotlib

# 1) 复现论文协议基线（约 6-8 分钟，115 个事件）
$PY scripts/run_baseline.py --variant default --out baseline_default

# 2) 跑本文模型（紧凑物理特征 + 循环时间特征）
$PY scripts/run_baseline.py --variant cyclic --features phys2 --out final_phys2

# 3) 监督模型（约 2-3 分钟）
$PY scripts/run_supervised.py

# 4) 出图
$PY scripts/make_figures.py --runs reports/baseline_default:基线AE reports/final_phys2:本文模型

# 5) 训练一个站的模型并用它打分
$PY scripts/train_station_model.py --mfr M1 --sid 7 --start 2015-04-12 --end 2017-11-12 --out models/M1_s7.pkl
$PY scripts/score_station.py --model models/M1_s7.pkl --mfr M1 --sid 7 --start 2017-11-18 --end 2017-11-27
```

## 环境注意事项

- 依赖 Python 3.10 以上和 `numpy`、`pandas`、`scikit-learn`、`matplotlib`，不需要 TensorFlow。
- `run_supervised.py` 在导入 sklearn 之前把线程数固定为 1，既保证结果可复现，也避免某些环境下多线程后端与进程/管道限制冲突；机器资源充足时可以去掉这段再跑。
- 所有脚本都关闭了 sklearn 的收敛警告。它只表示"未完全收敛"，不影响结果，但会让命令的退出码变成非零，看起来像失败，判断是否出错要看有没有 Traceback。

## 数据说明

- 原始数据：`数据/`（由环境变量 `PREDIST_DATA` 指定，只读，未修改）
- 结构：`manufacturer 1|2/operational_data/substation_<id>.csv` + `faults.csv` / `normal_events.csv` / `disturbances.csv` / `feature_descriptions.csv` / `configuration_types.csv`
- 实际 93 站 = M1 35 + M2 58；2012-03-28 ~ 2020-07-28；中位采样 10 分钟；约 1193 万行
- 加载后缓存到 `数据缓存/`，二次读取 < 0.5 s

## 下一步（未完成项）

1. 故障类型分层与可解释归因（当前 18 类准确率 0.142，仅可作参考）；
2. 国内数据接入与迁移验证（公开数据源清单见[国内数据源调研](docs/数据/国内数据源调研.md)）；
3. 传感器体检已落地（`src/quality.py` + `scripts/run_quality.py`，已知坏传感器命中 6/6、13 个站需降级）；下一步做坏传感器的代理特征替换（如室外温度坏时用回水温度或设定值推等价工况），而不是简单剔除；
4. 跨站预训练已完成并验证为负结果，不再作为改进方向。
