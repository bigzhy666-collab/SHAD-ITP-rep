"""横向对比多组实验结果（含"短训练窗子集"专项对比）并出图。

用法:
  python scripts/compare_runs.py --runs reports/baseline_default:论文基线 \
      reports/final_phys2:紧凑物理特征 reports/pretrain_ft:跨站预训练+微调
"""
from __future__ import annotations

import argparse
import pickle
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import FIGURES, REPORTS                     # noqa: E402
from src.protocol import metrics_with_lead, select_events   # noqa: E402
from scripts.run_baseline import calibrate_c_thr            # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["savefig.dpi"] = 300
plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.spines.right"] = False

COLORS = ["#7f8c9b", "#c0392b", "#2c7fb8", "#e67e22"]
SHORT_DAYS = 180


def load_run(path: Path) -> list[dict]:
    with open(path / "results.pkl", "rb") as fh:
        return pickle.load(fh)["results"]


def train_days_map() -> dict[str, int]:
    ev = select_events()
    out = {}
    for _, r in ev.iterrows():
        key = f"{r['manufacturer']}_E{int(r['event_id'])}_S{int(r['sid'])}_{r['kind']}"
        try:
            out[key] = int((pd.Timestamp(r["train_end"]) - pd.Timestamp(r["train_start"])).days)
        except Exception:
            out[key] = 9999
    return out


def eval_subset(results: list[dict], keys: set[str] | None = None) -> dict | None:
    sub = results if keys is None else [r for r in results if r["key"] in keys]
    if not sub or not any(r["kind"] == "fault" for r in sub):
        return None
    paths = {r["key"]: (r["c_path"], r["kind"]) for r in sub}
    times = {r["key"]: r["times"] for r in sub}
    reps = {r["key"]: r["report_date"] for r in sub if r["kind"] == "fault"}
    thr, _ = calibrate_c_thr(sub)
    met = metrics_with_lead(paths, times, reps, thr)
    met["n_events"] = len(sub)
    met["n_fault"] = sum(1 for r in sub if r["kind"] == "fault")
    return met


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="compare_all.csv")
    args = ap.parse_args()

    td = train_days_map()
    runs = {}
    for spec in args.runs:
        d, _, lab = spec.partition(":")
        p = Path(d) if Path(d).is_absolute() else ROOT / d
        if not (p / "results.pkl").exists():
            print(f"跳过（无结果）: {p}")
            continue
        runs[lab or p.name] = load_run(p)

    rows = []
    for name, results in runs.items():
        for scope in ("全部事件", f"短训练窗(<{SHORT_DAYS}天)"):
            if scope == "全部事件":
                keys = None
            else:
                keys = {r["key"] for r in results if td.get(r["key"], 9999) < SHORT_DAYS}
            met = eval_subset(results, keys)
            if met is None:
                continue
            met.update({"run": name, "scope": scope})
            rows.append(met)

    df = pd.DataFrame(rows)
    cols = ["run", "scope", "n_events", "n_fault", "c_thr", "A", "f0_5", "recall",
            "FAR_event", "E", "lead_days_mean", "n_detected"]
    df = df[[c for c in cols if c in df.columns]]
    df.to_csv(REPORTS / args.out, index=False, encoding="utf-8-sig")
    print(df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    # ---- 出图：两个子集上的 检出率 / F0.5 对比
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, metric, title in zip(axes, ("recall", "f0_5"),
                                 ("检出率（报修前）", "事件级 F0.5")):
        scopes = ["全部事件", f"短训练窗(<{SHORT_DAYS}天)"]
        width = 0.8 / max(1, len(runs))
        for i, name in enumerate(runs):
            vals = []
            for s in scopes:
                row = df[(df.run == name) & (df.scope == s)]
                vals.append(float(row[metric].iloc[0]) if len(row) else np.nan)
            xs = np.arange(len(scopes)) + (i - (len(runs) - 1) / 2) * width
            bars = ax.bar(xs, vals, width=width, label=name, color=COLORS[i % len(COLORS)])
            for b, v in zip(bars, vals):
                if np.isfinite(v):
                    ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.3f}",
                            ha="center", fontsize=7)
        ax.set_xticks(range(len(scopes)))
        ax.set_xticklabels(scopes, fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.set_title(title)
    axes[0].legend(fontsize=8)
    fig.suptitle("全量 vs 短训练窗子集：跨站预训练的目标收益", fontsize=12)
    fig.tight_layout()
    out_png = FIGURES / "pretrain_compare.png"
    fig.savefig(out_png)
    plt.close(fig)
    print("图已输出:", out_png)


if __name__ == "__main__":
    main()
