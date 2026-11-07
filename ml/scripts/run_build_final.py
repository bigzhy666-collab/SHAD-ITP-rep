"""组合最终模型：M1 用工况自适应配置、M2 用全局阈值配置，合并成最终结果并重算指标。

报告中「最终模型」（F0.5 0.780 / 检出率 58% / 平均提前 3.75 天）就是把两组实验按厂商
合在一起得到的结果。这个脚本让该结果可复现，而不是依赖人工拼接。

用法:
  python scripts/run_baseline.py --variant cyclic --features phys2 --adapt-thr --out final_v3_gated
  python scripts/run_baseline.py --variant cyclic --features phys2 --out final_phys2
  python scripts/run_build_final.py
"""
from __future__ import annotations

import argparse
import pickle
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import REPORTS                    # noqa: E402
from scripts.run_baseline import calibrate_c_thr  # noqa: E402
from src.protocol import metrics_with_lead        # noqa: E402

# 每个厂商取哪个实验的结果
CONFIG = {"M1": "final_v3_gated", "M2": "final_phys2"}


def load_results(run: str) -> list[dict]:
    path = REPORTS / run / "results.pkl"
    if not path.exists():
        raise SystemExit(f"缺少实验结果: {path}（先跑对应的 run_baseline.py）")
    with open(path, "rb") as fh:
        return pickle.load(fh)["results"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="final_best")
    args = ap.parse_args()

    results = []
    for mfr, run in CONFIG.items():
        sub = [r for r in load_results(run) if r["manufacturer"] == mfr]
        if not sub:
            raise SystemExit(f"{run} 中没有 {mfr} 的结果")
        results.extend(sub)
        print(f"  {mfr}: 取自 {run}，{len(sub)} 个事件")

    out_dir = REPORTS / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results.pkl", "wb") as fh:
        pickle.dump({"results": results,
                     "variant": "M1: 紧凑物理+循环+工况自适应 | M2: 紧凑物理+循环+全局阈值",
                     "skipped": [], "config": CONFIG}, fh)

    rows = []
    for m in ("M1", "M2", "ALL"):
        sub = results if m == "ALL" else [r for r in results if r["manufacturer"] == m]
        if not sub:
            continue
        paths = {r["key"]: (r["c_path"], r["kind"]) for r in sub}
        times = {r["key"]: r["times"] for r in sub}
        reps = {r["key"]: r["report_date"] for r in sub if r["kind"] == "fault"}
        thr, _ = calibrate_c_thr(sub)
        met = metrics_with_lead(paths, times, reps, thr)
        met.update({"manufacturer": m, "n_events": len(sub)})
        rows.append(met)

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "metrics_summary.csv", index=False, encoding="utf-8-sig")
    cols = ["manufacturer", "n_events", "c_thr", "A", "f0_5", "recall", "FAR_event",
            "E", "lead_days_mean"]
    print("\n组合结果：")
    print(df[[c for c in cols if c in df.columns]].to_string(
        index=False, float_format=lambda x: f"{x:.3f}"))
    print(f"\n输出: {out_dir}")


if __name__ == "__main__":
    main()
