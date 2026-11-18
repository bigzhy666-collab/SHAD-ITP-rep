from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.example_request import example_request
from backend.tests.test_detection_service import body, client, error, finish, post, upload


def detection(client, key='detection'):
    task_id = post(client, body(upload(client)), key).json()['data']['id']
    assert finish(client, task_id)['status'] == 'success'
    events = client.get(f'/api/detections/{task_id}/events?pageSize=500').json()['data']['items']
    assert events
    return {'detectionId': task_id, 'eventIds': [e['id'] for e in events], 'diagnosisId': None}


def create(client, config, key='report'):
    return client.post('/api/reports', json=config, headers={'Idempotency-Key': key})


def version(client, report, key='version'):
    return client.post(f"/api/reports/{report['id']}/versions", json={'expectedRevision': report['revision']},
                       headers={'Idempotency-Key': key})


def test_snapshot_notes_archive_versions_and_history(client):
    config = detection(client)
    response = create(client, config)
    assert response.status_code == 201, response.text
    original = response.json()['data']
    assert original['version'] == original['revision'] == 1
    assert original['seriesId'] == original['id'] and original['sourceReportId'] is None
    assert original['eventIds'] == config['eventIds'] and original['diagnosisId'] is None
    assert original['snapshot']['diagnosis'] is None
    task_id = config['detectionId']
    assert original['snapshot']['task'] == client.get('/api/detections/' + task_id).json()['data']
    assert original['snapshot']['result'] == client.get(f'/api/detections/{task_id}/result').json()['data']
    assert original['snapshot']['points'] == client.get(f'/api/detections/{task_id}/points?pageSize=500').json()['data']['items']
    assert original['snapshot']['events'] == client.get(f'/api/detections/{task_id}/events?pageSize=500').json()['data']['items']
    assert original['snapshot']['task']['modelSnapshot']['isDemo']
    report_id = original['id']
    saved = client.patch(f'/api/reports/{report_id}/note', json={'note': '中文备注\n人工核查 <script>未执行</script> 🧪', 'expectedRevision': 1}).json()['data']
    assert saved['revision'] == 2
    unchanged = client.patch(f'/api/reports/{report_id}/note', json={'note': saved['note'], 'expectedRevision': 2}).json()['data']
    assert unchanged == saved
    archived = client.post(f'/api/reports/{report_id}/archive', json={'expectedRevision': 2}).json()['data']
    assert archived['revision'] == 3 and archived['archivedAt']
    assert archived['snapshot'] == original['snapshot']
    assert client.post(f'/api/reports/{report_id}/archive', json={'expectedRevision': 2}).json()['data'] == archived
    error(client.patch(f'/api/reports/{report_id}/note', json={'note': '禁止修改', 'expectedRevision': 3}), 'REPORT_ARCHIVED', 409)
    new = version(client, archived).json()['data']
    assert new['version'] == 2 and new['revision'] == 1 and new['archivedAt'] is None
    assert new['id'] != report_id and new['seriesId'] == report_id and new['sourceReportId'] == report_id
    assert new['snapshot'] == original['snapshot'] and new['note'] == saved['note']
    assert client.get('/api/reports/' + report_id).json()['data'] == archived
    history = client.get('/api/reports?pageSize=1').json()['data']
    assert history['total'] == 2 and history['items'][0]['id'] == new['id']
    assert 'snapshot' not in history['items'][0]
    assert client.get('/api/reports?pageSize=1&page=2').json()['data']['items'][0]['id'] == report_id
    assert client.get('/api/reports?archived=true').json()['data']['items'][0]['id'] == report_id
    assert client.get('/api/reports?archived=false').json()['data']['total'] == 1
    assert client.get('/api/reports?detectionId=other').json()['data']['total'] == 0


def test_deduplicates_concurrent_create_and_version_and_conflicting_keys(client):
    config = detection(client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: create(client, config), range(8)))
    assert all(r.status_code == 201 for r in responses)
    ids = {r.json()['data']['id'] for r in responses}
    assert len(ids) == 1
    report = responses[0].json()['data']
    error(create(client, {**config, 'diagnosisId': 'different'}), 'IDEMPOTENCY_CONFLICT', 409)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: version(client, report), range(8)))
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()['data']['id'] for r in responses}) == 1
    assert client.get('/api/reports').json()['data']['total'] == 2
    error(version(client, {**report, 'revision': 2}), 'IDEMPOTENCY_CONFLICT', 409)
    assert version(client, report, 'intentional-next-version').json()['data']['version'] == 3


def test_revision_conflicts_never_overwrite_saved_notes_or_archive(client):
    report = create(client, detection(client)).json()['data']
    path = '/api/reports/' + report['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda text: client.patch(path + '/note', json={'note': text, 'expectedRevision': 1}), ['甲', '乙']))
    assert sorted(r.status_code for r in responses) == [200, 409]
    saved = client.get(path).json()['data']
    assert saved['note'] in ('甲', '乙') and saved['revision'] == 2
    error(client.post(path + '/archive', json={'expectedRevision': 1}), 'REVISION_CONFLICT', 409)
    error(version(client, report), 'REVISION_CONFLICT', 409)
    assert client.get(path).json()['data'] == saved


@pytest.mark.parametrize('changes,code,status', [
    ({'eventIds': []}, 'INVALID_REQUEST', 422),
    ({'eventIds': ['missing']}, 'SOURCE_MISMATCH', 422),
    ({'diagnosisId': 'unavailable'}, 'CAPABILITY_UNAVAILABLE', 503),
    ({'detectionId': 'missing'}, 'NOT_FOUND', 404),
    ({'snapshot': {}}, 'INVALID_REQUEST', 422),
])
def test_rejects_invalid_sources_and_client_supplied_snapshot(client, changes, code, status):
    config = detection(client)
    error(create(client, {**config, **changes}), code, status)
    assert client.get('/api/reports').json()['data']['total'] == 0


def test_duplicate_and_cross_task_events_rejected(client):
    first = detection(client, 'first')
    second = detection(client, 'second')
    error(create(client, {**first, 'eventIds': first['eventIds'] * 2}), 'INVALID_REQUEST')
    error(create(client, {**first, 'eventIds': second['eventIds']}), 'SOURCE_MISMATCH')


def test_queued_detection_cannot_be_reported(client):
    client.app.state.worker.close()
    service = client.app.state.detections
    from backend.schemas import DetectionCreate
    queued = service.create(DetectionCreate.model_validate(body(upload(client))), 'queue')
    error(create(client, {'detectionId': queued['id'], 'eventIds': ['unconfirmed'], 'diagnosisId': None}), 'RESULT_NOT_READY', 409)


@pytest.mark.parametrize('payload', [{'note': 'x' * 2001, 'expectedRevision': 1}, {'note': '', 'expectedRevision': True},
                                    {'note': '', 'expectedRevision': 0}, {'note': '', 'expectedRevision': '1'}])
def test_note_contract_is_strict(client, payload):
    error(client.patch('/api/reports/missing/note', json=payload), 'INVALID_REQUEST')


def test_atomic_storage_failures_can_retry_without_partial_report_or_version(client):
    config = detection(client)
    store = client.app.state.store
    with store.connection(write=True) as db:
        db.execute("CREATE TRIGGER fail_submit BEFORE INSERT ON report_submissions BEGIN SELECT RAISE(ABORT,'test'); END")
    response = create(client, config)
    error(response, 'STORAGE_WRITE_FAILED', 500)
    assert response.json()['error']['retryable']
    assert client.get('/api/reports').json()['data']['total'] == 0
    with store.connection(write=True) as db:
        db.execute('DROP TRIGGER fail_submit')
    report = create(client, config).json()['data']
    with store.connection(write=True) as db:
        db.execute("CREATE TRIGGER fail_update BEFORE UPDATE ON reports BEGIN SELECT RAISE(ABORT,'test'); END")
    error(client.patch(f"/api/reports/{report['id']}/note", json={'note': '失败后重试', 'expectedRevision': 1}), 'STORAGE_WRITE_FAILED', 500)
    error(client.post(f"/api/reports/{report['id']}/archive", json={'expectedRevision': 1}), 'STORAGE_WRITE_FAILED', 500)
    assert client.get('/api/reports/' + report['id']).json()['data'] == report
    with store.connection(write=True) as db:
        db.execute('DROP TRIGGER fail_update')
        db.execute("CREATE TRIGGER fail_version BEFORE INSERT ON report_submissions BEGIN SELECT RAISE(ABORT,'test'); END")
    error(version(client, report), 'STORAGE_WRITE_FAILED', 500)
    assert client.get('/api/reports').json()['data']['total'] == 1
    with store.connection(write=True) as db:
        db.execute('DROP TRIGGER fail_version')
    assert version(client, report).json()['data']['version'] == 2


def test_report_snapshot_independent_of_source_rows_and_survives_restart(client):
    config = detection(client)
    report = create(client, config).json()['data']
    store = client.app.state.store
    # Simulate later administrative source changes; stored report and descendants retain the evidence.
    with store.connection(write=True) as db:
        db.execute('DELETE FROM detection_points WHERE detection_id=?', (config['detectionId'],))
    assert client.get('/api/reports/' + report['id']).json()['data'] == report
    assert version(client, report).json()['data']['snapshot'] == report['snapshot']
    error(create(client, config, 'new'), 'RESULT_UNAVAILABLE', 503)
    client.app.state.worker.close()
    with TestClient(create_app(data_dir=store.directory), base_url='http://127.0.0.1') as restarted:
        assert restarted.get('/api/reports/' + report['id']).json()['data'] == report
        assert create(restarted, config).json()['data'] == report
        assert version(restarted, report).json()['data']['version'] == 2
        assert restarted.get('/api/reports').json()['data']['total'] == 2


def test_schema_two_upgrade_preserves_real_results(client):
    config = detection(client)
    client.app.state.worker.close()
    store = client.app.state.store
    with store.connection(write=True) as db:
        db.execute('DROP TABLE report_submissions')
        db.execute('DROP TABLE reports')
        db.execute('DELETE FROM schema_migrations WHERE version=3')
        db.execute('PRAGMA user_version=2')
    with TestClient(create_app(data_dir=store.directory), base_url='http://127.0.0.1') as restarted:
        runtime = restarted.get('/api/runtime').json()['data']
        assert runtime['storage']['schemaVersion'] == 4 and runtime['capabilities']['reportPersistence']
        report = create(restarted, config).json()['data']
        assert len(report['snapshot']['points']) == 60


def test_missing_report_and_invalid_submission_key(client):
    error(client.get('/api/reports/missing'), 'NOT_FOUND', 404)
    config = detection(client)
    error(client.post('/api/reports', json=config), 'INVALID_REQUEST')
    error(create(client, config, 'invalid key'), 'INVALID_REQUEST')
    error(client.get('/api/reports?page=0'), 'INVALID_REQUEST')
    error(client.get('/api/reports?pageSize=501'), 'INVALID_REQUEST')


def test_complete_curve_over_one_page_and_multi_event_selection(client):
    # A real model run containing a gap creates separate continuous blocks/events.
    records = example_request(600)['samples']
    records = records[:300] + records[301:]
    dataset = upload(client, records)
    task_id = post(client, body(dataset)).json()['data']['id']
    assert finish(client, task_id)['status'] == 'success'
    events = client.get(f'/api/detections/{task_id}/events?pageSize=500').json()['data']['items']
    assert len(events) >= 2
    config = {'detectionId': task_id, 'eventIds': [e['id'] for e in events], 'diagnosisId': None}
    report = create(client, config).json()['data']
    assert len(report['snapshot']['points']) == 599 > 500
    assert report['snapshot']['result']['summary']['pointCount'] == 599
    assert report['snapshot']['events'] == events
    assert create(client, {**config, 'eventIds': list(reversed(config['eventIds']))}).json()['data']['id'] == report['id']
    single = create(client, {**config, 'eventIds': config['eventIds'][:1]}, 'single').json()['data']
    assert len(single['snapshot']['events']) == 1 and len(single['snapshot']['points']) == 599
