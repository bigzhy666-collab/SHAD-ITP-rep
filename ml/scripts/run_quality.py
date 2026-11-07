"""传感器体检报告：对 93 个站的每个测点做健康度判定，并用人工标注的已知坏传感器做外部验证。

用法:
  python scripts/run_quality.py                # 全量体检（约 1-2 分钟）
  python scripts/run_quality.py --mfr M2
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import REPORTS                        # noqa: E402
from src.data import MFR_TAGS, substation_ids          # noqa: E402
from src.quality import KNOWN_BAD_OUTDOOR, is_severe, station_health  # noqa: E402

# 重点关注的传感器（影响特征与阈值）
KEY_SENSORS = [
    "outdoor_temperature",
    "p_net_supply_temperature",
    "p_net_return_temperature",
    "p_net_meter_heat_power",
    "p_net_meter_flow",
    "s_hc1_supply_temperature",
    "s_hc1_supply_temperature_setpoint",
    "p_hc1_return_temperature",
]


def md_table(df: pd.DataFrame) -> str:
    """不依赖 tabulate 的 markdown 表格。"""
    if df is None or len(df) == 0:
        return "（无）"
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mfr", default="all", choices=["all", "M1", "M2"])
    args = ap.parse_args()

    out_dir = REPORTS / "quality"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    tags = MFR_TAGS if args.mfr == "all" else [args.mfr]
    total = sum(len(substation_ids(t)) for t in tags)
    done = 0
    for tag in tags:
        for sid in substation_ids(tag):
            try:
                health = station_health(tag, sid)
            except Exception as exc:
                print(f"  {tag} s{sid} 体检失败: {exc}")
                continue
            for col, h in health.items():
                rows.append({
                    "manufacturer": tag, "sid": sid, "column": col,
                    "coverage": round(h.coverage, 4), "n_unique": h.n_unique,
                    "std": round(h.std, 4), "longest_flat_h": round(h.longest_flat_h, 1),
                    "out_of_range_ratio": round(h.out_of_range_ratio, 4),
                    "spike_ratio": round(h.spike_ratio, 4),
                    "verdict": h.verdict, "reasons": "; ".join(h.reasons),
                    "is_key_sensor": col in KEY_SENSORS,
                    "severe": is_severe(col, h),
                })
            done += 1
            if done % 20 == 0:
                print(f"  已体检 {done}/{total} 站", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "sensor_health.csv", index=False, encoding="utf-8-sig")
    n_station = df.groupby(["manufacturer", "sid"]).ngroups
    print(f"\n体检完成: {n_station} 站 / {len(df)} 个站-测点组合")
    print(df["verdict"].value_counts().to_string())

    # ---------------- 外部验证：室外温度 ----------------
    out = df[df.column == "outdoor_temperature"][["manufacturer", "sid", "verdict", "reasons"]]
    flagged = {(r.manufacturer, int(r.sid)) for r in out.itertuples() if r.verdict != "ok"}
    flagged_all = {(r.manufacturer, int(r.sid)) for r in out.itertuples()}
    truth = set(KNOWN_BAD_OUTDOOR)

    tp = sorted(flagged & truth)
    fp = sorted(flagged - truth)
    fn = sorted(truth - flagged)
    tn = len(flagged_all - truth - flagged)

    print("\n===== 室外温度体检 vs 人工标注的已知坏传感器 =====")
    print(f"  命中 (TP) {len(tp)}: {tp}")
    print(f"  漏报 (FN) {len(fn)}: {fn}")
    print(f"  新发现 (未被 README/探查记录) {len(fp)}: {fp}")
    precision = len(tp) / (len(tp) + len(fp)) if tp or fp else float("nan")
    recall = len(tp) / len(truth) if truth else float("nan")
    print(f"  precision={precision:.2f}  recall={recall:.2f}  (阴性 {tn} 个站)")

    # ---------------- 关键传感器坏站清单 ----------------
    key_bad = (df[(df.is_key_sensor) & (df.severe)]
               .groupby(["manufacturer", "sid"])["column"]
               .apply(lambda s: ", ".join(sorted(s))).reset_index())
    key_bad.to_csv(out_dir / "stations_with_bad_key_sensors.csv", index=False, encoding="utf-8-sig")
    print(f"\n关键传感器存在严重问题的站: {len(key_bad)} 个（明细见 stations_with_bad_key_sensors.csv）")

    # ---------------- 写报告 ----------------
    md = ["# 传感器体检报告", "",
          f"对 {df.sid.nunique()} 个站、{len(df)} 个站-测点组合做健康度判定；"
          f"判定规则：缺失/常值/冻结/越界/分辨率/尖峰。", "",
          "## 1. 判定结果分布", "",
          md_table(df["verdict"].value_counts().rename_axis("verdict").to_frame("站-测点组合数").reset_index()), "",
          "## 2. 室外温度（影响自适应阈值）外部验证", "",
          f"- 人工标注的已知坏传感器（README + 本地探查）：{len(truth)} 个",
          f"- 检出命中：{len(tp)} 个 → {tp}",
          f"- 漏报：{len(fn)} 个 → {fn}",
          f"- 体检新发现（未被人工记录）：{len(fp)} 个 → {fp}",
          f"- precision = {precision:.2f}，recall = {recall:.2f}", "",
          "## 3. 关键传感器存在问题的站（影响建模）", "",
          md_table(key_bad), "",
          "## 4. 判定标准", "",
          "| 判定 | 规则 |", "|---|---|",
          "| missing | 覆盖率 < 30% |",
          "| constant | 不同取值 ≤ 2 且连续不变 > 72h |",
          "| frozen | 连续 > 72h 数值完全不变 |",
          "| out_of_range | > 2% 数值超出物理区间 |",
          "| coarse | 温度列不同取值 < 30 个 |",
          "| noisy | > 2% 相邻点突跳超过 20 倍中位差 |", "",
          "## 5. 对建模的影响", "",
          "见 `src/quality.py::DEPENDENTS`：坏传感器会连带剔除其派生特征",
          "（例如室外温度坏 → 同时剔除 curve_residual / load_index / is_heating_season / miss_rate），",
          "并且室外温度不健康时强制关闭工况自适应阈值。"]
    (out_dir / "sensor_health_summary.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n输出目录: {out_dir}")


if __name__ == "__main__":
    main()


