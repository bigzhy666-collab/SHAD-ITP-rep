"""跨站预训练 + 本站微调（解决小样本站点：M2 训练窗中位仅 105 天，最短 22 天）。

思路：
  1. 用其他站的运行数据构建"通用正常换热站"语料库；
  2. 在该语料库上预训练自编码器（学通用的特征结构与重构能力）；
  3. 对每个目标站，用其自身训练窗数据 warm-start 微调；
  4. 阈值仍由**本站**训练分数确定（保持"每站自校准"部署形态）。

两个关键设计（第一版踩过的坑）：
  * **每站独立标准化后再混合**：各站供暖曲线/流量量级不同，若用统一标准化，
    预训练学到的是"模糊平均站"，微调反而要先把错误尺度扳回来 → 实测掉点。
  * **防泄漏**：为某目标站预训练时把该站数据从语料库中剔除（等价于"新站冷启动"）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.neural_network import MLPRegressor

from .data import load_disturbances, load_substation
from .features import PHYS_COLS, add_cyclic_features, add_point_features, fit_reference
from .models import AutoEncoderNBM, _fit_mahalanobis

CYC_COLS = ["cyc_hour_sin", "cyc_hour_cos", "cyc_dow_sin", "cyc_dow_cos",
            "cyc_doy_sin", "cyc_doy_cos"]
COLS = PHYS_COLS + CYC_COLS


def _disturbance_mask(index: pd.DatetimeIndex, disturbances: pd.DataFrame, sid: int,
                      pad_hours: float = 4.0) -> np.ndarray:
    mask = np.zeros(len(index), dtype=bool)
    for t in disturbances.loc[disturbances["sid"] == sid, "event_start"].dropna():
        lo = np.searchsorted(index.values, np.datetime64(t - pd.Timedelta(hours=pad_hours)))
        hi = np.searchsorted(index.values, np.datetime64(t + pd.Timedelta(hours=pad_hours)))
        mask[max(0, lo):min(len(index), hi)] = True
    return mask


def fit_scaler(X: pd.DataFrame) -> dict:
    """单站/单批数据的标准化参数（全缺失列退化为常数 0）。"""
    med = X.median().fillna(0.0)
    Xf = X.fillna(med)
    lo = Xf.quantile(0.001).fillna(-10.0)
    hi = Xf.quantile(0.999).fillna(10.0)
    # 兜底：极值相同（常数列）时给一个合理区间，避免 clip 失效
    same = (hi - lo).abs() < 1e-9
    lo = lo.where(~same, lo - 1.0)
    hi = hi.where(~same, hi + 1.0)
    Xc = Xf.clip(lo, hi, axis=1)
    mu = Xc.mean().fillna(0.0)
    sd = Xc.std(ddof=0).replace(0, 1.0).fillna(1.0)
    return {"med": med, "lo": lo, "hi": hi, "mu": mu, "sd": sd}


def transform(X: pd.DataFrame, sc: dict) -> np.ndarray:
    Xf = X.reindex(columns=COLS).astype("float64").fillna(sc["med"])
    Xc = Xf.clip(sc["lo"], sc["hi"], axis=1)
    return ((Xc - sc["mu"]) / sc["sd"]).to_numpy("float64")


def station_corpus(tag: str, sid: int, row_cap: int = 6000, seed: int = 0):
    """单站"正常语料"矩阵（已按本站统计量标准化）+ 本站 scaler。"""
    df = load_substation(tag, sid)
    if len(df) < 500:
        return None, None
    df = df.loc[df.index.min() + pd.Timedelta(days=30):]
    if len(df) < 300:
        return None, None
    d = load_disturbances(tag)
    df = df[~_disturbance_mask(df.index, d, sid)]
    if len(df) < 300:
        return None, None

    ref = fit_reference(df.iloc[: min(len(df), 20000)])
    feats = add_cyclic_features(add_point_features(df, reference=ref))
    X = feats.reindex(columns=COLS).astype("float64")
    if len(X) > row_cap:
        idx = np.random.default_rng(seed + sid).choice(len(X), row_cap, replace=False)
        X = X.iloc[np.sort(idx)]
    sc = fit_scaler(X)
    return transform(X, sc), sc


def build_corpus(tags=("M1", "M2"), row_cap: int = 6000) -> dict[str, dict[int, np.ndarray]]:
    from .data import substation_ids
    pools: dict[str, dict[int, np.ndarray]] = {}
    for tag in tags:
        pools[tag] = {}
        for sid in substation_ids(tag):
            try:
                X, _ = station_corpus(tag, sid, row_cap=row_cap)
            except Exception:
                X = None
            if X is not None and len(X) >= 300:
                pools[tag][sid] = X
        n = len(pools[tag])
        print(f"  {tag} 语料库: {n} 个站, 共 {sum(len(v) for v in pools[tag].values())} 行")
    return pools


def pretrain(tag: str, exclude_sid: int, pools: dict, total_cap: int = 60000,
             max_iter: int = 45, seed: int = 0) -> AutoEncoderNBM:
    """排除目标站后，在"各站独立标准化"的语料上预训练 AE。"""
    parts = [v for k, v in pools[tag].items() if k != exclude_sid]
    if not parts:
        raise ValueError(f"{tag}: 语料库为空")
    X = np.concatenate(parts, axis=0)
    if len(X) > total_cap:
        idx = np.random.default_rng(seed).choice(len(X), total_cap, replace=False)
        X = X[np.sort(idx)]
    return AutoEncoderNBM(layers=(64, 8), noise=0.05, seed=seed, max_iter=max_iter).fit(X)


def finetune(base: AutoEncoderNBM, X_target: np.ndarray, iters: int = 30,
             lr: float = 1.2e-4) -> AutoEncoderNBM:
    """在本站训练数据上 warm-start 微调（权重继承、小学习率）。

    注意：不能直接 deepcopy 已 fit 的 estimator 再改 early_stopping 重训——
    sklearn 的 best_loss_ / loss_curve_ / t_ 状态会残留导致异常，
    因此新建一个干净 estimator，只手工继承权重矩阵与优化器状态。
    """
    src = base.model
    new = MLPRegressor(
        hidden_layer_sizes=src.hidden_layer_sizes,
        activation=src.activation,
        solver="adam",
        learning_rate_init=lr,
        batch_size=src.batch_size,
        max_iter=iters,
        early_stopping=False,
        shuffle=True,
        random_state=base.seed,
        tol=1e-6,
        warm_start=True,
    )
    new.coefs_ = [c.copy() for c in src.coefs_]
    new.intercepts_ = [b.copy() for b in src.intercepts_]
    new.n_layers_ = src.n_layers_
    new.n_outputs_ = src.n_outputs_
    new.out_activation_ = src.out_activation_
    new.t_ = 0
    new._no_improvement_count = 0
    new.best_loss_ = np.inf
    new.loss_curve_ = []
    new.validation_scores_ = []
    new.n_iter_ = 0

    rng = np.random.default_rng(base.seed)
    new.fit(X_target + rng.normal(0.0, 0.02, size=X_target.shape), X_target)

    out = AutoEncoderNBM(layers=base.layers, noise=0.02, seed=base.seed, max_iter=1)
    out.model = new
    out._md = _fit_mahalanobis(out.residual(X_target))
    return out
