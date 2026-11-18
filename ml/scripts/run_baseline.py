"""按 PreDist 论文协议跑基线：每个事件训练一个自编码器正常行为模型。

用法:
  python scripts/run_baseline.py --mfr M1 --variant default --limit 3   # 冒烟测试
  python scripts/run_baseline.py --variant default                      # 全量
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
import traceback
from pathlib import Path

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import REPORTS                     # noqa: E402
from src.data import load_disturbances, load_substation  # noqa: E402
from src.features import add_point_features, select_phys  # noqa: E402
from src.models import AutoEncoderNBM, quantile_threshold  # noqa: E402
from src.protocol import (                          # noqa: E402
    Event, adaptive_threshold, build_test_frame, build_train_frame, criticality_from_mask,
    criticality_path, cusum_path, event_metrics, maintenance_mask, metrics_with_lead,
    prepare_xy, select_events,
)

DEFAULT_SCORE = {"M1": "mahalanobis", "M2": "rmse"}   # 论文 Table 3
DEFAULT_NOISE = {"M1": 0.05, "M2": 0.15}
DEFAULT_BOTTLENECK = {"M1": 0.65, "M2": 0.25}


def add_cyclic(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = df.index
    hour = idx.hour + idx.minute / 60.0
    doy = idx.dayofyear.astype(float)
    dow = idx.dayofweek.astype(float)
    df["_cyc_hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["_cyc_hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["_cyc_dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["_cyc_dow_cos"] = np.cos(2 * np.pi * dow / 7)
    df["_cyc_doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["_cyc_doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    return df


def run_event(ev: Event, variant: str, score_kind: str | None, max_iter: int,
              disturbances: pd.DataFrame, seed: int = 0, features: str = "raw",
              adapt_thr: bool = False, cusum: bool = False, q: float = 0.99,
              sensor_quality: bool = False) -> dict | None:
    t0 = time.time()
    df = load_substation(ev.manufacturer, ev.sid)
    if features in ("phys", "phys2"):
        ref = df.loc[ev.train_start:ev.train_end] if ev.train_start is not None else df
        df = add_point_features(df, ref)
        if features == "phys2":
            df = select_phys(df)
    if variant == "cyclic":
        df = add_cyclic(df)

    tr = build_train_frame(df, ev, disturbances)
    te = build_test_frame(df, ev)
    if len(tr) < 200 or len(te) < 10:
        return {"key": ev.key, "skipped": f"数据不足 train={len(tr)} test={len(te)}"}

    drops: list[str] = []
    force_global = False
    sq_note = ""
    if sensor_quality:
        from src.quality import assess_frame, derive_drops, outdoor_ok
        health = assess_frame(tr)
        drops = derive_drops(health, list(tr.columns))
        force_global = not outdoor_ok(health)
        out_v = health["outdoor_temperature"].verdict if "outdoor_temperature" in health else "missing"
        sq_note = f"outdoor={out_v};dropped={len(drops)}"

    prep = prepare_xy(tr, te, drop_cols=drops)
    if prep is None:
        return {"key": ev.key, "skipped": "有效特征不足"}
    Xtr, Xte, cols = prep

    kind = score_kind or DEFAULT_SCORE[ev.manufacturer]
    n_feat = Xtr.shape[1]
    bottleneck = max(1, int(round(n_feat * DEFAULT_BOTTLENECK[ev.manufacturer])))
    layers = (64, max(4, bottleneck))

    m = AutoEncoderNBM(layers=layers, noise=DEFAULT_NOISE[ev.manufacturer],
                       seed=seed, max_iter=max_iter)
    m.fit(Xtr)
    s_tr = m.score(Xtr, kind)
    s_te = m.score(Xte, kind)
    t_ae = quantile_threshold(s_tr, q)

    mmask = maintenance_mask(te.index, ev.sid, disturbances)
    if adapt_thr and not force_global and "outdoor_temperature" in tr.columns:
        thr_test = adaptive_threshold(tr["outdoor_temperature"], s_tr, te.get("outdoor_temperature"), q=q)
        label = f"adapt({np.nanmin(thr_test):.3f}~{np.nanmax(thr_test):.3f})"
    else:
        thr_test = np.full(len(s_te), t_ae)
        label = f"global({t_ae:.3f})"
    if cusum:
        cpath = cusum_path(s_te, thr_test, 0.5, mmask) if np.ndim(thr_test) else cusum_path(s_te, t_ae, 0.5, mmask)
        label += "+cusum"
    else:
        cpath = criticality_from_mask(s_te > thr_test, mmask)

    return {
        "key": ev.key, "manufacturer": ev.manufacturer, "event_id": ev.event_id,
        "sid": ev.sid, "kind": ev.kind, "fault_label": ev.fault_label,
        "monitoring_potential": ev.monitoring_potential, "config_type": ev.config_type,
        "c_max": int(cpath.max()) if len(cpath) else 0,
        "n_points": int(len(cpath)), "n_train": int(len(tr)), "n_features": int(n_feat),
        "t_ae": float(t_ae), "score_kind": kind, "thr_label": label,
        "times": te.index, "c_path": cpath, "score": s_te, "sq": sq_note,
        "report_date": ev.report_date,
        "elapsed_s": round(time.time() - t0, 1),
    }


def calibrate_c_thr(results: list[dict], grid=range(1, 101), n_splits: int = 5) -> tuple[int, pd.DataFrame]:
    """5 折分层 CV 在 1..100 上搜 C_thr，最大化 F0.5；返回各折最优的中位数。"""
    from sklearn.model_selection import StratifiedKFold

    paths = {r["key"]: (r["c_path"], r["kind"]) for r in results}
    labels = [r["kind"] if r["kind"] == "normal" else f"fault:{r['fault_label']}" for r in results]
    labels = pd.factorize(pd.Series(labels))[0]
    min_count = int(pd.Series(labels).value_counts().min()) if len(labels) else 0
    n_splits = int(max(1, min(n_splits, min_count)))
    if n_splits < 2:   # 类别过少（冒烟测试），直接在全量上搜
        best = (-1, 1)
        for thr in grid:
            f = event_metrics(paths, thr)["f0_5"]
            if f > best[0]:
                best = (f, thr)
        return int(best[1]), pd.DataFrame({"fold_best_c_thr": [best[1]]})
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)
    keys = [r["key"] for r in results]
    best_thr = []
    for tr_idx, va_idx in skf.split(keys, labels):
        sub_va = {keys[i]: paths[keys[i]] for i in va_idx}
        best = (-1, 1)
        for thr in grid:
            f = event_metrics(sub_va, thr)["f0_5"]
            if f > best[0]:
                best = (f, thr)
        best_thr.append(best[1])
    return int(np.median(best_thr)), pd.DataFrame({"fold_best_c_thr": best_thr})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mfr", default="all", choices=["all", "M1", "M2"])
    ap.add_argument("--variant", default="default", choices=["default", "cyclic"])
    ap.add_argument("--features", default="raw", choices=["raw", "phys", "phys2"],
                    help="raw=论文原始测点; phys=原始+物理残差工程特征")
    ap.add_argument("--adapt-thr", action="store_true", help="按室外温度分箱的工况自适应阈值")
    ap.add_argument("--cusum", action="store_true", help="用 CUSUM 代替 ±1 criticality")
    ap.add_argument("--sensor-quality", action="store_true",
                    help="传感器体检：坏传感器及其派生特征降级 + 室外温度不健康时关闭自适应阈值")
    ap.add_argument("--score", default=None, choices=[None, "mahalanobis", "rmse"])
    ap.add_argument("--max-iter", type=int, default=100)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--quantile", type=float, default=0.99, help="阈值分位（论文=0.99）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_dir = REPORTS / (args.out or f"baseline_{args.variant}")
    out_dir.mkdir(parents=True, exist_ok=True)

    events = select_events()
    events.to_csv(out_dir / "events_selected.csv", index=False, encoding="utf-8-sig")
    print(f"事件筛选: {len(events)} 个 "
          f"(fault={int((events.kind == 'fault').sum())}, normal={int((events.kind == 'normal').sum())})")
    print(events.groupby(["manufacturer", "kind"]).size())

    mfrs = ["M1", "M2"] if args.mfr == "all" else [args.mfr]
    dists = {m: load_disturbances(m) for m in ["M1", "M2"]}

    results, skipped = [], []
    t_start = time.time()
    todo = events[events.manufacturer.isin(mfrs)].reset_index(drop=True)
    if args.limit:
        todo = todo.groupby(["manufacturer", "kind"], group_keys=False).head(args.limit)
    print(f"待训练事件数: {len(todo)}")

    for i, row in todo.iterrows():
        ev = Event(
            manufacturer=row["manufacturer"], event_id=int(row["event_id"]), sid=int(row["sid"]),
            kind=row["kind"], report_date=row["report_date"] if pd.notna(row["report_date"]) else None,
            test_start=row["test_start"], test_end=row["test_end"],
            train_start=row["train_start"], train_end=row["train_end"],
            anomaly_start=row["anomaly_start"] if pd.notna(row["anomaly_start"]) else None,
            anomaly_end=row["anomaly_end"] if pd.notna(row["anomaly_end"]) else None,
            fault_label=row["fault_label"], monitoring_potential=row["monitoring_potential"],
            config_type=row["config_type"] if isinstance(row["config_type"], str) else "",
        )
        try:
            r = run_event(ev, args.variant, args.score, args.max_iter, dists[ev.manufacturer],
                          args.seed, features=args.features, adapt_thr=args.adapt_thr,
                          cusum=args.cusum, q=args.quantile,
                          sensor_quality=args.sensor_quality)
        except Exception as exc:  # 单个事件失败不阻断整体
            r = {"key": ev.key, "skipped": f"异常: {exc}"}
            traceback.print_exc()
        if r is None or "skipped" in r:
            skipped.append(r or {"key": ev.key, "skipped": "None"})
        else:
            results.append(r)
        if (i + 1) % 5 == 0 or i == len(todo) - 1:
            el = time.time() - t_start
            print(f"  [{i+1}/{len(todo)}] 完成 {len(results)} 跳过 {len(skipped)} "
                  f"已用 {el/60:.1f} min", flush=True)

    if not results:
        print("没有成功的事件，退出")
        return

    # ---- 阈值标定与指标
    c_thr, cv_df = calibrate_c_thr(results)
    cv_df.to_csv(out_dir / "c_thr_cv.csv", index=False)

    rows, per_event = [], []
    for m in mfrs:
        sub = [r for r in results if r["manufacturer"] == m]
        if not sub:
            continue
        paths = {r["key"]: (r["c_path"], r["kind"]) for r in sub}
        times = {r["key"]: r["times"] for r in sub}
        reps = {r["key"]: r["report_date"] for r in sub if r["kind"] == "fault"}
        rep_paths = {k: v for k, v in paths.items() if k in reps}
        # 逐厂商重新标定（论文分厂商给配置）
        thr_m, _ = calibrate_c_thr(sub)
        met = metrics_with_lead(paths, times, reps, thr_m)
        met.update({"manufacturer": m, "n_events": len(sub)})
        rows.append(met)
        for r in sub:
            per_event.append({
                "key": r["key"], "manufacturer": r["manufacturer"], "event_id": r["event_id"],
                "sid": r["sid"], "kind": r["kind"], "fault_label": r["fault_label"],
                "monitoring_potential": r["monitoring_potential"], "config_type": r["config_type"],
                "c_max": r["c_max"], "n_points": r["n_points"], "n_train": r["n_train"],
                "n_features": r["n_features"], "t_ae": r["t_ae"], "score_kind": r["score_kind"],
                "elapsed_s": r["elapsed_s"],
            })

    # 合并全部事件的总体指标（用各厂商阈值分别判定）
    all_paths, all_times, all_reps = {}, {}, {}
    for r in results:
        all_paths[r["key"]] = (r["c_path"], r["kind"])
        all_times[r["key"]] = r["times"]
        if r["kind"] == "fault":
            all_reps[r["key"]] = r["report_date"]
    # 用厂商阈值 + 汇总：为简化，先按全量再标定一次
    thr_all, _ = calibrate_c_thr(results)
    met_all = metrics_with_lead(all_paths, all_times, all_reps, thr_all)
    met_all.update({"manufacturer": "ALL", "n_events": len(results)})
    rows.append(met_all)

    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(out_dir / "metrics_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(per_event).to_csv(out_dir / "per_event.csv", index=False, encoding="utf-8-sig")

    with open(out_dir / "results.pkl", "wb") as fh:
        pickle.dump({"results": results, "c_thr": c_thr, "variant": args.variant,
                     "skipped": skipped}, fh)
    (out_dir / "metrics.json").write_text(json.dumps(
        {"c_thr_global": c_thr, "variant": args.variant,
         "metrics": metrics_df.to_dict(orient="records")}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("\n===== 指标汇总 =====")
    cols = ["manufacturer", "n_events", "c_thr", "TP", "FP", "FN", "TN", "A", "f0_5",
            "recall", "FAR_event", "E", "lead_days_mean", "lead_days_median", "n_detected"]
    cols = [c for c in cols if c in metrics_df.columns]
    print(metrics_df[cols].to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(f"\n耗时 {(time.time()-t_start)/60:.1f} min, 输出目录: {out_dir}")
    if skipped:
        print(f"跳过 {len(skipped)} 个事件（数据不足），详见 results.pkl")


if __name__ == "__main__":
    main()



