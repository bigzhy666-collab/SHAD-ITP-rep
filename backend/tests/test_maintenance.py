import hashlib
import json
import sqlite3
import stat
from contextlib import closing
from zipfile import ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.maintenance import backup, file_hash, restore, main as maintenance_main
from backend.tests.test_detection_service import client, upload
from backend.tests.test_reports import create, detection, version


@pytest.fixture
def saved_archive(client, tmp_path):
    upload(client)
    client.app.state.worker.close()
    output = tmp_path / '本地备份.shad-backup.zip'
    backup(client.app.state.store.directory, output)
    return output


def changed_zip(source, target, edit):
    with ZipFile(source) as original:
        entries = {item.filename: original.read(item) for item in original.infolist()}
    manifest = json.loads(entries.pop('manifest.json'))
    edit(manifest, entries)
    with ZipFile(target, 'w') as output:
        output.writestr('manifest.json', json.dumps(manifest))
        for name, content in entries.items():
            output.writestr(name, content)
    return target


def test_roundtrip_preserves_reports_versions_notes_sources_and_all_results(client, tmp_path):
    config = detection(client)
    report = create(client, config).json()['data']
    note = client.patch(f"/api/reports/{report['id']}/note", json={'note': '恢复后仍需保留的中文备注', 'expectedRevision': 1}).json()['data']
    archived = client.post(f"/api/reports/{report['id']}/archive", json={'expectedRevision': note['revision']}).json()['data']
    next_version = version(client, archived).json()['data']
    store = client.app.state.store
    client.app.state.worker.close()
    output = tmp_path / '完整业务.shad-backup.zip'
    result = backup(store.directory, output)
    assert not result['modelsIncluded'] and result['counts']['reports'] == 2
    restored = tmp_path / '中文路径 空格/恢复数据'
    restored_result = restore(output, restored)
    assert restored_result['modelsVerified'] == 1 and restored_result['counts'] == result['counts']
    assert not (restored / 'desktop-runtime.json').exists() and not (restored / 'logs').exists()
    with TestClient(create_app(data_dir=restored), base_url='http://127.0.0.1') as recovered:
        for before in (archived, next_version):
            assert recovered.get('/api/reports/' + before['id']).json()['data'] == before
        assert create(recovered, config).json()['data'] == archived
        assert version(recovered, archived).json()['data'] == next_version
        assert recovered.get('/api/detections/' + config['detectionId'] + '/points?pageSize=500').json()['data']['total'] == 60
        assert recovered.get('/api/reports').json()['data']['total'] == 2
    for path in (store.directory / 'sources').iterdir():
        assert file_hash(restored / 'sources' / path.name) == file_hash(path)
    assert client.get('/api/reports/' + report['id']).json()['data'] == archived


def test_running_service_blocks_offline_backup(client, tmp_path):
    with pytest.raises(RuntimeError, match='正在使用'):
        backup(client.app.state.store.directory, tmp_path / '不能保存.zip')
    assert not (tmp_path / '不能保存.zip').exists()


def test_committed_wal_data_is_included(client, tmp_path):
    client.app.state.worker.close()
    store = client.app.state.store
    with closing(sqlite3.connect(store.path)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("INSERT INTO enterprises(id,name,code) VALUES('wal-test','已提交 WAL 企业','WAL-TEST')")
        writer.commit()
        assert store.path.with_name('shad.sqlite3-wal').stat().st_size > 0
        output = tmp_path / '含WAL.zip'
        backup(store.directory, output)
    target = tmp_path / '恢复WAL'
    restore(output, target)
    with closing(sqlite3.connect(target / 'shad.sqlite3')) as db:
        assert db.execute("SELECT name FROM enterprises WHERE id='wal-test'").fetchone()[0] == '已提交 WAL 企业'


def test_existing_archive_or_restore_directory_never_overwritten(saved_archive, tmp_path, client):
    previous = saved_archive.read_bytes()
    with pytest.raises(ValueError, match='已存在'):
        backup(client.app.state.store.directory, saved_archive)
    assert saved_archive.read_bytes() == previous
    target = tmp_path / '已有数据'; target.mkdir()
    keep = target / '不能删除.txt'; keep.write_text('原文件', encoding='utf-8')
    with pytest.raises(ValueError, match='新目录'):
        restore(saved_archive, target)
    assert keep.read_text(encoding='utf-8') == '原文件'
    with pytest.raises(ValueError, match='目录之外'):
        backup(client.app.state.store.directory, client.app.state.store.directory / '混放.zip')


@pytest.mark.parametrize('bad_name', ['../outside.txt', '/outside.txt', 'C:/outside.txt', 'sources/../outside.csv',
                                     'sources\\outside.csv', 'model.pkl', 'desktop-runtime.json', 'sources/ABC.csv'])
def test_archive_path_traversal_and_extra_executables_rejected(saved_archive, tmp_path, bad_name):
    def edit(manifest, entries):
        content = b'bad-path'
        entries[bad_name] = content
        manifest['files'].append({'path': bad_name, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    modified = changed_zip(saved_archive, tmp_path / '异常路径.zip', edit)
    target = tmp_path / '拒绝恢复'
    with pytest.raises(ValueError):
        restore(modified, target)
    assert not target.exists() and not (tmp_path / 'outside.txt').exists()


def test_tampered_bytes_and_database_source_hash_are_both_checked(saved_archive, tmp_path):
    def tamper(manifest, entries):
        item = next(f for f in manifest['files'] if f['path'].startswith('sources/'))
        entries[item['path']] = b'changed'
        item['size'] = len(entries[item['path']])
    modified = changed_zip(saved_archive, tmp_path / '校验失败.zip', tamper)
    target = tmp_path / '校验未通过'
    with pytest.raises(ValueError, match='校验失败'):
        restore(modified, target)
    assert not target.exists()
    def update_manifest_hash(manifest, entries):
        for item in manifest['files']:
            item['sha256'] = hashlib.sha256(entries[item['path']]).hexdigest()
    modified2 = changed_zip(modified, tmp_path / '数据库不符.zip', update_manifest_hash)
    with pytest.raises(ValueError, match='数据库记录'):
        restore(modified2, target)
    assert not target.exists()


def test_missing_or_modified_original_csv_prevents_backup(client, tmp_path):
    upload(client)
    client.app.state.worker.close()
    store = client.app.state.store
    original = next(store.sources.iterdir())
    original.write_bytes(b'changed')
    output = tmp_path / '不能备份.zip'
    with pytest.raises(ValueError, match='校验值'):
        backup(store.directory, output)
    assert not output.exists()
    original.unlink()
    with pytest.raises(ValueError, match='缺失'):
        backup(store.directory, output)
    assert not output.exists()


def test_missing_trusted_model_blocks_restore_without_loading_backup_code(saved_archive, tmp_path):
    model_dir = tmp_path / '空模型目录'; model_dir.mkdir()
    target = tmp_path / '不能启动的恢复'
    with pytest.raises(OSError):
        restore(saved_archive, target, model_dir)
    assert not target.exists()


def test_duplicate_entries_and_symbolic_links_rejected(saved_archive, tmp_path):
    duplicate = tmp_path / '重复条目.zip'
    duplicate.write_bytes(saved_archive.read_bytes())
    with pytest.warns(UserWarning, match='Duplicate'):
        with ZipFile(duplicate, 'a') as zipped:
            zipped.writestr('shad.sqlite3', b'not a database')
    with pytest.raises(ValueError, match='重复文件'):
        restore(duplicate, tmp_path / '重复恢复')
    linked = tmp_path / '链接.zip'
    linked.write_bytes(saved_archive.read_bytes())
    with ZipFile(linked, 'a') as zipped:
        entry = ZipInfo('sources/link.csv')
        entry.create_system = 3; entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(entry, '../outside')
    with pytest.raises(ValueError, match='链接'):
        restore(linked, tmp_path / '链接恢复')


def test_restore_failure_does_not_publish_partial_directory(saved_archive, tmp_path, monkeypatch):
    def fail(*args):
        raise OSError('模拟发布失败')
    monkeypatch.setattr('backend.maintenance.os.rename', fail)
    target = tmp_path / '发布失败'
    with pytest.raises(OSError, match='发布失败'):
        restore(saved_archive, target)
    assert not target.exists() and not list(tmp_path.glob('.shad-restore-*'))


def test_oversized_or_future_manifest_rejected(saved_archive, tmp_path, monkeypatch):
    modified = changed_zip(saved_archive, tmp_path / '未来版本.zip', lambda manifest, entries: manifest.update(schemaVersion=99))
    with pytest.raises(ValueError):
        restore(modified, tmp_path / '版本越界')
    monkeypatch.setattr('backend.maintenance.MAX_TOTAL', 1)
    with pytest.raises(ValueError, match='超过|大小限制'):
        restore(saved_archive, tmp_path / '大小越界')


def test_backup_shortcut_generates_new_filename_outside_data_directory(saved_archive, client, capsys):
    directory = client.app.state.store.directory
    assert maintenance_main(['backup', '--data-dir', str(directory), '--human']) == 0
    assert '备份已完成' in capsys.readouterr().out
    generated = list((directory.parent / 'backups').glob('*.shad-backup.zip'))
    assert len(generated) == 1 and not generated[0].is_relative_to(directory)
