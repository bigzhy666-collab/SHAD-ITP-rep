"""Actual background launcher, authenticated stop, backup and restored startup."""
import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import httpx

from backend.desktop import control_record, status, stop
from backend.registry import ROOT
from backend.tests.temp_data import isolated_data
from backend.tests.test_reports import create, detection, version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--exe', type=Path, help='验证已打包程序，替代 Python 服务进程')
    args = parser.parse_args()
    with socket.socket() as free:
        free.bind(('127.0.0.1', 0)); port = free.getsockname()[1]
    def cli(module, *args, expected=0):
        command = [str(parsed_exe), '--json', *map(str, args)] if parsed_exe else [sys.executable, '-m', module, *map(str, args)]
        environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        if parsed_exe:
            environment.pop('PYTHONPATH', None)
            environment.pop('PYTHONHOME', None)
            environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
        result = subprocess.run(command, cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90,
                                env=environment)
        assert result.returncode == expected, result.stderr or result.stdout
        return json.loads(result.stdout) if expected == 0 else result.stderr

    parsed_exe = args.exe.resolve() if args.exe else None
    with isolated_data() as temporary:
        root = Path(temporary)
        original = root / '中文原数据 空格'
        restored = root / '恢复后的数据 空格'
        backup_file = root / '完整业务.shad-backup.zip'
        try:
            started = cli('backend.desktop', 'start', '--data-dir', original, '--port', port,
                          '--registry', (parsed_exe.parent / 'examples/registry.example.json' if parsed_exe else ROOT / 'backend/config/registry.example.json'), '--no-browser')
            assert started['running'] and not started['reused']
            reused = cli('backend.desktop', 'start', '--data-dir', original, '--port', port, '--no-browser')
            assert reused['reused'] and reused['instanceId'] == started['instanceId']
            url = started['url']
            with httpx.Client(base_url=url, trust_env=False, timeout=15) as client:
                runtime = client.get('/api/runtime').json()['data']
                assert runtime['desktop']['managed'] and runtime['desktop']['instanceId'] == started['instanceId']
                assert client.get('/overview?service=local', headers={'Accept': 'text/html'}).status_code == 200
                assert client.post('/api/desktop/stop', json={}).status_code == 403
                token = control_record(original)['token']
                assert token not in json.dumps(runtime)
                assert client.post('/api/desktop/stop', json={}, headers={'X-SHAD-Control': token, 'Origin': 'http://outside.example'}).status_code == 403
                config = detection(client)
                first = create(client, config).json()['data']
                path = '/api/reports/' + first['id']
                noted = client.patch(path + '/note', json={'note': '备份恢复验收备注；合成输入和示例模型。', 'expectedRevision': 1}).json()['data']
                archived = client.post(path + '/archive', json={'expectedRevision': noted['revision']}).json()['data']
                second = version(client, archived).json()['data']
                cli('backend.maintenance', 'backup', '--data-dir', original, '--output', backup_file, expected=2)
                conflict = root / '同端口不应初始化'
                cli('backend.desktop', 'start', '--data-dir', conflict, '--port', port, '--no-browser', expected=2)
                assert not (conflict / 'shad.sqlite3').exists()
                assert client.get('/api/runtime').json()['data']['desktop']['instanceId'] == started['instanceId']
            stopped = cli('backend.desktop', 'stop', '--data-dir', original)
            assert not stopped['running']
            assert not (original / 'desktop-runtime.json').exists()
            backup_result = cli('backend.maintenance', 'backup', '--data-dir', original, '--output', backup_file)
            assert backup_result['counts']['reports'] == 2
            with ZipFile(backup_file) as zipped:
                names = zipped.namelist()
                assert set(names) == {'manifest.json', 'shad.sqlite3', *[n for n in names if n.startswith('sources/')]}
                assert all('desktop' not in n and not n.endswith('.pkl') and 'logs/' not in n for n in names)
            recovered = cli('backend.maintenance', 'restore', '--archive', backup_file, '--data-dir', restored)
            assert recovered['counts'] == backup_result['counts'] and recovered['modelsVerified'] == 1
            restarted = cli('backend.desktop', 'start', '--data-dir', restored, '--port', port, '--no-browser')
            assert restarted['instanceId'] != started['instanceId']
            with httpx.Client(base_url=restarted['url'], trust_env=False, timeout=15) as client:
                assert client.get(path).json()['data'] == archived
                assert client.get('/api/reports/' + second['id']).json()['data'] == second
                assert create(client, config).json()['data'] == archived
                assert version(client, archived).json()['data'] == second
                assert client.get('/api/detections/' + config['detectionId'] + '/points?pageSize=500').json()['data']['total'] == 60
                assert client.get('/api/stations?segmentId=seg-example').json()['data']['total'] == 1
            assert not cli('backend.desktop', 'stop', '--data-dir', restored)['running']
            record = {'verifiedAt': datetime.now(timezone.utc).isoformat(), 'serviceVersion': runtime['serviceVersion'],
                      'transport': 'frozen executable and loopback TCP' if parsed_exe else 'actual CLI/background child and loopback TCP', 'schemaVersion': recovered['schemaVersion'],
                      'input': 'actual example model; synthetic input; not site validation', 'restoredCounts': recovered['counts'],
                      'checks': ['Chinese and spaced data paths', 'start and reopen same managed instance',
                                 'real static page', 'missing stop token rejected', 'foreign Origin rejected',
                                 'port conflict does not initialize another database or stop the existing listener',
                                 'running service blocks backup', 'authenticated graceful stop and control record cleanup',
                                 'verified offline SQLite and original CSV backup; no code/models/control token',
                                 'restore to new folder', 'same port restart with restored data',
                                 'unchanged notes, archived version, new version, 60 points and stable events',
                                 'report/version idempotency retained', 'clean stop of restored service'], 'passed': True}
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Managed start/stop and backup/restore checks passed (real processes and actual model).')
        except Exception:
            log = original / 'logs/service.log'
            if log.exists():
                print(log.read_text(encoding='utf-8')[-6000:], file=sys.stderr)
            raise
        finally:
            for directory in (original, restored):
                if status(directory)['running']:
                    stop(directory)


if __name__ == '__main__':
    main()
