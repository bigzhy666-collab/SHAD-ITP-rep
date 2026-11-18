import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.storage import LocalStore


@pytest.fixture
def client():
    with TestClient(create_app(), base_url='http://127.0.0.1:8765') as c:
        yield c


def update(c, kind, row, **changes):
    return c.patch(f'/api/organizations/{kind}/{row["id"]}', json={
        'name': row['name'], 'code': row['code'], 'active': row['active'],
        'expectedRevision': row['revision'], **changes})


def test_hierarchy_update_conflict_duplicate_and_restart(client):
    ent = client.post('/api/enterprises', json={'name': '新企业', 'code': 'NEW'}).json()['data']
    net = client.post('/api/networks', json={'name': '新管网', 'code': 'NEW', 'enterpriseId': ent['id']}).json()['data']
    seg = client.post('/api/segments', json={'name': '新管段', 'code': 'NEW', 'networkId': net['id']}).json()['data']
    saved = update(client, 'segments', seg, name='已改名', active=False).json()['data']
    assert saved['revision'] == 2 and not saved['active']
    assert update(client, 'segments', seg, name='旧窗口覆盖').status_code == 409
    assert client.post('/api/segments', json={'name': '重复', 'code': 'new', 'networkId': net['id']}).status_code == 409
    directory = client.app.state.store.directory
    client.app.state.worker.close()
    with TestClient(create_app(data_dir=directory), base_url='http://127.0.0.1:8765') as reopened:
        actual = reopened.get('/api/organizations').json()['data']
        assert saved in actual['segments'] and ent in actual['enterprises']


def test_disabled_parent_blocks_new_children_and_station_but_preserves_history(client):
    rows = client.get('/api/organizations').json()['data']
    ent = rows['enterprises'][0]
    assert update(client, 'enterprises', ent, active=False).status_code == 200
    assert client.post('/api/networks', json={'name': '禁止新增', 'code': 'OFF', 'enterpriseId': ent['id']}).status_code == 409
    assert client.post('/api/segments', json={'name': '禁止新增', 'code': 'OFF', 'networkId': 'net-1'}).status_code == 409
    assert client.post('/api/stations', json={'name': '禁止站', 'code': 'OFF', 'enterpriseId': 'ent-1', 'networkId': 'net-1', 'segmentId': 'seg-1', 'timezone': 'Asia/Shanghai'}).status_code == 409
    assert len(client.get('/api/organizations').json()['data']['segments']) == len(rows['segments'])
    assert not client.get('/api/organizations').json()['data']['enterprises'][0]['active']


def test_cannot_reparent_or_patch_unknown_kind(client):
    row = client.get('/api/organizations').json()['data']['networks'][0]
    assert update(client, 'networks', row, enterpriseId='ent-2').status_code == 422
    assert update(client, 'stations', row).status_code == 422
    assert update(client, 'networks', {**row, 'id': 'unknown'}).status_code == 404


def test_schema_three_upgrade_preserves_existing_ids(tmp_path):
    store = LocalStore(tmp_path / 'data')
    with store.connection(write=True) as db:
        for kind in ('enterprises', 'networks', 'segments'):
            db.execute(f'ALTER TABLE {kind} DROP COLUMN active')
            db.execute(f'ALTER TABLE {kind} DROP COLUMN revision')
        db.execute('DELETE FROM schema_migrations WHERE version=4')
        db.execute('PRAGMA user_version=3')
    reopened = LocalStore(store.directory)
    assert reopened.organizations()['segments'][0]['id'] == 'seg-1'
    assert reopened.organizations()['segments'][0]['revision'] == 1
    with reopened.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4


def test_renames_preserve_saved_snapshots_and_disabled_path_blocks_detection():
    from backend.registry import ROOT
    from backend.tests.test_detection_service import upload, body, post, finish
    from backend.tests.test_reports import create
    registry = ROOT / 'backend/config/registry.example.json'
    with TestClient(create_app(registry), base_url='http://127.0.0.1:8765') as c:
        dataset = upload(c)
        task_id = post(c, body(dataset)).json()['data']['id']
        original = finish(c, task_id)
        events = c.get(f'/api/detections/{task_id}/events').json()['data']['items']
        report = create(c, {'detectionId': task_id, 'eventIds': [e['id'] for e in events], 'diagnosisId': None}).json()['data']
        ent = next(r for r in c.get('/api/organizations').json()['data']['enterprises'] if r['id'] == 'ent-example')
        assert update(c, 'enterprises', ent, name='本地维护后的企业', active=False).status_code == 200
        denied = post(c, body(dataset), 'new-after-disabled')
        assert denied.status_code == 409 and denied.json()['error']['code'] == 'ORGANIZATION_INACTIVE'
        assert c.get('/api/detections/' + task_id).json()['data'] == original
        assert c.get('/api/reports/' + report['id']).json()['data'] == report
        directory = c.app.state.store.directory
    # An old administrator registry cannot undo a local rename or re-enable an object.
    with TestClient(create_app(registry, data_dir=directory), base_url='http://127.0.0.1:8765') as c:
        ent = next(r for r in c.get('/api/organizations').json()['data']['enterprises'] if r['id'] == 'ent-example')
        assert ent['name'] == '本地维护后的企业' and not ent['active']
        assert c.get('/api/reports/' + report['id']).json()['data'] == report
