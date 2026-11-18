"""SQLite metadata and indexed samples; original CSV kept in managed files."""
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import ServiceError
from .schemas import OrganizationCreate, OrganizationUpdate, RegistryConfig, Station, StationCreate

SEEDS = {
    "enterprises": [
        {"id": "ent-1", "name": "北方热力有限责任公司", "code": "ENT-001"},
        {"id": "ent-2", "name": "城东热力分公司", "code": "ENT-002"}],
    "networks": [
        {"id": "net-1", "enterpriseId": "ent-1", "name": "城北主力供热网", "code": "NET-01"},
        {"id": "net-2", "enterpriseId": "ent-1", "name": "城西供热网", "code": "NET-02"},
        {"id": "net-3", "enterpriseId": "ent-2", "name": "高新片区热网", "code": "NET-03"}],
    "segments": [
        {"id": "seg-1", "networkId": "net-1", "name": "1号二次供热管段", "code": "ST-P01"},
        {"id": "seg-2", "networkId": "net-1", "name": "2号一次供热管段", "code": "ST-P02"},
        {"id": "seg-3", "networkId": "net-1", "name": "3号末端支路", "code": "ST-P03"},
        {"id": "seg-4", "networkId": "net-2", "name": "西区供热支线", "code": "ST-W01"},
        {"id": "seg-5", "networkId": "net-3", "name": "高新供热管段", "code": "ST-E01"}],
}


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.sources = self.directory / "sources"
        self.sources.mkdir(exist_ok=True)
        self.path = self.directory / "shad.sqlite3"
        with self.connection(write=True) as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 4:
                raise ValueError("本地数据库版本高于当前服务，不能降级打开")
            if version == 0:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                    CREATE TABLE enterprises(id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE COLLATE NOCASE);
                    CREATE TABLE networks(id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL COLLATE NOCASE,
                        enterpriseId TEXT NOT NULL REFERENCES enterprises(id), UNIQUE(enterpriseId,code));
                    CREATE TABLE segments(id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL COLLATE NOCASE,
                        networkId TEXT NOT NULL REFERENCES networks(id), UNIQUE(networkId,code));
                    CREATE TABLE stations(id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL COLLATE NOCASE,
                        enterpriseId TEXT NOT NULL REFERENCES enterprises(id), networkId TEXT NOT NULL REFERENCES networks(id),
                        segmentId TEXT NOT NULL REFERENCES segments(id), timezone TEXT NOT NULL, UNIQUE(enterpriseId,code));
                    CREATE INDEX stations_segment ON stations(segmentId);
                    CREATE TABLE models(id TEXT NOT NULL, version TEXT NOT NULL, stationId TEXT NOT NULL REFERENCES stations(id),
                        registration TEXT NOT NULL, PRIMARY KEY(id,version));
                    CREATE TABLE datasets(id TEXT PRIMARY KEY, stationId TEXT NOT NULL REFERENCES stations(id),
                        created_at TEXT NOT NULL, metadata TEXT NOT NULL, source_file TEXT NOT NULL UNIQUE);
                    CREATE INDEX datasets_station ON datasets(stationId,created_at DESC);
                    CREATE TABLE dataset_samples(dataset_id TEXT NOT NULL REFERENCES datasets(id), position INTEGER NOT NULL,
                        time_us INTEGER NOT NULL, timestamp TEXT NOT NULL, values_json TEXT NOT NULL, quality_json TEXT NOT NULL,
                        PRIMARY KEY(dataset_id,position), UNIQUE(dataset_id,time_us));
                    CREATE INDEX samples_time ON dataset_samples(dataset_id,time_us);
                    INSERT INTO schema_migrations VALUES(1,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
                    PRAGMA user_version=1;
                    COMMIT;
                """)
            if version < 2:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE detections(id TEXT PRIMARY KEY, station_id TEXT NOT NULL REFERENCES stations(id),
                        segment_id TEXT NOT NULL REFERENCES segments(id), dataset_id TEXT NOT NULL REFERENCES datasets(id),
                        model_id TEXT NOT NULL, model_version TEXT NOT NULL, status TEXT NOT NULL,
                        created_at TEXT NOT NULL, task_json TEXT NOT NULL, input_json TEXT NOT NULL,
                        FOREIGN KEY(model_id,model_version) REFERENCES models(id,version));
                    CREATE INDEX detections_history ON detections(segment_id,created_at DESC,id DESC);
                    CREATE INDEX detections_queue ON detections(status,created_at,id);
                    CREATE TABLE idempotency_keys(operation TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
                        detection_id TEXT NOT NULL REFERENCES detections(id), PRIMARY KEY(operation,key));
                    CREATE TABLE detection_results(detection_id TEXT PRIMARY KEY REFERENCES detections(id), payload TEXT NOT NULL);
                    CREATE TABLE detection_points(detection_id TEXT NOT NULL REFERENCES detections(id), position INTEGER NOT NULL,
                        time_us INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(detection_id,position));
                    CREATE INDEX detection_points_time ON detection_points(detection_id,time_us);
                    CREATE TABLE detection_events(id TEXT PRIMARY KEY, detection_id TEXT NOT NULL REFERENCES detections(id),
                        start_us INTEGER NOT NULL, end_us INTEGER NOT NULL, payload TEXT NOT NULL);
                    CREATE INDEX detection_events_time ON detection_events(detection_id,start_us,id);
                    INSERT INTO schema_migrations VALUES(2,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
                    PRAGMA user_version=2;
                    COMMIT;
                """)
            if version < 3:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE reports(id TEXT PRIMARY KEY, series_id TEXT NOT NULL, version INTEGER NOT NULL,
                        detection_id TEXT NOT NULL REFERENCES detections(id), created_at TEXT NOT NULL,
                        archived_at TEXT, report_json TEXT NOT NULL, UNIQUE(series_id,version));
                    CREATE INDEX reports_history ON reports(created_at DESC,id DESC);
                    CREATE INDEX reports_source ON reports(detection_id,created_at DESC,id DESC);
                    CREATE TABLE report_submissions(operation TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
                        report_id TEXT NOT NULL REFERENCES reports(id), PRIMARY KEY(operation,key));
                    INSERT INTO schema_migrations VALUES(3,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
                    PRAGMA user_version=3;
                    COMMIT;
                """)
            if version < 4:
                for kind in SEEDS:
                    columns = {r[1] for r in db.execute(f"PRAGMA table_info({kind})")}
                    if 'active' not in columns:
                        db.execute(f"ALTER TABLE {kind} ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))")
                    if 'revision' not in columns:
                        db.execute(f"ALTER TABLE {kind} ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
                db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(4,?)", (now(),))
                db.execute("PRAGMA user_version=4")
            for kind, rows in SEEDS.items():
                for row in rows:
                    if not db.execute(f"SELECT 1 FROM {kind} WHERE id=?", (row["id"],)).fetchone():
                        self._insert_org(db, kind, row)
        self._clean_orphans()

    @contextmanager
    def connection(self, write=False):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=5000")
            yield db
            db.commit()
        except (sqlite3.Error, OSError) as exc:
            if db:
                db.rollback()
            raise ServiceError("STORAGE_WRITE_FAILED" if write else "STORAGE_UNAVAILABLE",
                               "本地存储读写失败，请检查目录权限、磁盘空间及服务日志。", 500 if write else 503, True) from exc
        except BaseException:
            if db:
                db.rollback()
            raise
        finally:
            if db:
                db.close()

    @staticmethod
    def _insert_org(db, kind, row):
        # kind is chosen exclusively from server-owned constants.
        fields = {"enterprises": ("id", "name", "code"),
                  "networks": ("id", "name", "code", "enterpriseId"),
                  "segments": ("id", "name", "code", "networkId")}[kind]
        db.execute(f"INSERT INTO {kind}({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                   [row[f] for f in fields])

    @staticmethod
    def _check_station_path(db, station):
        found = db.execute("""SELECT 1 FROM segments s JOIN networks n ON n.id=s.networkId
                              WHERE s.id=? AND n.id=? AND n.enterpriseId=?""",
                           (station["segmentId"], station["networkId"], station["enterpriseId"])).fetchone()
        if not found:
            raise ServiceError("SOURCE_MISMATCH", "企业、管网和管段未登记或所属关系不一致，请先登记组织。")

    def organizations(self):
        with self.connection() as db:
            return {kind: [{**dict(row), "active": bool(row["active"])} for row in db.execute(f"SELECT * FROM {kind} ORDER BY rowid")]
                    for kind in SEEDS}

    def create_organization(self, kind: str, body: OrganizationCreate):
        row = {"id": uuid4().hex, "name": body.name, "code": body.code}
        parent = {"enterprises": None, "networks": "enterpriseId", "segments": "networkId"}[kind]
        if (parent is None and (body.enterpriseId or body.networkId)) or \
                (parent == "enterpriseId" and (not body.enterpriseId or body.networkId)) or \
                (parent == "networkId" and (not body.networkId or body.enterpriseId)):
            raise ServiceError("INVALID_REQUEST", "组织层级参数不正确。")
        if parent:
            row[parent] = getattr(body, parent)
        with self.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            if parent:
                table = 'enterprises' if parent == 'enterpriseId' else 'networks'
                owner = db.execute(f'SELECT * FROM {table} WHERE id=?', (row[parent],)).fetchone()
                if owner and (not owner['active'] or (table == 'networks' and not db.execute('SELECT active FROM enterprises WHERE id=?', (owner['enterpriseId'],)).fetchone()[0])):
                    raise ServiceError('ORGANIZATION_INACTIVE', '上级组织已停用，请先启用。', 409)
            try:
                self._insert_org(db, kind, row)
            except sqlite3.IntegrityError as exc:
                raise ServiceError("ORGANIZATION_CONFLICT", "上级组织不存在，或同一上级的组织编码已存在。", 409) from exc
        return {**row, "active": True, "revision": 1}

    def require_active_path(self, station):
        with self.connection() as db:
            self._check_station_path(db, station)
            for kind, key in [('enterprises', 'enterpriseId'), ('networks', 'networkId'), ('segments', 'segmentId')]:
                if not db.execute(f"SELECT active FROM {kind} WHERE id=?", (station[key],)).fetchone()[0]:
                    raise ServiceError('ORGANIZATION_INACTIVE', '当前企业、管网或管段已停用，请启用后再创建业务。', 409)

    def update_organization(self, kind: str, identifier: str, body: OrganizationUpdate):
        with self.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute(f"SELECT * FROM {kind} WHERE id=?", (identifier,)).fetchone()
            if not old:
                raise ServiceError('NOT_FOUND', '组织对象不存在。', 404)
            if old['revision'] != body.expectedRevision:
                raise ServiceError('REVISION_CONFLICT', '记录已被其他窗口修改，请刷新后核对并重新保存。', 409)
            try:
                db.execute(f"UPDATE {kind} SET name=?,code=?,active=?,revision=revision+1 WHERE id=?",
                           (body.name, body.code, int(body.active), identifier))
            except sqlite3.IntegrityError as exc:
                raise ServiceError('ORGANIZATION_CONFLICT', '同一上级的组织编码已存在。', 409) from exc
            row = dict(db.execute(f"SELECT * FROM {kind} WHERE id=?", (identifier,)).fetchone())
            return {**row, 'active': bool(row['active'])}

    def stations(self, segment_id=None):
        with self.connection() as db:
            query = "SELECT * FROM stations" + (" WHERE segmentId=?" if segment_id else "") + " ORDER BY rowid"
            return [dict(s) for s in db.execute(query, (segment_id,) if segment_id else ())]

    def station(self, station_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
            if not row:
                raise ServiceError("NOT_FOUND", "换热站不存在，请先登记本站对象。", 404)
            return dict(row)

    def create_station(self, body: StationCreate):
        station = Station(id=uuid4().hex, **body.model_dump()).model_dump()
        self.require_active_path(station)
        with self.connection(write=True) as db:
            self._check_station_path(db, station)
            try:
                db.execute("INSERT INTO stations VALUES(?,?,?,?,?,?,?)", tuple(station.values()))
            except sqlite3.IntegrityError as exc:
                raise ServiceError("STATION_CODE_CONFLICT", "同一企业的换热站编码已存在。", 409) from exc
        return station

    def register(self, config: RegistryConfig):
        """Trusted administrator manifest, additive and immutable by model version."""
        with self.connection(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            for kind in SEEDS:
                for row in config.organizations.get(kind, []):
                    existing = db.execute(f"SELECT * FROM {kind} WHERE id=?", (row["id"],)).fetchone()
                    if existing:
                        if any(existing[k] != row[k] for k in ("enterpriseId", "networkId") if k in existing.keys()):
                            raise ValueError("注册表与现有组织记录不一致")
                    else:
                        self._insert_org(db, kind, row)
            for station in config.stations:
                row = station.model_dump()
                self._check_station_path(db, row)
                old = db.execute("SELECT * FROM stations WHERE id=?", (station.id,)).fetchone()
                if old and dict(old) != row:
                    raise ValueError("注册表不能覆盖现有站点或时区")
                if not old:
                    db.execute("INSERT INTO stations VALUES(?,?,?,?,?,?,?)", tuple(row.values()))
            for model in config.models:
                payload = model.model_dump()
                old = db.execute("SELECT registration FROM models WHERE id=? AND version=?", (model.id, model.version)).fetchone()
                if old and json.loads(old[0]) != payload:
                    raise ValueError("模型同版本登记不可覆盖，请分配新版本")
                if not old:
                    db.execute("INSERT INTO models VALUES(?,?,?,?)", (model.id, model.version, model.stationId, json_text(payload)))

    def registry_config(self):
        with self.connection() as db:
            return RegistryConfig(stations=[Station(**dict(s)) for s in db.execute("SELECT * FROM stations")],
                                  models=[json.loads(row[0]) for row in db.execute("SELECT registration FROM models")])

    def save_dataset(self, metadata, samples, raw: bytes):
        dataset_id = metadata["id"]
        target = (self.sources / f"{dataset_id}.csv").resolve()
        if target.parent != self.sources.resolve() or not dataset_id.isalnum():
            raise ValueError("Invalid managed dataset id")
        created = False
        try:
            with self.connection(write=True) as db:
                db.execute("BEGIN IMMEDIATE")
                # Only clean up files created by this operation if the transaction fails.
                with target.open("xb") as output:
                    created = True
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                db.execute("INSERT INTO datasets VALUES(?,?,?,?,?)", (dataset_id, metadata["stationId"], metadata["createdAt"],
                           json_text(metadata), target.name))
                db.executemany("INSERT INTO dataset_samples VALUES(?,?,?,?,?,?)", [
                    (dataset_id, i, sample["time_us"], sample["timestamp"], json_text(sample["values"]), json_text(sample["quality"]))
                    for i, sample in enumerate(samples)])
        except BaseException as exc:
            if created:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    # Preserve the original storage failure; startup cleanup can retry later.
                    logging.getLogger('shad').warning('Failed to remove an uncommitted import source')
            if isinstance(exc, OSError):
                raise ServiceError("STORAGE_WRITE_FAILED", "原始数据保存失败，请检查本地目录和磁盘空间。", 500, True) from exc
            raise
        return metadata

    def _clean_orphans(self):
        # Only server-named, unreferenced CSVs older than a day. No recursive delete,
        # symlink traversal, or removal of files that an active import just created.
        with self.connection() as db:
            referenced = {row[0] for row in db.execute("SELECT source_file FROM datasets")}
        for path in self.sources.iterdir():
            if path.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}\.csv", path.name) or path.name in referenced:
                continue
            if path.is_file() and path.stat().st_mtime < time.time() - 86400:
                path.unlink()

    def dataset(self, dataset_id):
        with self.connection() as db:
            row = db.execute("SELECT metadata FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            if not row:
                raise ServiceError("NOT_FOUND", "数据集不存在。", 404)
            return json.loads(row[0])

    def datasets(self, station_id, page, size):
        with self.connection() as db:
            where, args = (" WHERE stationId=?", [station_id]) if station_id else ("", [])
            total = db.execute("SELECT count(*) FROM datasets" + where, args).fetchone()[0]
            rows = db.execute("SELECT metadata FROM datasets" + where + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                              [*args, size, (page - 1) * size])
            return {"items": [json.loads(r[0]) for r in rows], "page": page, "pageSize": size, "total": total}

    def samples(self, dataset_id, start_us, end_us, fields, page, size):
        self.dataset(dataset_id)
        terms, args = ["dataset_id=?"], [dataset_id]
        if start_us is not None:
            terms.append("time_us>=?"); args.append(start_us)
        if end_us is not None:
            terms.append("time_us<=?"); args.append(end_us)
        where = " AND ".join(terms)
        with self.connection() as db:
            total = db.execute("SELECT count(*) FROM dataset_samples WHERE " + where, args).fetchone()[0]
            rows = db.execute("SELECT timestamp,values_json,quality_json FROM dataset_samples WHERE " + where +
                              " ORDER BY time_us LIMIT ? OFFSET ?", [*args, size, (page - 1) * size])
            items = []
            for row in rows:
                values, quality = json.loads(row[1]), json.loads(row[2])
                selected = fields if fields is not None else values.keys()
                items.append({"timestamp": row[0], "values": {f: values.get(f) for f in selected},
                              "quality": {f: quality.get(f, "missing") for f in selected}})
            return {"items": items, "page": page, "pageSize": size, "total": total}
