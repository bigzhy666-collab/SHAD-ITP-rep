"""把实验结果画成图（中文标注，300dpi）。

用法:
  python scripts/make_figures.py --runs reports/baseline_default:基线AE reports/improved_phys:物理残差AE
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

from src.common import FIGURES, REPORTS           # noqa: E402
from src.protocol import event_metrics, metrics_with_lead  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 120
plt.rcParams["savefig.dpi"] = 300
plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.spines.right"] = False

C_BASE, C_OURS = "#7f8c9b", "#c0392b"


def load_run(path: Path) -> dict:
    with open(path / "results.pkl", "rb") as fh:
        return pickle.load(fh)


def run_metrics(results: list[dict]) -> dict:
    out = {}
    for m in ("M1", "M2", "ALL"):
        sub = results if m == "ALL" else [r for r in results if r["manufacturer"] == m]
        if not sub:
            continue
        paths = {r["key"]: (r["c_path"], r["kind"]) for r in sub}
        times = {r["key"]: r["times"] for r in sub}
        reps = {r["key"]: r["report_date"] for r in sub if r["kind"] == "fault"}
        # 复用与主脚本一致的标定逻辑
        from scripts.run_baseline import calibrate_c_thr
        thr, _ = calibrate_c_thr(sub)
        met = metrics_with_lead(paths, times, reps, thr)
        met["manufacturer"] = m
        met["n_events"] = len(sub)
        out[m] = met
    return out


def fig_metrics_compare(runs: dict[str, dict], path: Path):
    """指标对比条形图：A / F0.5 / 检出率 / 平均提前量。"""
    names = list(runs)
    metrics_of = {k: run_metrics(v["results"]) for k, v in runs.items()}
    specs = [("A", "正常行为准确率 A", 1.0), ("f0_5", "事件级 F0.5", 1.0),
             ("recall", "检出率（报修前）", 1.0), ("E", "提前量得分 Ē", 1.0)]
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.6))
    for ax, (key, label, ymax) in zip(axes, specs):
        vals = [metrics_of[n]["ALL"].get(key, np.nan) for n in names]
        bars = ax.bar(range(len(names)), vals, color=[C_BASE, C_OURS][:len(names)], width=0.6)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.3f}", ha="center", fontsize=9)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, fontsize=9)
        ax.set_ylim(0, ymax * 1.12)
        ax.set_title(label, fontsize=11)
        ax.axhline(0.6 if key == "recall" else (0.83 if key == "f0_5" else (0.98 if key == "A" else 0)),
                   ls="--", lw=0.8, color="#999999")
    axes[0].annotate("论文基线 0.98", xy=(0, 0.98), fontsize=7, color="#666666")
    axes[1].annotate("论文基线 0.83", xy=(0, 0.83), fontsize=7, color="#666666")
    axes[2].annotate("论文基线 0.60", xy=(0, 0.60), fontsize=7, color="#666666")
    fig.suptitle("PreDist 协议下的检测性能对比（虚线=原论文报告值）", fontsize=12)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_lead_distribution(runs: dict[str, dict], path: Path):
    """提前量分布 + 按故障类型检出情况。"""
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.2))
    for i, (name, run) in enumerate(runs.items()):
        leads, labels = [], []
        thr = run["c_thr"]
        for r in run["results"]:
            if r["kind"] != "fault" or len(r["c_path"]) == 0:
                continue
            if r["c_path"].max() < thr:
                continue
            idx = int(np.argmax(r["c_path"] >= thr))
            leads.append((r["report_date"] - r["times"][idx]).total_seconds() / 86400)
            labels.append(r["fault_label"])
        axes[0].hist(leads, bins=np.arange(0, 7.5, 0.5), alpha=0.65,
                     label=f"{name} (n={len(leads)}, 中位{np.median(leads):.2f}天)" if leads else name,
                     color=[C_BASE, C_OURS][min(i, 1)])
    axes[0].axvline(24 / 24, color="#999999", ls="--", lw=0.8)
    axes[0].set_xlabel("提前预警时长（天）")
    axes[0].set_ylabel("检出事件数")
    axes[0].set_title("提前预警时长分布")
    axes[0].legend(fontsize=8)

    # 右图：按故障类型的检出数（取最后一个 run）
    run = list(runs.values())[-1]
    thr = run["c_thr"]
    df = pd.DataFrame([{
        "fault_label": r["fault_label"], "detected": int(r["c_path"].max() >= thr) if len(r["c_path"]) else 0,
        "mp": r["monitoring_potential"],
    } for r in run["results"] if r["kind"] == "fault"])
    g = df.groupby("fault_label").agg(n=("detected", "size"), det=("detected", "sum")).sort_values("n")
    axes[1].barh(range(len(g)), g["n"], color="#dcdcdc", label="事件数")
    axes[1].barh(range(len(g)), g["det"], color=C_OURS, label="检出")
    axes[1].set_yticks(range(len(g)))
    axes[1].set_yticklabels([s[:28] for s in g.index], fontsize=7)
    axes[1].set_xlabel("事件数")
    axes[1].set_title(f"按故障类型的检出情况（{list(runs)[-1]}）")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_timeline(run: dict, path: Path, pick: str = "median"):
    """典型事件的分数/criticality 时间线：最有说服力的单图。"""
    thr = run["c_thr"]
    cands = []
    for r in run["results"]:
        if r["kind"] != "fault" or len(r["c_path"]) == 0:
            continue
        if r["c_path"].max() < thr:
            continue
        idx = int(np.argmax(r["c_path"] >= thr))
        lead = (r["report_date"] - r["times"][idx]).total_seconds() / 3600
        starts_normal = r["score"][0] <= r["t_ae"]
        cands.append((lead, starts_normal, r))
    if not cands:
        return
    # 优先选"从正常状态开始、提前 6h~5 天告警"的典型事件，最能说明问题
    good = [c for c in cands if c[1] and 6 <= c[0] <= 120]
    pool = good or cands
    pool.sort(key=lambda x: x[0])
    if pick == "earliest":
        lead_h, _, r = pool[-1]
    else:
        lead_h, _, r = pool[len(pool) // 2]
    t = r["times"]
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(t, r["score"], color="#34495e", lw=0.9, label="异常分数")
    ax.axhline(r["t_ae"], color="#e67e22", ls="--", lw=1, label=f"正常基线阈值 t_AE={r['t_ae']:.3f}")
    ax.set_ylabel("异常分数（重构误差）")
    ax.set_ylim(bottom=min(0.0, np.nanmin(r["score"])))
    ax2 = ax.twinx()
    c_disp = np.minimum(r["c_path"], 2 * thr)
    ax2.plot(t, c_disp, color=C_OURS, lw=1.2, alpha=0.85, label="criticality C")
    ax2.axhline(thr, color=C_OURS, ls=":", lw=1)
    ax2.set_ylabel(f"criticality C（截断显示）", color=C_OURS)
    ax2.set_ylim(0, 2 * thr + 0.5)
    rep = r["report_date"]
    ax.axvline(rep, color="#27ae60", lw=1.4)
    ax.annotate("客户报修", xy=(rep, ax.get_ylim()[1] * 0.92), fontsize=9, color="#27ae60", ha="right")
    det_t = t[int(np.argmax(r["c_path"] >= thr))]
    ax.axvline(det_t, color=C_OURS, ls="--", lw=1.2)
    ax.annotate(f"首次告警\n提前 {lead_h/24:.1f} 天", xy=(det_t, ax.get_ylim()[1] * 0.55),
                fontsize=9, color=C_OURS, ha="right")
    ax.set_title(f"典型事件：{r['manufacturer']} 站 {r['sid']} · {r['fault_label']}")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_thr_curve(runs: dict[str, dict], path: Path):
    """F0.5 随 C_thr 变化曲线。"""
    fig, ax = plt.subplots(figsize=(7, 4))
    grid = np.arange(1, 61)
    for i, (name, run) in enumerate(runs.items()):
        paths = {r["key"]: (r["c_path"], r["kind"]) for r in run["results"]}
        f = [event_metrics(paths, int(t))["f0_5"] for t in grid]
        ax.plot(grid, f, color=[C_BASE, C_OURS][min(i, 1)], lw=1.6, label=name)
        best = int(grid[int(np.argmax(f))])
        ax.plot([best], [max(f)], "o", color=[C_BASE, C_OURS][min(i, 1)])
    ax.set_xlabel("criticality 阈值 C_thr")
    ax.set_ylabel("事件级 F0.5")
    ax.set_title("F0.5 随持续性阈值的变化")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="目录:标签")
    ap.add_argument("--out-prefix", default="fig")
    args = ap.parse_args()

    runs = {}
    for spec in args.runs:
        d, _, lab = spec.partition(":")
        p = Path(d)
        if not p.is_absolute():
            p = ROOT / p
        if not (p / "results.pkl").exists():
            print(f"跳过（无结果）: {p}")
            continue
        run = load_run(p)
        if "c_thr" not in run or run.get("c_thr") is None:
            from scripts.run_baseline import calibrate_c_thr
            run["c_thr"], _ = calibrate_c_thr(run["results"])
        runs[lab or p.name] = run
    if not runs:
        print("没有可用结果")
        return

    FIGURES.mkdir(parents=True, exist_ok=True)
    fig_metrics_compare(runs, FIGURES / f"{args.out_prefix}_metrics.png")
    fig_lead_distribution(runs, FIGURES / f"{args.out_prefix}_leadtime.png")
    fig_thr_curve(runs, FIGURES / f"{args.out_prefix}_f05_curve.png")
    fig_timeline(list(runs.values())[-1], FIGURES / f"{args.out_prefix}_timeline.png")
    print("图已输出到", FIGURES)

    # 同时导出指标对比 CSV
    rows = []
    for name, run in runs.items():
        for m, met in run_metrics(run["results"]).items():
            met["run"] = name
            rows.append(met)
    pd.DataFrame(rows).to_csv(REPORTS / f"{args.out_prefix}_compare.csv",
                              index=False, encoding="utf-8-sig")
    print("指标对比已写入", REPORTS / f"{args.out_prefix}_compare.csv")


if __name__ == "__main__":
    main()
