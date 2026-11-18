"""模型产物（Model Card 对应的可运行实现）。

这是"只交付模型"的核心接口：
  - train_station_model(...)  用某个站的历史数据训练一个正常行为模型，存成 .pkl
  - StationModel.detect(df)   对新数据（含国内数据，字段映射后）输出逐点异常分数、
                              阈值、criticality 与告警段
训练/推理使用同一套特征与标准化参数，避免线上线下的偏差。

依赖：numpy / pandas / scikit-learn（无需 TensorFlow）
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ALL_RAW          # noqa: F401  (保留以便字段映射时参考)
from .data import load_disturbances, load_substation
from .features import build_features, fit_reference
from .models import AutoEncoderNBM
from .protocol import is_excluded

# 与论文 Table 3 一致的默认超参
DEFAULT_SCORE = {"M1": "mahalanobis", "M2": "rmse"}
DEFAULT_NOISE = {"M1": 0.05, "M2": 0.15}
DEFAULT_BOTTLENECK = {"M1": 0.65, "M2": 0.25}
# 由 5 折 CV 标定得到的持续性阈值（见 reports/*/c_thr_cv.csv）
DEFAULT_C_THR = {"M1": 11, "M2": 7}


@dataclass
class StationModel:
    tag: str
    sid: int
    feature_mode: str = "phys2"
    cyclic: bool = True
    score_kind: str = "rmse"
    q: float = 0.99
    layers: tuple = (64, 8)
    noise: float = 0.05
    adaptive: bool = True
    c_thr: int = 7

    reference: dict = field(default_factory=dict)
    cols: list = field(default_factory=list)
    impute: np.ndarray | None = None
    clip_lo: np.ndarray | None = None
    clip_hi: np.ndarray | None = None
    mu: np.ndarray | None = None
    sd: np.ndarray | None = None
    ae: AutoEncoderNBM | None = None
    thr_global: float = np.nan
    edges: np.ndarray | None = None
    thr_map: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- 变换
    def transform(self, df: pd.DataFrame) -> np.ndarray:
        X = df.reindex(columns=self.cols).astype("float64")
        X = X.fillna(pd.Series(self.impute, index=self.cols))
        X = X.clip(self.clip_lo, self.clip_hi, axis=1)
        X = (X - self.mu) / self.sd
        return X.to_numpy("float64")

    def score(self, X: np.ndarray) -> np.ndarray:
        return self.ae.score(X, self.score_kind)

    def thresholds(self, outdoor: pd.Series | None = None) -> np.ndarray | float:
        if not self.adaptive or self.edges is None or outdoor is None:
            return self.thr_global
        out = pd.to_numeric(outdoor, errors="coerce").to_numpy("float64")
        med = float(np.nanmedian(out)) if np.isfinite(out).any() else 0.0
        bins = np.digitize(np.nan_to_num(out, nan=med), self.edges)
        default = float(np.median(list(self.thr_map.values()))) if self.thr_map else self.thr_global
        return np.array([self.thr_map.get(int(b), default) for b in bins], dtype="float64")

    # ---------------------------------------------------------------- 推理
    def detect(self, df_raw: pd.DataFrame, outdoor_col: str = "outdoor_temperature") -> pd.DataFrame:
        """对一段新数据输出逐点检测结果。df_raw 需包含训练时的同名测点列。"""
        feats = build_features(df_raw, reference=self.reference, mode=self.feature_mode, cyclic=self.cyclic)
        X = self.transform(feats)
        s = self.score(X)
        thr = self.thresholds(feats[outdoor_col] if outdoor_col in feats.columns else None)
        thr = np.broadcast_to(np.asarray(thr, dtype="float64"), s.shape) if np.ndim(thr) else np.full(s.shape, thr)
        alarm = s > thr

        # criticality（+1 / -1，下限 0）
        c = np.zeros(len(s), dtype="int32")
        v = 0
        for i in range(len(s)):
            v = v + 1 if alarm[i] else max(0, v - 1)
            c[i] = v

        out = pd.DataFrame({
            "score": s, "threshold": thr, "alarm": alarm, "criticality": c,
            "health": np.clip(1.0 - s / np.where(thr > 0, thr, 1e-9), 0.0, 1.0),
            "confirmed": c >= self.c_thr,
        }, index=df_raw.index if len(df_raw) == len(s) else feats.index)
        return out


def _fit_transform(train_df: pd.DataFrame) -> tuple[np.ndarray, list, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    cand = [c for c in train_df.columns
            if not is_excluded(c) and pd.api.types.is_numeric_dtype(train_df[c])]
    X = train_df[cand].astype("float64")
    miss = X.isna().mean()
    std = X.std(ddof=0)
    zero_frac = (X == 0).mean()
    keep = [c for c in cand
            if miss.get(c, 1.0) <= 0.8 and std.get(c, 0.0) > 1e-9 and zero_frac.get(c, 1.0) <= 0.5]
    if len(keep) < 3:
        raise ValueError(f"有效特征不足: {keep}")
    X = X[keep]
    mu = X.mean()
    X = X.fillna(mu)
    lo, hi = X.quantile(0.001), X.quantile(0.999)
    X = X.clip(lo, hi, axis=1)
    sd = X.std(ddof=0).replace(0, 1.0)
    Xz = (X - mu) / sd
    return (Xz.to_numpy("float64"), keep, mu.to_numpy(), sd.to_numpy(),
            lo.to_numpy(), hi.to_numpy())


def train_station_model(tag: str, sid: int, train_start=None, train_end=None,
                        feature_mode: str = "phys2",
                        cyclic: bool = True, adaptive: bool = True,
                        q: float = 0.99, c_thr: int | None = None,
                        max_iter: int = 100, seed: int = 0,
                        remove_disturbances: bool = True,
                        valid_frac: float = 0.0) -> StationModel:
    """训练一个站的正常行为模型。

    默认取该站最后 12 个月数据（去掉最后 14 天作为"待检测"缓冲）。
    """
    df = load_substation(tag, sid)
    if len(df) < 500:
        raise ValueError(f"{tag} 站 {sid} 数据不足: {len(df)} 行")

    if train_end is None:
        train_end = df.index.max() - pd.Timedelta(days=14)
    if train_start is None:
        train_start = max(df.index.min(), train_end - pd.Timedelta(days=365))
    tr = df.loc[train_start:train_end]
    if len(tr) < 500:
        raise ValueError(f"训练区间过短: {len(tr)} 行")

    if remove_disturbances:
        d = load_disturbances(tag)
        mask = np.zeros(len(tr), dtype=bool)
        idx = tr.index
        for t in d.loc[d["sid"] == sid, "event_start"].dropna():
            lo = np.searchsorted(idx.values, np.datetime64(t - pd.Timedelta(hours=4)))
            hi = np.searchsorted(idx.values, np.datetime64(t + pd.Timedelta(hours=4)))
            mask[max(0, lo):min(len(idx), hi)] = True
        tr = tr[~mask]

    if valid_frac > 0:
        n_val = int(len(tr) * valid_frac)
        tr, _ = tr.iloc[:-n_val], tr.iloc[-n_val:]

    ref = fit_reference(tr)
    feats = build_features(tr, reference=ref, mode=feature_mode, cyclic=cyclic)
    X, cols, mu, sd, lo, hi = _fit_transform(feats)

    n_feat = X.shape[1]
    bottleneck = max(1, int(round(n_feat * DEFAULT_BOTTLENECK[tag])))
    layers = (64, max(4, bottleneck))
    ae = AutoEncoderNBM(layers=layers, noise=DEFAULT_NOISE[tag], seed=seed, max_iter=max_iter).fit(X)

    model = StationModel(
        tag=tag, sid=sid, feature_mode=feature_mode, cyclic=cyclic,
        score_kind=DEFAULT_SCORE[tag], q=q, layers=layers, noise=DEFAULT_NOISE[tag],
        adaptive=adaptive, c_thr=int(c_thr if c_thr is not None else DEFAULT_C_THR[tag]),
        reference=ref, cols=cols, impute=mu, clip_lo=lo, clip_hi=hi, mu=mu, sd=sd, ae=ae,
        meta={"train_start": str(train_start), "train_end": str(train_end),
              "n_train": int(len(tr)), "n_features": int(n_feat),
              "max_iter": max_iter, "seed": seed},
    )
    model.thr_global = float(np.quantile(ae.score(X, model.score_kind), q))
    if adaptive and "outdoor_temperature" in feats.columns:
        out = feats["outdoor_temperature"].to_numpy("float64")
        ok = np.isfinite(out)
        if ok.sum() > 200:
            edges = np.unique(np.nanquantile(out[ok], np.linspace(0, 1, 6)))[1:-1]
            model.edges = edges
            s = ae.score(X, model.score_kind)
            bins = np.digitize(out, edges)
            thr_map = {}
            for b in np.unique(bins):
                m = bins == b
                if m.sum() >= 100:
                    thr_map[int(b)] = float(np.quantile(s[m], q))
            model.thr_map = thr_map
    return model


# ---------------------------------------------------------------- 持久化
def save_model(model: StationModel, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(model, fh)
    return path


def load_model(path: str | Path) -> StationModel:
    with open(path, "rb") as fh:
        return pickle.load(fh)


# ---------------------------------------------------------------- 国内数据字段映射
STANDARD_ALIASES = {
    "供水温度": "s_hc1_supply_temperature",
    "一次供水温度": "p_net_supply_temperature",
    "一次回水温度": "p_net_return_temperature",
    "一次侧供水温度": "p_net_supply_temperature",
    "一次侧回水温度": "p_net_return_temperature",
    "回水温度": "p_hc1_return_temperature",
    "二次供水温度": "s_hc1_supply_temperature",
    "二次回水温度": "p_hc1_return_temperature",
    "供水温度设定值": "s_hc1_supply_temperature_setpoint",
    "设定供水温度": "s_hc1_supply_temperature_setpoint",
    "瞬时流量": "p_net_meter_flow",
    "流量": "p_net_meter_flow",
    "瞬时热量": "p_net_meter_heat_power",
    "热量": "p_net_meter_heat_power",
    "功率": "p_net_meter_heat_power",
    "室外温度": "outdoor_temperature",
    "户外温度": "outdoor_temperature",
}


def map_columns(df: pd.DataFrame, mapping: dict[str, str] | None = None,
                time_col: str | None = None) -> pd.DataFrame:
    """把国内热力公司/其他来源的列名映射到本项目标准列名。

    mapping: {"原始列名": "标准列名"}，未给出的列尝试用 STANDARD_ALIASES 自动匹配。
    """
    ren = {}
    for c in df.columns:
        if c in (mapping or {}):
            ren[c] = mapping[c]
        elif c in STANDARD_ALIASES:
            ren[c] = STANDARD_ALIASES[c]
    out = df.rename(columns=ren)
    if time_col:
        out = out.set_index(pd.to_datetime(out[time_col], errors="coerce"))
    elif not isinstance(out.index, pd.DatetimeIndex):
        for c in ("timestamp", "时间", "时间戳", "datetime", "date"):
            if c in out.columns:
                out = out.set_index(pd.to_datetime(out[c], errors="coerce"))
                break
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out

