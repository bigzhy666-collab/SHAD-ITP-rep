"""Offline, verified data backups. Restore publishes a new directory only."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from pydantic import Field

from . import SERVICE_VERSION
from .desktop import default_data_dir
from .locking import DataDirectoryLease
from .registry import ROOT, ModelRegistry
from .schemas import ModelRegistration, RegistryConfig, Station, StrictModel

MAX_TOTAL = 4 * 1024**3
MAX_FILE = 2 * 1024**3
MAX_FILES = 100001
MAX_MANIFEST = 16 * 1024**2
TABLES = ('enterprises', 'networks', 'segments', 'stations', 'models', 'datasets', 'dataset_samples',
          'detections', 'idempotency_keys', 'detection_results', 'detection_points', 'detection_events',
          'reports', 'report_submissions', 'schema_migrations')
SHA = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


class BackupFile(StrictModel):
    path: str
    size: Annotated[int, Field(ge=0, le=MAX_FILE)]
    sha256: SHA


class BackupManifest(StrictModel):
    format: Literal['shad-local-backup']
    formatVersion: Literal[1]
    serviceVersion: str
    schemaVersion: Annotated[int, Field(ge=1, le=4)]
    createdAt: str
    files: Annotated[list[BackupFile], Field(min_length=1, max_length=MAX_FILES)]
    models: list[ModelRegistration]


def file_hash(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


@contextmanager
def staging(parent, prefix):
    parent = parent.resolve()
    with tempfile.TemporaryDirectory(prefix=prefix, dir=parent) as raw:
        path = Path(raw).resolve()
        # Every recursive temporary cleanup is confined to this explicit parent.
        if path.parent != parent or not path.name.startswith(prefix):
            raise RuntimeError('临时目录超出预期范围。')
        yield path


def database_info(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        schema = db.execute('PRAGMA user_version').fetchone()[0]
        if schema not in (3, 4):
            raise ValueError('备份需要受支持的 schema 3/4 数据库；旧数据请先使用当前服务完成升级，高版本不能降级打开。')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('数据库完整性或关联关系校验失败。')
        actual = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(TABLES).issubset(actual):
            raise ValueError('数据库业务表不完整。')
        sources = {}
        for name, metadata in db.execute('SELECT source_file,metadata FROM datasets'):
            if not re.fullmatch(r'[a-f0-9]{32}\.csv', name):
                raise ValueError('数据库引用了不受管理的原文件名。')
            checksum = json.loads(metadata)['sourceChecksum']
            if not re.fullmatch(r'[a-f0-9]{64}', checksum):
                raise ValueError('原文件校验值格式错误。')
            sources[name] = checksum
        models = []
        for model_id, version, station_id, raw in db.execute('SELECT id,version,stationId,registration FROM models'):
            model = ModelRegistration.model_validate_json(raw)
            if (model.id, model.version, model.stationId) != (model_id, version, station_id):
                raise ValueError('数据库模型登记不一致。')
            models.append(model)
        db.row_factory = sqlite3.Row
        config = RegistryConfig(models=models, stations=[Station(**dict(s)) for s in db.execute('SELECT * FROM stations')])
        counts = {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in TABLES}
    return {'schema': schema, 'sources': sources, 'config': config, 'counts': counts}


def check_models(info, model_dir):
    # Verify trusted installed artifacts, without unpickling or importing code from a backup.
    registry = ModelRegistry(config=info['config'], artifact_root=model_dir)
    for model in registry.entries.values():
        registry._path(model)


def backup(directory, output, model_dir=None):
    if output.is_symlink():
        raise ValueError('备份目标已存在链接，请选择新文件名。')
    directory, output = directory.resolve(), output.resolve()
    if output.exists():
        raise ValueError('备份目标已存在，请选择新文件名，不覆盖旧备份。')
    if output.is_relative_to(directory):
        raise ValueError('备份请保存到原数据目录之外，避免与运行数据混放。')
    if not (directory / 'shad.sqlite3').is_file():
        raise ValueError('此目录没有 SHAD 数据库，请核对当前软件数据目录。')
    output.parent.mkdir(parents=True, exist_ok=True)
    with DataDirectoryLease(directory), staging(output.parent, '.shad-backup-') as work:
        source = directory / 'shad.sqlite3'
        if source.is_symlink() or source.resolve().parent != directory:
            raise ValueError('数据库不在预期目录。')
        snapshot = work / 'shad.sqlite3'
        # SQLite backup includes committed WAL contents; never copy only the live main file.
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(snapshot)) as target:
            original.backup(target)
            target.execute('PRAGMA journal_mode=DELETE')
        info = database_info(snapshot)
        check_models(info, model_dir)
        sources = directory / 'sources'
        if sources.is_symlink() or sources.resolve().parent != directory:
            raise ValueError('原文件目录不在预期位置。')
        (work / 'sources').mkdir()
        for name, checksum in info['sources'].items():
            original = sources / name
            if original.is_symlink() or original.resolve().parent != sources.resolve() or not original.is_file():
                raise ValueError('数据库引用的原文件缺失或位置异常：' + name)
            if original.stat().st_size > MAX_FILE:
                raise ValueError('原文件超过备份大小限制。')
            shutil.copyfile(original, work / 'sources' / name)
            if file_hash(work / 'sources' / name) != checksum:
                raise ValueError('原文件与导入时校验值不符：' + name)
        files = [BackupFile(path=p.relative_to(work).as_posix(), size=p.stat().st_size, sha256=file_hash(p))
                 for p in [snapshot, *sorted((work / 'sources').iterdir())]]
        if sum(f.size for f in files) > MAX_TOTAL:
            raise ValueError('备份内容超过 4 GiB，请联系维护人员拆分数据。')
        manifest = BackupManifest(format='shad-local-backup', formatVersion=1, serviceVersion=SERVICE_VERSION,
                                  schemaVersion=info['schema'], createdAt=datetime.now(timezone.utc).isoformat(),
                                  files=files, models=info['config'].models)
        raw_manifest = manifest.model_dump_json(indent=2).encode('utf-8')
        if len(raw_manifest) > MAX_MANIFEST:
            raise ValueError('备份清单超过大小限制。')
        archive = work / 'pending.zip'
        with ZipFile(archive, 'x', compression=ZIP_DEFLATED, compresslevel=6) as zipped:
            zipped.writestr('manifest.json', raw_manifest)
            for item in files:
                zipped.write(work / item.path, item.path)
        with archive.open('rb+') as complete:
            os.fsync(complete.fileno())
        # Publish only a complete ZIP; neither Windows rename nor POSIX link replaces an existing file.
        if os.name == 'nt':
            os.rename(archive, output)
        else:
            os.link(archive, output)
        return {'backup': str(output), 'schemaVersion': info['schema'], 'files': len(files), 'counts': info['counts'],
                'modelsIncluded': False, 'sha256': file_hash(output)}


def read_manifest(zipped):
    entries = zipped.infolist()
    if len(entries) > MAX_FILES + 1 or len({e.filename for e in entries}) != len(entries):
        raise ValueError('备份条目过多或存在重复文件。')
    for entry in entries:
        mode = entry.external_attr >> 16
        if (entry.is_dir() or entry.flag_bits & 1 or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or entry.file_size > MAX_FILE):
            raise ValueError('备份包含目录、链接、加密或超限条目。')
    names = {e.filename for e in entries}
    if 'manifest.json' not in names or zipped.getinfo('manifest.json').file_size > MAX_MANIFEST:
        raise ValueError('缺少备份清单或清单过大。')
    manifest = BackupManifest.model_validate_json(zipped.read('manifest.json'))
    expected = [item.path for item in manifest.files]
    if len(set(expected)) != len(expected) or set(expected) | {'manifest.json'} != names or 'shad.sqlite3' not in expected:
        raise ValueError('备份文件与清单不符。')
    for item in manifest.files:
        if item.path != 'shad.sqlite3' and not re.fullmatch(r'sources/[a-f0-9]{32}\.csv', item.path):
            raise ValueError('备份包含不允许的文件路径。')
        if zipped.getinfo(item.path).file_size != item.size:
            raise ValueError('备份文件大小与清单不符。')
    if sum(f.size for f in manifest.files) > MAX_TOTAL:
        raise ValueError('备份展开后超过 4 GiB。')
    return manifest


def restore(archive, directory, model_dir=None):
    if directory.is_symlink():
        raise ValueError('恢复目标必须是新目录，不能使用已有链接。')
    archive, directory = archive.resolve(), directory.resolve()
    if directory.exists():
        raise ValueError('恢复目标必须是新目录；不会覆盖当前数据库或已有文件。')
    if not archive.is_file() or archive.stat().st_size > MAX_TOTAL + MAX_MANIFEST:
        raise ValueError('备份文件不存在或超过大小限制。')
    directory.parent.mkdir(parents=True, exist_ok=True)
    with staging(directory.parent, '.shad-restore-') as work:
        with ZipFile(archive) as zipped:
            manifest = read_manifest(zipped)
            (work / 'sources').mkdir()
            for item in manifest.files:
                target = work / item.path
                if not target.resolve().is_relative_to(work):
                    raise ValueError('恢复文件路径越界。')
                digest, size = hashlib.sha256(), 0
                with zipped.open(item.path) as source, target.open('xb') as output:
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > item.size:
                            raise ValueError('恢复文件实际长度超出清单。')
                        digest.update(chunk); output.write(chunk)
                    output.flush(); os.fsync(output.fileno())
                if size != item.size or digest.hexdigest() != item.sha256:
                    raise ValueError('备份校验失败：' + item.path)
        info = database_info(work / 'shad.sqlite3')
        model_values = lambda values: sorted((m.model_dump() for m in values), key=lambda m: (m['id'], m['version']))
        if info['schema'] != manifest.schemaVersion or model_values(info['config'].models) != model_values(manifest.models):
            raise ValueError('数据库版本或模型登记与备份清单不符。')
        expected = {'shad.sqlite3', *('sources/' + name for name in info['sources'])}
        if expected != {item.path for item in manifest.files}:
            raise ValueError('数据库引用的原文件与清单不一致。')
        for name, checksum in info['sources'].items():
            if file_hash(work / 'sources' / name) != checksum:
                raise ValueError('原文件与数据库记录的校验值不符：' + name)
        check_models(info, model_dir)
        # Both absolute paths stay in the explicit target parent; never move/delete existing data.
        if work.resolve().parent != directory.parent.resolve() or directory.exists():
            raise ValueError('恢复目标发生变化，已停止发布。')
        os.rename(work, directory)
        return {'dataDir': str(directory), 'schemaVersion': info['schema'], 'files': len(manifest.files),
                'counts': info['counts'], 'modelsVerified': len(info['config'].models)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='SHAD 停止服务后的本地数据备份与恢复')
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('backup', help='备份到新 ZIP 文件；请先停止服务')
    make.add_argument('--data-dir', type=Path, default=default_data_dir())
    make.add_argument('--output', type=Path, help='新备份文件；默认位于数据目录旁的 backups 文件夹')
    make.add_argument('--model-dir', type=Path)
    make.add_argument('--human', action='store_true')
    load = sub.add_parser('restore', help='校验并恢复到不存在的新目录')
    load.add_argument('--archive', type=Path, required=True)
    load.add_argument('--data-dir', type=Path, required=True)
    load.add_argument('--model-dir', type=Path)
    load.add_argument('--human', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'backup' and args.output is None:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
            args.output = args.data_dir.resolve().parent / 'backups' / ('SHAD-' + stamp + '.shad-backup.zip')
        value = backup(args.data_dir, args.output, args.model_dir) if args.action == 'backup' else restore(
            args.archive, args.data_dir, args.model_dir)
        if args.human:
            print('SHAD 备份已完成：' + value['backup'] if args.action == 'backup' else 'SHAD 已恢复到新目录：' + value['dataDir'])
            print('已校验数据库、原始文件和模型登记。')
        else:
            print(json.dumps(value, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, BadZipFile, KeyError) as exc:
        print(f'SHAD 数据维护失败：{exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
