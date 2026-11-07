"""窗口级监督模型（跨站训练）：故障二分类 + 故障类型多分类。

与无监督正常行为模型互补：
  无监督 = "这个站现在正常吗"（不需要标签，零门槛部署）
  监督   = "这个窗口像不像某类故障"（跨站借用历史工单，可给出故障类型建议）

评估严格按 PreDist 协议：报修前 7 天窗口内、提前量 = 报修时刻 - 首次告警窗口终点。
"""
from __future__ import annotations

import os
# 必须在 import sklearn/numpy 之前设置：本机沙箱禁止 python 创建命名管道，
# 多线程后端会走 multiprocessing.pool.ThreadPool -> os.pipe -> WinError 5。
# 单线程还顺带保证结果可复现。
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import json
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, balanced_accuracy_score
from sklearn.model_selection import GroupKFold

from src.common import REPORTS                       # noqa: E402
from src.data import load_disturbances, load_substation  # noqa: E402
from src.features import build_features, window_features  # noqa: E402
from src.protocol import select_events                # noqa: E402

# 报修前采样锚点（小时）：7 天测试窗 = 168h
OFFSETS = [6, 12, 24, 48, 72, 120, 168]
WIN_H, STRIDE_H = 6.0, 3.0
N_HARD_NEG = 3          # 每个故障事件额外采样的"同站硬负样本"数


def _station_features(cache: dict, tag: str, sid: int, ref_start, ref_end) -> pd.DataFrame:
    key = (tag, sid, str(ref_start), str(ref_end))
    if key in cache:
        return cache[key]
    df = load_substation(tag, sid)
    ref = df.loc[ref_start:ref_end] if ref_start is not None else df
    feats = build_features(df, reference=None, mode="phys2", cyclic=True) \
        if ref is None else build_features(df, reference=None, mode="phys2", cyclic=True)
    # 用训练期重算供暖曲线基准，保证不泄漏未来信息
    from src.features import add_point_features, select_phys, add_cyclic_features, fit_reference
    reference = fit_reference(ref) if len(ref) > 200 else None
    feats = add_point_features(df, reference=reference)
    feats = add_cyclic_features(select_phys(feats))
    cache[key] = feats
    return feats


def build_dataset() -> pd.DataFrame:
    ev = select_events()
    cache: dict = {}
    rows = []
    dists = {tag: load_disturbances(tag) for tag in ("M1", "M2")}
    rng = np.random.default_rng(0)

    faults = ev[ev.kind == "fault"].copy()
    normals = ev[ev.kind == "normal"].copy()

    for _, e in faults.iterrows():
        rep = pd.Timestamp(e["report_date"])
        ref_s, ref_e = e["train_start"], e["train_end"]
        try:
            feats = _station_features(cache, e["manufacturer"], int(e["sid"]), ref_s, ref_e)
        except Exception:
            continue
        for h in OFFSETS:
            end = rep - pd.Timedelta(hours=h)
            start = end - pd.Timedelta(hours=WIN_H)
            w = window_features(feats, start, end, WIN_H, STRIDE_H)
            if w.empty:
                continue
            row = w.iloc[[0]].copy()
            row["label"] = 1
            row["fault_label"] = e["fault_label"]
            row["mp"] = e["monitoring_potential"]
            row["event_key"] = f"{e['manufacturer']}_E{e['event_id']}"
            row["manufacturer"] = e["manufacturer"]
            row["sid"] = int(e["sid"])
            row["offset_h"] = h
            rows.append(row)

        # —— 同站硬负样本：从"远离任何报修/维修"的时段随机取窗，避免模型只会区分"冬季故障窗 vs 夏季正常窗"
        d = dists[e["manufacturer"]]
        d = d[(d["sid"] == int(e["sid"]))]["event_start"].dropna()
        bad = [(pd.Timestamp(t) - pd.Timedelta(days=3), pd.Timestamp(t) + pd.Timedelta(days=3)) for t in d]
        bad.append((rep - pd.Timedelta(days=8), rep + pd.Timedelta(days=8)))
        idx = feats.index
        ok_t = []
        for t in idx[rng.integers(0, len(idx), size=min(200, len(idx)))]:
            if any(a <= t <= b for a, b in bad):
                continue
            ok_t.append(t)
            if len(ok_t) >= N_HARD_NEG:
                break
        for t in ok_t:
            w = window_features(feats, t - pd.Timedelta(hours=WIN_H), t, WIN_H, STRIDE_H)
            if w.empty:
                continue
            row = w.iloc[[0]].copy()
            row["label"] = 0
            row["fault_label"] = "normal"
            row["mp"] = np.nan
            row["event_key"] = f"{e['manufacturer']}_H{e['event_id']}"
            row["manufacturer"] = e["manufacturer"]
            row["sid"] = int(e["sid"])
            row["offset_h"] = np.nan
            rows.append(row)

    for _, e in normals.iterrows():
        ref_s, ref_e = e["train_start"], e["train_end"]
        try:
            feats = _station_features(cache, e["manufacturer"], int(e["sid"]), ref_s, ref_e)
        except Exception:
            continue
        w = window_features(feats, e["test_start"], e["test_end"], WIN_H, 6.0)
        if w.empty:
            continue
        # 正常事件窗较长，抽样最多 6 个窗口
        if len(w) > 6:
            w = w.iloc[np.linspace(0, len(w) - 1, 6).astype(int)]
        for k in range(len(w)):
            row = w.iloc[[k]].copy()
            row["label"] = 0
            row["fault_label"] = "normal"
            row["mp"] = np.nan
            row["event_key"] = f"{e['manufacturer']}_N{e['event_id']}"
            row["manufacturer"] = e["manufacturer"]
            row["sid"] = int(e["sid"])
            row["offset_h"] = np.nan
            rows.append(row)

    if not rows:
        raise SystemExit("没有构造出样本")
    ds = pd.concat(rows, ignore_index=True)
    ds["group"] = ds["manufacturer"].astype(str) + "_" + ds["sid"].astype(str)
    return ds


def feature_cols(ds: pd.DataFrame) -> list[str]:
    drop = {"label", "fault_label", "mp", "event_key", "manufacturer", "sid",
            "offset_h", "group", "window_start", "window_end"}
    cols = [c for c in ds.columns if c not in drop and pd.api.types.is_numeric_dtype(ds[c])]
    return cols


def event_level_metrics(ds: pd.DataFrame, prob: np.ndarray, thr: float) -> dict:
    """把窗口概率聚合成事件级指标（与论文协议同口径）。"""
    d = ds.copy()
    d["prob"] = prob
    tp = fp = fn = tn = 0
    leads, ears, point_acc = [], [], []
    for key, g in d.groupby("event_key"):
        if "_H" in key:      # 硬负样本只参与训练/窗口级 AUC，不进事件级协议评估
            continue
        kind = "fault" if g["label"].iloc[0] == 1 else "normal"
        if kind == "fault":
            hit = g[g["prob"] >= thr]
            if len(hit):
                tp += 1
                # 提前量 = 报修前最早命中的锚点
                lead_h = float(hit["offset_h"].max())
                leads.append(lead_h)
                ears.append(min(1.0, max(0.0, lead_h / 24.0)))
            else:
                fn += 1
                ears.append(0.0)
        else:
            # 正常事件：按窗口计点级误报
            if (g["prob"] >= thr).any():
                fp += 1
            else:
                tn += 1
            point_acc.append(float((g["prob"] < thr).mean()))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f05 = (1.25 * precision * recall / (0.25 * precision + recall)) if precision + recall else 0.0
    return {
        "thr": thr, "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "f0_5": f05,
        "A": float(np.mean(point_acc)) if point_acc else np.nan,
        "FAR_event": fp / (fp + tn) if fp + tn else np.nan,
        "E": float(np.mean(ears)) if ears else np.nan,
        "lead_days_mean": float(np.mean(leads) / 24.0) if leads else np.nan,
        "lead_days_median": float(np.median(leads) / 24.0) if leads else np.nan,
        "n_detected": len(leads),
    }


def best_threshold(ds: pd.DataFrame, prob: np.ndarray) -> tuple[float, dict]:
    best = (-1.0, 0.5, {})
    for thr in np.arange(0.02, 0.99, 0.02):
        met = event_level_metrics(ds, prob, float(thr))
        if met["f0_5"] > best[0]:
            best = (met["f0_5"], float(thr), met)
    return best[1], best[2]


def main():
    out_dir = REPORTS / "supervised"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("构造窗口级样本集 ...")
    ds = build_dataset()
    cols = feature_cols(ds)
    print(f"样本 {len(ds)} 个窗口 | 故障窗口 {int(ds.label.sum())} / 正常窗口 {int((1-ds.label).sum())} "
          f"| 事件 {ds.event_key.nunique()} 个 | 特征 {len(cols)} 维")
    ds.to_pickle(out_dir / "dataset.pkl")

    X = ds[cols].to_numpy("float64")
    y = ds["label"].to_numpy()
    groups = ds["group"].to_numpy()

    # ---------- 1) 二分类：跨站 GroupKFold，拿 OOF 概率
    oof = np.zeros(len(ds))
    gkf = GroupKFold(n_splits=5)
    for fold, (tr, va) in enumerate(gkf.split(X, y, groups)):
        clf = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
            l2_regularization=1.0, class_weight="balanced",
            early_stopping=True, validation_fraction=0.15, random_state=fold,
        )
        clf.fit(X[tr], y[tr])
        oof[va] = clf.predict_proba(X[va])[:, 1]
        print(f"  fold {fold+1}: 训练 {len(tr)} 验证 {len(va)}")

    auc = roc_auc_score(y, oof)
    ap = average_precision_score(y, oof)
    print(f"窗口级 AUC={auc:.3f}  PR-AUC={ap:.3f}")

    thr, met = best_threshold(ds, oof)
    print("\n===== 事件级（OOF，阈值按 F0.5 最优）=====")
    for k in ("thr", "TP", "FP", "FN", "TN", "A", "f0_5", "recall", "FAR_event",
              "E", "lead_days_mean", "lead_days_median", "n_detected"):
        print(f"  {k}: {met[k]}")

    # ---------- 2) 故障类型多分类（只用故障窗口，按站分组评估）
    pos = ds[ds.label == 1].copy()
    Xp = pos[cols].to_numpy("float64")
    yp = pos["fault_label"].astype(str).to_numpy()
    groups_p = pos["group"].to_numpy()
    clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06,
                                         l2_regularization=1.0, class_weight="balanced",
                                         random_state=0)
    n_splits = min(5, max(2, pos["group"].nunique()))
    gkf3 = GroupKFold(n_splits=n_splits)
    correct = top3 = total = 0
    for tr, va in gkf3.split(Xp, yp, groups_p):
        clf.fit(Xp[tr], yp[tr])
        proba = clf.predict_proba(Xp[va])
        classes = clf.classes_
        pred = classes[proba.argmax(1)]
        top = classes[np.argsort(proba, axis=1)[:, -3:]]
        correct += int((pred == yp[va]).sum())
        top3 += int(sum(yp[va][i] in top[i] for i in range(len(va))))
        total += len(va)
    acc = correct / total if total else np.nan
    top3_acc = top3 / total if total else np.nan
    print(f"\n故障类型多分类（按站分组 {n_splits} 折）：准确率={acc:.3f}  Top3={top3_acc:.3f} "
          f"（{len(set(yp))} 类，{len(yp)} 个窗口）")

    # ---------- 3) 保存
    ds_out = ds[["event_key", "label", "fault_label", "mp", "manufacturer", "sid", "offset_h"]].copy()
    ds_out["oof_prob"] = oof
    ds_out.to_csv(out_dir / "oof_predictions.csv", index=False, encoding="utf-8-sig")
    summary = {"n_windows": len(ds), "n_features": len(cols), "auc": float(auc), "pr_auc": float(ap),
               "event_level": met, "fault_type_accuracy": float(acc), "fault_type_top3": float(top3_acc),
               "offsets_h": OFFSETS}
    (out_dir / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # 最终模型（全量训练，用于部署/演示）
    final = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                           max_leaf_nodes=31, l2_regularization=1.0,
                                           class_weight="balanced", random_state=0)
    final.fit(X, y)
    with open(out_dir / "model_binary.pkl", "wb") as fh:
        pickle.dump({"model": final, "cols": cols, "threshold": thr,
                     "win_h": WIN_H, "offsets_h": OFFSETS}, fh)
    print(f"\n输出: {out_dir}")


if __name__ == "__main__":
    main()
