"""Administrator-owned manifest. Browser input cannot select pickle paths."""
import hashlib
import importlib
import logging
import sys
import warnings
from pathlib import Path
from threading import Lock

import numpy as np
from sklearn.exceptions import InconsistentVersionWarning

from .errors import ServiceError
from .schemas import FIELDS, OPTIONAL_FIELDS, ModelRegistration, RegistryConfig

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("shad.registry")


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModelRegistry:
    def __init__(self, config_path: Path | None = None, artifact_root: Path | None = None,
                 config: RegistryConfig | None = None):
        self.artifact_root = (artifact_root or ROOT / "ml/models").resolve()
        config = RegistryConfig.model_validate_json(config_path.read_text(encoding="utf-8-sig")) \
            if config_path else config or RegistryConfig()
        self.config = config
        self.stations = {s.id: s.model_dump() for s in config.stations}
        self.entries: dict[tuple[str, str], ModelRegistration] = {}
        self.cache = {}
        self.lock = Lock()
        if len(self.stations) != len(config.stations):
            raise ValueError("注册表站点 ID 重复")
        for entry in config.models:
            key = (entry.id, entry.version)
            if key in self.entries:
                raise ValueError("模型 ID 和版本重复；不能覆盖已有版本")
            station = self.stations.get(entry.stationId)
            if not station or station["timezone"] != entry.trainingTimezone:
                raise ValueError("模型必须绑定已登记且时区一致的站点")
            self.entries[key] = entry

    def _path(self, entry: ModelRegistration) -> Path:
        # Resolve symlinks too. Only files inside administrator-managed model root.
        path = (self.artifact_root / entry.artifact).resolve()
        if not path.is_relative_to(self.artifact_root) or path.suffix != ".pkl":
            raise ValueError("模型不在可信目录或格式不支持")
        if checksum(path) != entry.artifactChecksum:
            raise ValueError("模型校验值不匹配；请登记新版本")
        return path

    def resolve(self, model_id: str, version: str):
        entry = self.entries.get((model_id, version))
        if entry is None:
            raise ServiceError("NOT_FOUND", "未登记此模型版本。", 404)
        try:
            with self.lock:
                path = self._path(entry)  # Re-check even when cached: no silent artifact replacement.
                key = (entry.id, entry.version)
                if key not in self.cache:
                    ml_root = str(ROOT / "ml")
                    if ml_root not in sys.path:
                        sys.path.insert(0, ml_root)
                    inference = importlib.import_module("src.inference")
                    with warnings.catch_warnings():
                        # sklearn does not guarantee pickle portability across versions.
                        warnings.simplefilter("error", InconsistentVersionWarning)
                        model = inference.load_model(path)
                    if not isinstance(model, inference.StationModel) or model.ae is None:
                        raise ValueError("不是已拟合的 StationModel")
                    if not model.cols or len(model.cols) != len(set(model.cols)):
                        raise ValueError("训练字段无效")
                    if model.c_thr < 1 or not np.isfinite(model.thr_global) or model.thr_global <= 0:
                        raise ValueError("模型阈值配置无效")
                    self.cache[key] = model
                model = self.cache[key]
        except Exception as exc:
            logger.exception("Model unavailable: %s@%s", entry.id, entry.version)
            raise ServiceError("MODEL_UNAVAILABLE", "模型不可用，请核查产物校验值、依赖版本及服务日志。",
                               503, False) from exc
        return entry, model

    @staticmethod
    def metadata(entry, model) -> dict:
        return {
            "id": entry.id, "version": entry.version, "stationId": entry.stationId,
            "name": entry.name, "artifactChecksum": entry.artifactChecksum,
            "purpose": "station_anomaly_detection", "isDemo": entry.isDemo,
            "trainingTimezone": entry.trainingTimezone, "trainedAt": None,
            "trainStart": model.meta.get("train_start"), "trainEnd": model.meta.get("train_end"),
            "featureMode": model.feature_mode, "scoreKind": model.score_kind,
            "cyclic": bool(model.cyclic), "adaptive": bool(model.adaptive),
            "cThr": int(model.c_thr), "quantile": float(model.q),
            "requiredFields": list(FIELDS), "trainingFeatureColumns": list(model.cols),
            "optionalFields": list(OPTIONAL_FIELDS),
            "description": entry.description, "status": "ready",
        }

    def list_models(self, station_id: str | None) -> list[dict]:
        items = []
        for entry in self.entries.values():
            if station_id and entry.stationId != station_id:
                continue
            try:
                _, model = self.resolve(entry.id, entry.version)
                item = self.metadata(entry, model)
            except ServiceError:
                item = {**entry.model_dump(exclude={"artifact"}), "status": "unavailable",
                        "requiredFields": list(FIELDS)}
            items.append(item)
        return items
