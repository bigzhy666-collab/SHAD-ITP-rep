"""实验：跨站预训练 + 本站微调，与基线/紧凑物理特征模型对比。

评估协议与 run_baseline 完全一致（每事件 7 天测试窗、99% 分位阈值、criticality、F0.5/检出率/提前量）；
差异只在"模型初始化"：从其他站预训练的 AE 权重出发，再用本站训练窗微调。

用法:
  python scripts/run_pretrain.py --limit 4      # 冒烟
  python scripts/run_pretrain.py                # 全量（约 20-30 分钟）
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import REPORTS                                 # noqa: E402
from src.data import load_disturbances, load_substation         # noqa: E402
from src.features import build_features, fit_reference          # noqa: E402
from src.pretrain import (build_corpus, finetune, fit_scaler, pretrain, transform)  # noqa: E402
from src.protocol import (                                      # noqa: E402
    Event, build_test_frame, build_train_frame, criticality_from_mask,
    event_metrics, maintenance_mask, metrics_with_lead, select_events,
)
from scripts.run_baseline import calibrate_c_thr, DEFAULT_SCORE  # noqa: E402

QUANTILE = 0.99
MAX_ITER_PRETRAIN = 40
TOTAL_CAP = 40000


def make_event(row) -> Event:
    return Event(
        manufacturer=row["manufacturer"], event_id=int(row["event_id"]), sid=int(row["sid"]),
        kind=row["kind"], report_date=row["report_date"] if pd.notna(row["report_date"]) else None,
        test_start=row["test_start"], test_end=row["test_end"],
        train_start=row["train_start"], train_end=row["train_end"],
        anomaly_start=row["anomaly_start"] if pd.notna(row["anomaly_start"]) else None,
        anomaly_end=row["anomaly_end"] if pd.notna(row["anomaly_end"]) else None,
        fault_label=row["fault_label"], monitoring_potential=row["monitoring_potential"],
        config_type=row["config_type"] if isinstance(row["config_type"], str) else "",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mfr", default="all", choices=["all", "M1", "M2"])
    ap.add_argument("--ft-iters", type=int, default=30)
    ap.add_argument("--ft-lr", type=float, default=1.2e-4)
    ap.add_argument("--out", default="pretrain_ft")
    args = ap.parse_args()

    out_dir = REPORTS / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("构建跨站语料库 ...")
    pools = build_corpus()
    dists = {m: load_disturbances(m) for m in ("M1", "M2")}
    events = select_events()
    mfrs = ["M1", "M2"] if args.mfr == "all" else [args.mfr]
    todo = events[events.manufacturer.isin(mfrs)].reset_index(drop=True)
    if args.limit:
        todo = todo.groupby(["manufacturer", "kind"], group_keys=False).head(args.limit)
    print(f"待评估事件: {len(todo)}")

    station_cache: dict = {}      # (tag,sid) -> dict(feats, ref, pretrained)
    results, skipped = [], []

    for i, row in todo.iterrows():
        ev = make_event(row)
        key = (ev.manufacturer, ev.sid)
        try:
            df = load_substation(ev.manufacturer, ev.sid)
            tr_raw = build_train_frame(df, ev, dists[ev.manufacturer])
            te_raw = build_test_frame(df, ev)
            if len(tr_raw) < 200 or len(te_raw) < 10:
                skipped.append({"key": ev.key, "reason": f"数据不足 {len(tr_raw)}/{len(te_raw)}"})
                continue

            if key not in station_cache:
                ref = fit_reference(tr_raw)
                feats = build_features(df, reference=ref, mode="phys2", cyclic=True)
                target_sc = fit_scaler(feats.loc[tr_raw.index])
                ae_base = pretrain(ev.manufacturer, ev.sid, pools,
                                   max_iter=MAX_ITER_PRETRAIN, seed=0)
                station_cache[key] = {"feats": feats, "ae": ae_base, "scaler": target_sc}
            cache = station_cache[key]
            feats = cache["feats"]

            Xtr = transform(feats.loc[tr_raw.index], cache["scaler"])
            Xte = transform(feats.loc[te_raw.index], cache["scaler"])

            ae = finetune(cache["ae"], Xtr, iters=args.ft_iters, lr=args.ft_lr)
            kind = DEFAULT_SCORE[ev.manufacturer]
            s_tr = ae.score(Xtr, kind)
            s_te = ae.score(Xte, kind)
            t_ae = float(np.quantile(s_tr, QUANTILE))

            mmask = maintenance_mask(te_raw.index, ev.sid, dists[ev.manufacturer])
            cpath = criticality_from_mask(s_te > t_ae, mmask)

            results.append({
                "key": ev.key, "manufacturer": ev.manufacturer, "event_id": ev.event_id,
                "sid": ev.sid, "kind": ev.kind, "fault_label": ev.fault_label,
                "monitoring_potential": ev.monitoring_potential, "config_type": ev.config_type,
                "c_max": int(cpath.max()), "n_points": int(len(cpath)),
                "n_train": int(len(tr_raw)), "t_ae": t_ae, "score_kind": kind,
                "times": te_raw.index, "c_path": cpath, "score": s_te,
                "report_date": ev.report_date,
                "train_days": int((ev.train_end - ev.train_start).days),
            })
        except Exception as exc:
            skipped.append({"key": ev.key, "reason": f"{type(exc).__name__}: {exc}"})

        if (i + 1) % 5 == 0 or i == len(todo) - 1:
            print(f"  [{i+1}/{len(todo)}] 完成 {len(results)} 跳过 {len(skipped)} "
                  f"已用 {(time.time()-t0)/60:.1f} min", flush=True)

    if not results:
        print("没有成功事件；跳过原因：")
        for s in skipped[:8]:
            print("  ", s)
        return

    # ---- 指标（与主脚本同口径）
    rows = []
    for m in mfrs + ["ALL"]:
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

    met_df = pd.DataFrame(rows)
    met_df.to_csv(out_dir / "metrics_summary.csv", index=False, encoding="utf-8-sig")
    with open(out_dir / "results.pkl", "wb") as fh:
        pickle.dump({"results": results, "variant": "pretrain+finetune", "skipped": skipped}, fh)

    print("\n===== 跨站预训练 + 本站微调 =====")
    cols = ["manufacturer", "n_events", "c_thr", "A", "f0_5", "recall", "FAR_event",
            "E", "lead_days_mean", "n_detected"]
    print(met_df[[c for c in cols if c in met_df.columns]].to_string(
        index=False, float_format=lambda x: f"{x:.3f}"))

    # ---- 短训练窗子集（<180 天）单独评估：这是本方法的目标场景
    print("\n===== 短训练窗子集（训练数据 < 180 天）=====")
    short = [r for r in results if r.get("train_days", 999) < 180]
    sub_rows = []
    for m in ("M1", "M2", "ALL"):
        s = short if m == "ALL" else [r for r in short if r["manufacturer"] == m]
        if not s:
            continue
        paths = {r["key"]: (r["c_path"], r["kind"]) for r in s}
        times = {r["key"]: r["times"] for r in s}
        reps = {r["key"]: r["report_date"] for r in s if r["kind"] == "fault"}
        thr, _ = calibrate_c_thr(s)
        met = metrics_with_lead(paths, times, reps, thr)
        met.update({"manufacturer": m, "n_events": len(s),
                    "n_fault": sum(1 for r in s if r["kind"] == "fault")})
        sub_rows.append(met)
    short_df = pd.DataFrame(sub_rows)
    short_df.to_csv(out_dir / "metrics_short_window.csv", index=False, encoding="utf-8-sig")
    if len(short_df):
        print(short_df[["manufacturer", "n_events", "n_fault", "c_thr", "A", "f0_5", "recall",
                        "E", "lead_days_mean"]].to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    else:
        print("（本次没有训练窗 < 180 天的事件）")

    (out_dir / "metrics.json").write_text(json.dumps(
        {"metrics": met_df.to_dict(orient="records"),
         "short_window": short_df.to_dict(orient="records"),
         "skipped": skipped[:20]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n耗时 {(time.time()-t0)/60:.1f} min -> {out_dir}")


if __name__ == "__main__":
    main()

