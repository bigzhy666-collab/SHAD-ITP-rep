"""Real CLI/TCP detection and restart; durable crash states are explicitly seeded."""
import argparse
import csv
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.app import create_app
from backend.example_request import example_request
from backend.registry import ROOT
from backend.schemas import DetectionCreate, FIELDS, UNITS
from backend.tests.temp_data import isolated_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with isolated_data() as directory, tempfile.TemporaryFile() as log, \
            httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=10) as client:
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
            process.terminate(); process.wait(timeout=5)
            raise RuntimeError('Backend startup timed out')

        def stop(process):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)

        def finished(task_id):
            for _ in range(100):
                task = client.get('/api/detections/' + task_id).json()['data']
                if task['status'] in ('success', 'failed'):
                    return task
                time.sleep(.05)
            raise AssertionError('Task timeout')

        process = start(True)
        try:
            station = client.get('/api/stations?segmentId=seg-example').json()['data']['items'][0]
            text = io.StringIO(newline='')
            writer = csv.writer(text)
            writer.writerow(['timestamp', *FIELDS])
            writer.writerows([r['timestamp'], *r['values'].values()] for r in example_request()['samples'])
            manifest = {'name': 'CLI 任务验收数据（合成）', 'stationId': station['id'], 'timezone': station['timezone'],
                        'encoding': 'utf-8-sig', 'delimiter': ',', 'timeColumn': 'timestamp',
                        'columnMapping': {f: f for f in FIELDS}, 'sourceUnits': UNITS}
            response = client.post('/api/datasets/import', data={'manifest': json.dumps(manifest)},
                                   files={'file': ('合成.csv', text.getvalue().encode('utf-8-sig'), 'text/csv')})
            assert response.status_code == 201, response.text
            dataset = response.json()['data']
            config = {'name': 'CLI 持久化检测', 'context': {f: station[f] for f in ('enterpriseId', 'networkId', 'segmentId')},
                      'datasetId': dataset['id'], 'modelId': 'station-nbm-m1-7', 'modelVersion': 'example-1',
                      'range': {'start': dataset['start'], 'end': dataset['end']}}
            config['context']['stationId'] = station['id']
            response = client.post('/api/detections', json=config, headers={'Idempotency-Key': 'cli-original'})
            assert response.status_code == 202, response.text
            task_id = response.json()['data']['id']
            task = finished(task_id)
            assert task['status'] == 'success', task
            before = {kind: client.get(f'/api/detections/{task_id}/{kind}?pageSize=500').json()['data']
                      for kind in ('result', 'points', 'events')}
            assert before['points']['total'] == 60 and before['events']['total'] > 0
        finally:
            stop(process)
        # Simulate the durable states left by a crash; no fake state endpoint exists in the service.
        dormant = create_app(data_dir=Path(directory)).state.detections
        interrupted = dormant.create(DetectionCreate.model_validate(config), 'seed-interrupted')
        dormant.repo.claim()
        queued = dormant.create(DetectionCreate.model_validate(config), 'seed-queued')
        process = start()
        try:
            assert client.get(f'/api/detections/{task_id}').json()['data'] == task
            for kind, data in before.items():
                assert client.get(f'/api/detections/{task_id}/{kind}?pageSize=500').json()['data'] == data
            assert client.post('/api/detections', json=config, headers={'Idempotency-Key': 'cli-original'}).json()['data']['id'] == task_id
            failed = client.get(f"/api/detections/{interrupted['id']}").json()['data']
            assert failed['status'] == 'failed' and failed['error']['code'] == 'TASK_INTERRUPTED'
            assert finished(queued['id'])['status'] == 'success'
            retry = client.post(f"/api/detections/{interrupted['id']}/retry", json={}, headers={'Idempotency-Key': 'cli-retry'})
            assert retry.status_code == 202, retry.text
            assert finished(retry.json()['data']['id'])['status'] == 'success'
            runtime = client.get('/api/runtime').json()['data']
            record = {'verifiedAt': datetime.now(timezone.utc).isoformat(), 'transport': 'real CLI and loopback TCP',
                      'serviceVersion': runtime['serviceVersion'], 'schemaVersion': runtime['storage']['schemaVersion'],
                      'input': '60 synthetic points and the actual registered example artifact; not field validation',
                      'summary': before['result']['summary'], 'capabilities': runtime['capabilities'],
                      'checks': ['CSV import', '202 persisted task', 'actual model detection', '60 saved points and stable events',
                                 'real process stop/start without registry argument', 'unchanged success result and events',
                                 'idempotency retained across restart', 'seeded crash-running state becomes interrupted failure',
                                 'seeded queued state executes after real restart', 'interrupted task HTTP retry succeeds'], 'passed': True}
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Detection CLI/HTTP/restart checks passed (actual model, synthetic input).')
        finally:
            stop(process)


if __name__ == '__main__':
    main()
