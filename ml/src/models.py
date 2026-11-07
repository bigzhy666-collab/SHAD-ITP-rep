"""模型层：正常行为模型（NBM）与异常打分。

基线（对齐论文）：自编码器 AE = 输入 -> [64,32] -> 重建输入，训练加高斯噪声正则，
异常分数 = RMSE 或 Mahalanobis 距离，阈值 = 训练分数 99% 分位。

我们的改进版会在此基础上加入：物理残差特征、配置分层/跨站预训练、工况自适应阈值。
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.decomposition import PCA
from sklearn.neural_network import MLPRegressor


# ---------------------------------------------------------------- 自编码器
class AutoEncoderNBM:
    """MLP 自编码器（sklearn 实现，等价于 输入→64→32→n_features 的对称重构网络）。"""

    def __init__(self, layers=(64, 32), lr: float = 4.5e-4, noise: float = 0.05,
                 seed: int = 0, max_iter: int = 100, batch_size: int = 256):
        self.layers = tuple(layers)
        self.lr = lr
        self.noise = noise
        self.seed = seed
        self.max_iter = max_iter
        self.batch_size = batch_size
        self.model = None
        self._md = None

    def fit(self, X: np.ndarray) -> "AutoEncoderNBM":
        rng = np.random.default_rng(self.seed)
        Xn = X + rng.normal(0.0, self.noise, size=X.shape) if self.noise > 0 else X
        # 训练集够小时关闭 early stopping，避免验证集太小
        es = len(X) > 2000
        self.model = MLPRegressor(
            hidden_layer_sizes=self.layers,
            activation="relu",
            solver="adam",
            learning_rate_init=self.lr,
            batch_size=min(self.batch_size, max(32, len(X) // 10)),
            max_iter=self.max_iter,
            early_stopping=es,
            validation_fraction=0.2 if es else 0.0,
            n_iter_no_change=5,
            random_state=self.seed,
            tol=1e-5,
        )
        self.model.fit(Xn, X)
        err = self.residual(X)
        self._md = _fit_mahalanobis(err)
        return self

    def residual(self, X: np.ndarray) -> np.ndarray:
        return X - self.model.predict(X)

    def score(self, X: np.ndarray, kind: str = "rmse") -> np.ndarray:
        err = self.residual(X)
        if kind == "rmse":
            return np.sqrt(np.mean(err ** 2, axis=1))
        if kind == "mahalanobis":
            return _mahalanobis(err, *self._md)
        raise ValueError(f"未知异常分数类型: {kind}")


def _fit_mahalanobis(err: np.ndarray):
    p = err.shape[1]
    mu = err.mean(axis=0)
    cov = np.cov(err, rowvar=False)
    cov = np.atleast_2d(cov)
    ridge = max(1e-6, 1e-4 * np.trace(cov) / p)
    cov = cov + np.eye(p) * ridge
    inv = np.linalg.pinv(cov)
    return mu, inv


def _mahalanobis(err: np.ndarray, mu: np.ndarray, inv: np.ndarray) -> np.ndarray:
    d = err - mu
    val = np.einsum("ij,jk,ik->i", d, inv, d)
    return np.sqrt(np.clip(val, 0, None))


# ---------------------------------------------------------------- 对比用模型
class PCANBM:
    """PCA 残差（SPE / Q 统计量）：经典多元统计过程监控基线，可解释性最好。"""

    def __init__(self, n_components: float | int = 0.9, seed: int = 0):
        self.n_components = n_components
        self.pca = None

    def fit(self, X: np.ndarray) -> "PCANBM":
        self.pca = PCA(n_components=self.n_components, random_state=0)
        self.pca.fit(X)
        return self

    def score(self, X: np.ndarray, kind: str = "spe") -> np.ndarray:
        Xr = self.pca.inverse_transform(self.pca.transform(X))
        err = X - Xr
        if kind == "spe":
            return np.sqrt(np.mean(err ** 2, axis=1))
        # Hotelling T^2
        z = self.pca.transform(X)
        return np.sum((z / np.sqrt(self.pca.explained_variance_)) ** 2, axis=1)


class IForestNBM:
    def __init__(self, n_estimators: int = 200, seed: int = 0):
        self.model = IsolationForest(n_estimators=n_estimators, random_state=seed, n_jobs=-1)

    def fit(self, X: np.ndarray) -> "IForestNBM":
        self.model.fit(X)
        return self

    def score(self, X: np.ndarray, kind: str = "if") -> np.ndarray:
        return -self.model.score_samples(X)


# ---------------------------------------------------------------- 阈值
def quantile_threshold(train_score: np.ndarray, q: float = 0.99) -> float:
    return float(np.quantile(train_score, q))
