import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.errors import ServiceError
from backend.example_request import example_request
from backend.registry import ROOT
from backend.schemas import DetectionCreate, FIELDS, InferenceInput, UNITS


@pytest.fixture
def client():
    with TestClient(create_app(ROOT / 'backend/config/registry.example.json'), base_url='http://127.0.0.1:8765') as client:
        yield client


def upload(client, records=None):
    records = records if records is not None else example_request()['samples']
    station = client.get('/api/stations?segmentId=seg-example').json()['data']['items'][0]
    text = io.StringIO(newline='')
    writer = csv.writer(text)
    writer.writerow(['timestamp', *FIELDS])
    writer.writerows([r['timestamp'], *[r['values'][f] for f in FIELDS]] for r in records)
    manifest = {'name': '真实模型任务验收数据（合成）', 'stationId': station['id'], 'timezone': station['timezone'],
                'encoding': 'utf-8-sig', 'delimiter': ',', 'timeColumn': 'timestamp',
                'columnMapping': {f: f for f in FIELDS}, 'sourceUnits': UNITS}
    response = client.post('/api/datasets/import', data={'manifest': json.dumps(manifest)},
                           files={'file': ('合成验收.csv', text.getvalue().encode('utf-8-sig'), 'text/csv')})
    assert response.status_code == 201, response.text
    return response.json()['data']


def body(dataset):
    return {'name': '模型批次检测', 'context': {'enterpriseId': 'ent-example', 'networkId': 'net-example',
            'segmentId': 'seg-example', 'stationId': 'station-example-m1-7'}, 'datasetId': dataset['id'],
            'modelId': 'station-nbm-m1-7', 'modelVersion': 'example-1',
            'range': {'start': dataset['start'], 'end': dataset['end']}}


def post(client, config, key='test-create'):
    return client.post('/api/detections', json=config, headers={'Idempotency-Key': key})


def finish(client, task_id):
    limit = time.monotonic() + 10
    while time.monotonic() < limit:
        response = client.get('/api/detections/' + task_id)
        assert response.status_code == 200, response.text
        task = response.json()['data']
        if task['status'] in ('success', 'failed'):
            return task
        time.sleep(.02)
    raise AssertionError('Task did not finish in 10 seconds')


def error(response, code, status=422):
    assert response.status_code == status, response.text
    assert response.json()['error']['code'] == code, response.text


def test_real_task_matches_actual_model_points_and_persists_stable_events(client):
    dataset = upload(client)
    response = post(client, body(dataset))
    assert response.status_code == 202, response.text
    accepted = response.json()['data']
    assert accepted['status'] == 'queued' and accepted['progress'] is None
    task_id = accepted['id']
    task = finish(client, task_id)
    assert task['status'] == 'success', task
    result = client.get(f'/api/detections/{task_id}/result').json()['data']
    points = client.get(f'/api/detections/{task_id}/points?pageSize=500').json()['data']
    events = client.get(f'/api/detections/{task_id}/events?pageSize=500').json()['data']
    expected = client.app.state.model_service.infer(InferenceInput.model_validate(example_request()))
    assert points['items'] == expected['points']
    assert events['total'] == len(expected['segments']) > 0
    assert result['summary']['pointCount'] == 60
    assert result['contextSnapshot'] == task['contextSnapshot'] == accepted['contextSnapshot']
    assert result['datasetSnapshot'] == accepted['datasetSnapshot']
    assert result['modelSnapshot'] == accepted['modelSnapshot']
    assert task['startedAt'] and task['finishedAt'] and task['phase'] == 'completed'
    for i, event in enumerate(events['items'], 1):
        assert event['id'] == f'event-{task_id}-{i:03d}'
        assert event['detectionId'] == task_id and event['cause'] is None and event['solution'] is None
    assert client.get(f'/api/detections/{task_id}/events').json()['data']['items'] == events['items']
    assert client.get('/api/detections?segmentId=seg-example&status=success').json()['data']['total'] == 1
    assert client.get('/api/detections?segmentId=seg-1').json()['data']['total'] == 0
    assert client.get('/api/detections?stationId=other').json()['data']['total'] == 0


def test_same_idempotency_key_concurrent_submissions_only_execute_once(client, monkeypatch):
    config = body(upload(client))
    service = client.app.state.model_service
    original = service.infer
    calls = []
    def infer(request):
        calls.append(request)
        return original(request)
    monkeypatch.setattr(service, 'infer', infer)
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: post(client, config, 'same-key'), range(12)))
    assert all(r.status_code == 202 for r in responses)
    ids = {r.json()['data']['id'] for r in responses}
    assert len(ids) == 1
    task_id = ids.pop()
    assert finish(client, task_id)['status'] == 'success'
    assert len(calls) == 1
    assert client.get('/api/detections').json()['data']['total'] == 1
    assert post(client, config, 'same-key').json()['data']['id'] == task_id
    config['name'] = 'different'
    error(post(client, config, 'same-key'), 'IDEMPOTENCY_CONFLICT', 409)


@pytest.mark.parametrize('change,code', [
    ('context', 'SOURCE_MISMATCH'), ('model', 'NOT_FOUND'), ('dataset', 'NOT_FOUND'),
    ('reversed', 'TIME_RANGE_INVALID'), ('outside', 'TIME_RANGE_INVALID'), ('naive', 'TIME_RANGE_INVALID'),
    ('extra', 'INVALID_REQUEST'), ('empty-name', 'INVALID_REQUEST'),
])
def test_invalid_task_inputs_never_create_history(client, change, code):
    config = body(upload(client))
    if change == 'context': config['context']['segmentId'] = 'seg-1'
    if change == 'model': config['modelVersion'] = 'unknown'
    if change == 'dataset': config['datasetId'] = 'unknown'
    if change == 'reversed': config['range']['start'], config['range']['end'] = config['range']['end'], config['range']['start']
    if change == 'outside': config['range']['start'] = '2020-01-01T00:00:00Z'
    if change == 'naive': config['range']['start'] = '2026-11-08T00:00:00'
    if change == 'extra': config['scenario'] = 'abnormal'
    if change == 'empty-name': config['name'] = '  '
    error(post(client, config), code, 404 if change in ('model', 'dataset') else 422)
    assert client.get('/api/detections').json()['data']['total'] == 0


def test_invalid_dataset_and_selected_core_missing_block_before_creation(client):
    records = example_request()['samples']
    for row in records[10:20]: row['values']['outdoor_temperature'] = None
    dataset = upload(client, records)
    assert dataset['status'] == 'ready'
    config = body(dataset)
    config['range'] = {'start': records[10]['timestamp'], 'end': records[19]['timestamp']}
    error(post(client, config), 'DATA_QUALITY_BLOCKED')
    hourly = upload(client, records[::2])
    assert hourly['status'] == 'invalid'
    error(post(client, body(hourly)), 'DATA_QUALITY_BLOCKED')
    assert client.get('/api/detections').json()['data']['total'] == 0


def test_over_5000_points_rejected_without_splitting(client):
    records = example_request(5001)['samples']
    dataset = upload(client, records)
    assert dataset['status'] == 'ready'
    error(post(client, body(dataset)), 'DETECTION_LIMIT_EXCEEDED')
    assert client.get('/api/detections').json()['data']['total'] == 0


def test_failed_model_task_retry_is_new_task_with_original_snapshots(client, monkeypatch):
    dataset = upload(client)
    model = client.app.state.model_service.registry.resolve('station-nbm-m1-7', 'example-1')[1]
    original = model.detect
    def fail(_): raise RuntimeError('test model failure')
    monkeypatch.setattr(model, 'detect', fail)
    task_id = post(client, body(dataset)).json()['data']['id']
    failed = finish(client, task_id)
    assert failed['status'] == 'failed' and failed['error']['code'] == 'MODEL_EXECUTION_FAILED'
    error(client.get(f'/api/detections/{task_id}/result'), 'RESULT_NOT_READY', 409)
    monkeypatch.setattr(model, 'detect', original)
    response = client.post(f'/api/detections/{task_id}/retry', json={}, headers={'Idempotency-Key': 'retry-1'})
    assert response.status_code == 202, response.text
    retried = response.json()['data']
    assert retried['id'] != task_id and retried['retryOf'] == task_id
    for key in ('contextSnapshot', 'datasetSnapshot', 'modelSnapshot', 'range'):
        assert retried[key] == failed[key]
    assert finish(client, retried['id'])['status'] == 'success'
    assert client.post(f'/api/detections/{task_id}/retry', json={}, headers={'Idempotency-Key': 'retry-1'}).json()['data']['id'] == retried['id']
    assert client.get(f'/api/detections/{task_id}').json()['data'] == failed
    error(client.post(f"/api/detections/{retried['id']}/retry", json={}, headers={'Idempotency-Key': 'invalid-retry'}), 'TASK_NOT_RETRYABLE', 409)


def test_result_transaction_rolls_back_on_write_failure_then_retry_recovers(client):
    dataset = upload(client)
    store = client.app.state.store
    with store.connection(write=True) as db:
        db.execute("CREATE TRIGGER reject_point BEFORE INSERT ON detection_points BEGIN SELECT RAISE(FAIL,'disk write failure'); END")
    task_id = post(client, body(dataset)).json()['data']['id']
    failed = finish(client, task_id)
    assert failed['status'] == 'failed' and failed['error']['code'] == 'STORAGE_WRITE_FAILED'
    with store.connection(write=True) as db:
        for table in ('detection_results', 'detection_points', 'detection_events'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        db.execute('DROP TRIGGER reject_point')
    retried = client.post(f'/api/detections/{task_id}/retry', json={}, headers={'Idempotency-Key': 'disk-retry'}).json()['data']
    assert finish(client, retried['id'])['status'] == 'success'


def test_pending_result_phase_and_shared_model_busy_wait(client):
    dataset = upload(client)
    lock = client.app.state.model_service._execution_lock
    lock.acquire()
    try:
        task_id = post(client, body(dataset)).json()['data']['id']
        for endpoint in ('result', 'points', 'events'):
            error(client.get(f'/api/detections/{task_id}/{endpoint}'), 'RESULT_NOT_READY', 409)
        task = client.get(f'/api/detections/{task_id}').json()['data']
        assert task['status'] in ('queued', 'running') and task['progress'] is None
    finally:
        lock.release()
    assert finish(client, task_id)['status'] == 'success'


def test_no_confirmed_events_is_success_with_short_context_warning(client):
    dataset = upload(client, example_request(6)['samples'])
    task_id = post(client, body(dataset)).json()['data']['id']
    task = finish(client, task_id)
    assert task['status'] == 'success'
    assert any(w['code'] == 'CONFIRMATION_CONTEXT_SHORT' for w in task['warnings'])
    assert client.get(f'/api/detections/{task_id}/events').json()['data']['total'] == 0


def test_pages_ranges_event_intersection_and_stable_ids(client):
    dataset = upload(client)
    task_id = post(client, body(dataset)).json()['data']['id']
    assert finish(client, task_id)['status'] == 'success'
    points = client.get(f'/api/detections/{task_id}/points?pageSize=17').json()['data']
    assert points['total'] == 60 and len(points['items']) == 17
    second = client.get(f'/api/detections/{task_id}/points?page=2&pageSize=17').json()['data']['items']
    assert second[0]['timestamp'] > points['items'][-1]['timestamp']
    start, end = second[1]['timestamp'], second[4]['timestamp']
    selected = client.get(f'/api/detections/{task_id}/points', params={'start': start, 'end': end}).json()['data']
    assert selected['total'] == 4
    events = client.get(f'/api/detections/{task_id}/events').json()['data']['items']
    selected_events = client.get(f'/api/detections/{task_id}/events', params={'start': start, 'end': end}).json()['data']['items']
    assert selected_events == [e for e in events if pd.Timestamp(e['start']) <= pd.Timestamp(end) and pd.Timestamp(e['end']) >= pd.Timestamp(start)]
    error(client.get(f'/api/detections/{task_id}/points?pageSize=501'), 'INVALID_REQUEST')
    error(client.get(f'/api/detections/{task_id}/events?start=not-a-time'), 'TIME_RANGE_INVALID')


def test_restart_restores_success_requeues_queued_and_fails_interrupted(client):
    dataset = upload(client)
    config = body(dataset)
    completed_id = post(client, config, 'completed').json()['data']['id']
    completed = finish(client, completed_id)
    points = client.get(f'/api/detections/{completed_id}/points?pageSize=500').json()['data']
    client.app.state.worker.close()
    service = client.app.state.detections
    interrupted = service.create(DetectionCreate.model_validate(config), 'interrupted')
    service.repo.claim()
    queued = service.create(DetectionCreate.model_validate(config), 'queued')
    directory = client.app.state.store.directory
    with TestClient(create_app(data_dir=directory), base_url='http://127.0.0.1') as reopened:
        assert reopened.get(f'/api/detections/{completed_id}').json()['data'] == completed
        assert reopened.get(f'/api/detections/{completed_id}/points?pageSize=500').json()['data'] == points
        failed = reopened.get(f"/api/detections/{interrupted['id']}").json()['data']
        assert failed['status'] == 'failed' and failed['error']['code'] == 'TASK_INTERRUPTED'
        assert finish(reopened, queued['id'])['status'] == 'success'
        assert post(reopened, config, 'completed').json()['data']['id'] == completed_id


def test_same_data_directory_cannot_run_two_workers(client):
    directory = client.app.state.store.directory
    with pytest.raises(RuntimeError, match='另一个 SHAD'):
        with TestClient(create_app(data_dir=directory), base_url='http://127.0.0.1'):
            pass
    assert client.get('/api/runtime').json()['data']['capabilities']['anomalyDetection']


def test_gap_resets_counter_and_empty_gap_range_cannot_create_task(client):
    records = example_request()['samples']
    for row in records[20:]: row['timestamp'] = (pd.Timestamp(row['timestamp']) + pd.Timedelta(hours=5)).isoformat()
    dataset = upload(client, records)
    config = body(dataset)
    config['range'] = {'start': (pd.Timestamp(records[19]['timestamp']) + pd.Timedelta(minutes=30)).isoformat(),
                       'end': (pd.Timestamp(records[20]['timestamp']) - pd.Timedelta(minutes=30)).isoformat()}
    error(post(client, config), 'DATA_EMPTY')
    task_id = post(client, body(dataset), 'gap').json()['data']['id']
    assert finish(client, task_id)['status'] == 'success'
    points = client.get(f'/api/detections/{task_id}/points?pageSize=500').json()['data']['items']
    assert points[19]['blockId'] != points[20]['blockId']
    assert points[20]['criticality'] == 1
    assert client.get(f'/api/detections/{task_id}/result').json()['data']['summary']['blockCount'] == 2


def test_station_and_model_cross_binding_rejected(client):
    dataset = upload(client)
    other = client.post('/api/stations', json={'name': 'other station', 'code': 'OTHER', 'enterpriseId': 'ent-example',
                         'networkId': 'net-example', 'segmentId': 'seg-example', 'timezone': 'Etc/UTC'}).json()['data']
    config = body(dataset)
    config['context']['stationId'] = other['id']
    error(post(client, config), 'SOURCE_MISMATCH')


def test_missing_invalid_or_oversized_idempotency_key_cannot_create_task(client):
    config = body(upload(client))
    for headers in ({}, {'Idempotency-Key': 'x' * 129}, {'Idempotency-Key': 'bad key'}):
        error(client.post('/api/detections', json=config, headers=headers), 'INVALID_REQUEST')
    assert client.get('/api/detections').json()['data']['total'] == 0


def test_queue_is_serial_and_fifo(client, monkeypatch):
    config = DetectionCreate.model_validate(body(upload(client)))
    worker = client.app.state.worker
    worker.close()
    service = client.app.state.detections
    jobs = [service.create(config, 'serial-' + str(i)) for i in range(3)]
    order = []
    original = service.execute
    def execute(task, stop):
        order.append(task['id'])
        original(task, stop)
    monkeypatch.setattr(service, 'execute', execute)
    worker.start()
    for task in jobs: assert finish(client, task['id'])['status'] == 'success'
    assert order == [task['id'] for task in jobs]


def test_changed_model_snapshot_after_queuing_is_not_silently_executed(client, monkeypatch):
    worker = client.app.state.worker
    worker.close()
    service = client.app.state.detections
    task = service.create(DetectionCreate.model_validate(body(upload(client))), 'frozen')
    model = client.app.state.model_service.registry.resolve('station-nbm-m1-7', 'example-1')[1]
    monkeypatch.setattr(model, 'c_thr', model.c_thr + 1)
    worker.start()
    failed = finish(client, task['id'])
    assert failed['status'] == 'failed' and failed['error']['code'] == 'SOURCE_SNAPSHOT_CHANGED'
    error(client.get(f"/api/detections/{task['id']}/points"), 'RESULT_NOT_READY', 409)


def test_no_point_alarm_is_success_and_does_not_create_fake_causes(client, monkeypatch):
    dataset = upload(client)
    model = client.app.state.model_service.registry.resolve('station-nbm-m1-7', 'example-1')[1]
    # A test double covers the business state only, not model accuracy.
    def normal(frame):
        return pd.DataFrame({'score': 0., 'threshold': 1., 'alarm': False, 'criticality': 0,
                             'health': 1., 'confirmed': False}, index=frame.index)
    monkeypatch.setattr(model, 'detect', normal)
    task_id = post(client, body(dataset), 'normal').json()['data']['id']
    assert finish(client, task_id)['status'] == 'success'
    summary = client.get(f'/api/detections/{task_id}/result').json()['data']['summary']
    assert summary['alarmPointCount'] == summary['eventCount'] == 0


def test_schema_one_data_upgrades_without_losing_imported_samples(client):
    dataset = upload(client)
    worker = client.app.state.worker
    worker.close()
    store = client.app.state.store
    # Remove the v2/v3 additions in this isolated fixture to reproduce the shipped v1 schema.
    with store.connection(write=True) as db:
        for table in ('report_submissions', 'reports', 'idempotency_keys', 'detection_events', 'detection_points', 'detection_results', 'detections'):
            db.execute('DROP TABLE ' + table)
        db.execute('DELETE FROM schema_migrations WHERE version>=2')
        db.execute('PRAGMA user_version=1')
    with TestClient(create_app(data_dir=store.directory), base_url='http://127.0.0.1') as reopened:
        assert reopened.get('/api/runtime').json()['data']['storage']['schemaVersion'] == 4
        assert reopened.get(f"/api/datasets/{dataset['id']}").json()['data'] == dataset
        assert reopened.get(f"/api/datasets/{dataset['id']}/samples").json()['data']['total'] == 60
        task_id = post(reopened, body(dataset)).json()['data']['id']
        assert finish(reopened, task_id)['status'] == 'success'


def test_event_boundary_uses_requested_range_and_records_actual_sample_range(client):
    dataset = upload(client)
    config = body(dataset)
    config['range']['end'] = (pd.Timestamp(dataset['end']) - pd.Timedelta(minutes=15)).isoformat()
    task_id = post(client, config, 'not-on-bin').json()['data']['id']
    assert finish(client, task_id)['status'] == 'success'
    result = client.get(f'/api/detections/{task_id}/result').json()['data']
    assert result['range'] == config['range']
    assert pd.Timestamp(result['sampleRange']['end']) < pd.Timestamp(result['range']['end'])
    events = client.get(f'/api/detections/{task_id}/events').json()['data']['items']
    assert events and all(e['boundary'] == 'within_range' for e in events)


def test_mixed_invalid_source_bins_are_readable_but_block_detection_when_quality_is_insufficient(client):
    records = []
    for row in example_request()['samples']:
        records.append(row)
        records.append({'timestamp': (pd.Timestamp(row['timestamp']) + pd.Timedelta(minutes=5)).isoformat(),
                        'values': {**row['values'], 'outdoor_temperature': 'bad'}})
    dataset = upload(client, records)
    assert dataset['status'] == 'ready' and dataset['normalizedRowCount'] == 60
    samples = client.get(f"/api/datasets/{dataset['id']}/samples?pageSize=500").json()['data']['items']
    assert all(r['values']['outdoor_temperature'] is not None and r['quality']['outdoor_temperature'] == 'invalid' for r in samples)
    error(post(client, body(dataset)), 'DATA_QUALITY_BLOCKED')
    assert client.get('/api/detections').json()['data']['total'] == 0
