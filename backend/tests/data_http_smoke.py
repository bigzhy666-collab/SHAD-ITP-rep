"""Real CLI stop/start with isolated disk data, without mocking the server."""
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

from backend.example_request import example_request
from backend.registry import ROOT
from backend.schemas import FIELDS, UNITS
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
        def start():
            process = subprocess.Popen([sys.executable, '-m', 'backend', '--port', str(port), '--data-dir', directory],
                                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
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
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError('Backend startup timed out')

        def stop(process):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        process = start()
        try:
            station = client.post('/api/stations', json={
                'name': '真实重启验收站', 'code': 'RESTART-1', 'enterpriseId': 'ent-1', 'networkId': 'net-1',
                'segmentId': 'seg-1', 'timezone': 'Asia/Shanghai'}).json()['data']
            text = io.StringIO(newline='')
            writer = csv.writer(text)
            writer.writerow(['时间', *FIELDS])
            for sample in example_request(12)['samples']:
                writer.writerow([sample['timestamp'], *[sample['values'][f] for f in FIELDS]])
            manifest = {'name': '重启验收数据', 'stationId': station['id'], 'timezone': station['timezone'],
                        'encoding': 'utf-8-sig', 'delimiter': ',', 'timeColumn': '时间',
                        'columnMapping': {f: f for f in FIELDS}, 'sourceUnits': UNITS}
            response = client.post('/api/datasets/import', data={'manifest': json.dumps(manifest)},
                                   files={'file': ('运行.csv', text.getvalue().encode('utf-8-sig'), 'text/csv')})
            assert response.status_code == 201, response.text
            dataset = response.json()['data']
            assert dataset['status'] == 'ready'
            before = client.get(f"/api/datasets/{dataset['id']}/samples?pageSize=500").json()['data']
        finally:
            stop(process)
        process = start()
        try:
            runtime = client.get('/api/runtime').json()['data']
            assert runtime['capabilities']['dataImport']
            assert runtime['capabilities']['anomalyDetection']
            assert not runtime['capabilities']['causeDiagnosis'] and runtime['capabilities']['reportPersistence']
            assert client.get('/api/stations').json()['data']['items'] == [station]
            assert client.get(f"/api/datasets/{dataset['id']}").json()['data'] == dataset
            after = client.get(f"/api/datasets/{dataset['id']}/samples?pageSize=500").json()['data']
            assert before == after and after['total'] == 12
            assert len(list((Path(directory) / 'sources').glob('*.csv'))) == 1
            assert client.post('/api/detections', json={}).status_code == 422
            record = {'verifiedAt': datetime.now(timezone.utc).isoformat(), 'transport': 'real loopback TCP',
                      'serviceVersion': runtime['serviceVersion'], 'databaseSchema': runtime['storage']['schemaVersion'],
                      'input': '12 synthetic points; no training or accuracy claim',
                      'checks': ['CLI startup', 'station persistence', 'multipart CSV import', 'actual process restart',
                                 'identical dataset metadata and 12 samples after restart', 'original CSV retained',
                                 'invalid detection request rejected', 'cause/report capabilities remain closed'], 'passed': True}
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Data API real HTTP import/restart checks passed.')
        finally:
            stop(process)


if __name__ == '__main__':
    main()
