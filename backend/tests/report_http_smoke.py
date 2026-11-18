"""Real CLI/TCP report persistence and restart, using isolated synthetic input."""
import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.registry import ROOT
from backend.tests.temp_data import isolated_data
from backend.tests.test_reports import create, detection, version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with isolated_data() as directory, tempfile.TemporaryFile() as log, \
            httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=15) as client:
        def start(register=False):
            command = [sys.executable, '-m', 'backend', '--port', str(port), '--data-dir', directory]
            if register:
                command += ['--registry', 'backend/config/registry.example.json']
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            for _ in range(100):
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read().decode('utf-8', errors='replace'))
                try:
                    if client.get('/api/runtime').status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            stop(process)
            raise RuntimeError('Backend startup timed out')

        def stop(process):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)

        process = start(True)
        try:
            config = detection(client)
            first = create(client, config).json()['data']
            path = '/api/reports/' + first['id']
            updated = client.patch(path + '/note', json={'note': '真实进程重启验收；合成数据，不作现场结论。',
                                                       'expectedRevision': first['revision']}).json()['data']
            archived = client.post(path + '/archive', json={'expectedRevision': updated['revision']}).json()['data']
            assert archived['archivedAt'] and len(archived['snapshot']['points']) == 60
            second = version(client, archived).json()['data']
            assert second['version'] == 2 and second['snapshot'] == archived['snapshot']
        finally:
            stop(process)
        process = start()
        try:
            assert client.get(path).json()['data'] == archived
            assert client.get('/api/reports/' + second['id']).json()['data'] == second
            assert create(client, config).json()['data'] == archived
            assert version(client, archived).json()['data'] == second
            assert client.patch(path + '/note', json={'note': '禁止覆盖', 'expectedRevision': archived['revision']}).status_code == 409
            assert client.patch('/api/reports/' + second['id'] + '/note', json={'note': '过期修订', 'expectedRevision': 999}).status_code == 409
            history = client.get('/api/reports?detectionId=' + config['detectionId']).json()['data']
            assert history['total'] == 2 and all('snapshot' not in r for r in history['items'])
            runtime = client.get('/api/runtime').json()['data']
            assert runtime['capabilities']['reportPersistence'] and not runtime['capabilities']['causeDiagnosis']
            record = {'verifiedAt': datetime.now(timezone.utc).isoformat(), 'transport': 'real CLI and loopback TCP',
                      'serviceVersion': runtime['serviceVersion'], 'schemaVersion': runtime['storage']['schemaVersion'],
                      'input': 'actual registered example model, synthetic 60-point input; not field validation',
                      'capabilities': runtime['capabilities'], 'pointCount': len(archived['snapshot']['points']),
                      'eventCount': len(archived['eventIds']), 'versions': [archived['version'], second['version']],
                      'checks': ['real detection', 'independent report snapshot', 'saved Chinese note', 'archive lock',
                                 'new version preserves old', 'actual process stop/start without registry',
                                 'unchanged saved reports', 'creation/version deduplication across restart',
                                 'revision conflict', 'lightweight filtered history'], 'passed': True}
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Report CLI/HTTP/restart checks passed (actual model, synthetic input).')
        finally:
            stop(process)


if __name__ == '__main__':
    main()
