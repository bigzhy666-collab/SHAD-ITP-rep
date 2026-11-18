import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.__main__ import main
from backend.app import create_app
from backend.control import DesktopControl
from backend.desktop import CONTROL_FILE, control_record, default_data_dir, status, stop, main as desktop_main


def test_desktop_close_does_not_stop_a_replacement_instance(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.desktop.status', lambda directory: {'running': True, 'instanceId': 'new'})
    call = Mock()
    monkeypatch.setattr('backend.desktop.call', call)
    with pytest.raises(RuntimeError, match='实例已变化'):
        stop(tmp_path, expected_instance='old')
    call.assert_not_called()
from backend.locking import DataDirectoryLease


def test_control_requires_matching_token_and_origin_and_never_returns_token(tmp_path):
    stopped = Mock()
    control = DesktopControl('a' * 32, 'b' * 64, stopped)
    with TestClient(create_app(control=control), base_url='http://127.0.0.1') as client:
        runtime = client.get('/api/runtime')
        assert runtime.json()['data']['desktop']['instanceId'] == control.instance_id
        assert control.token not in runtime.text and 'token' not in runtime.text
        for headers in ({}, {'X-SHAD-Control': 'wrong'}, {'X-SHAD-Control': control.token, 'origin': 'http://example.com'}):
            assert client.post('/api/desktop/stop', json={}, headers=headers).status_code == 403
        assert client.post('/api/desktop/stop', json={'pid': 123}, headers={'X-SHAD-Control': control.token}).status_code == 422
        stopped.assert_not_called()
        response = client.post('/api/desktop/stop', json={}, headers={'X-SHAD-Control': control.token})
        assert response.status_code == 200 and response.json()['data'] == {'stopping': True, 'instanceId': control.instance_id}
        stopped.assert_called_once_with()


def test_unmanaged_service_is_not_stopped():
    with TestClient(create_app(), base_url='http://127.0.0.1') as client:
        assert client.get('/api/runtime').json()['data']['desktop'] == {'managed': False}
        response = client.post('/api/desktop/stop', json={})
        assert response.status_code == 409 and response.json()['error']['code'] == 'DESKTOP_UNMANAGED'


def test_port_conflict_fails_before_creating_database(tmp_path, capsys):
    with socket.socket() as other:
        other.bind(('127.0.0.1', 0)); other.listen()
        directory = tmp_path / '不可误初始化'
        assert main(['--port', str(other.getsockname()[1]), '--data-dir', str(directory)]) == 2
        assert not directory.exists()
        assert '端口' in capsys.readouterr().err


def test_service_lock_covers_startup_migrations(tmp_path):
    directory = tmp_path / '维护中的目录'; directory.mkdir()
    with socket.socket() as free:
        free.bind(('127.0.0.1', 0)); port = free.getsockname()[1]
    with DataDirectoryLease(directory):
        assert main(['--port', str(port), '--data-dir', str(directory)]) == 2
        assert not (directory / 'shad.sqlite3').exists()


def test_status_and_stop_do_not_trust_reused_pid_or_foreign_listener(tmp_path, monkeypatch):
    record = {'instanceId': 'a' * 32, 'pid': 123, 'port': 18765, 'token': 'b' * 64}
    (tmp_path / CONTROL_FILE).write_text(json.dumps(record))
    calls = []
    def foreign(value, stop=False):
        calls.append(stop)
        return {'desktop': {'instanceId': 'other', 'pid': 123}}
    monkeypatch.setattr('backend.desktop.call', foreign)
    assert status(tmp_path)['foreignListener']
    with pytest.raises(RuntimeError, match='其他进程'):
        stop(tmp_path)
    assert not any(calls)
    assert control_record(tmp_path) == record


@pytest.mark.parametrize('changes', [{'port': True}, {'port': -1}, {'port': 65536}, {'pid': '123'}, {'token': 'short'}, {'url': 'http://outside'},
                                    {'instanceId': '?' * 32}, {'token': '\n' * 64}])
def test_control_file_cannot_redirect_requests(tmp_path, changes):
    value = {'instanceId': 'a' * 32, 'pid': 123, 'port': 8765, 'token': 'b' * 64, **changes}
    (tmp_path / CONTROL_FILE).write_text(json.dumps(value))
    with pytest.raises(RuntimeError):
        status(tmp_path)


def test_stale_record_cannot_report_unmanaged_running_service_as_stopped(tmp_path):
    assert not status(tmp_path)['running']
    with DataDirectoryLease(tmp_path):
        with pytest.raises(RuntimeError, match='正在使用'):
            stop(tmp_path)


def test_data_directory_respects_explicit_environment_and_user_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('SHAD_DATA_DIR', str(tmp_path / '显式路径'))
    assert default_data_dir() == (tmp_path / '显式路径').resolve()
    monkeypatch.delenv('SHAD_DATA_DIR')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / '本地用户'))
    assert default_data_dir() == (tmp_path / '本地用户/SHAD/data').resolve()


def test_readable_status_does_not_claim_unmanaged_service_stopped(tmp_path, capsys):
    target = tmp_path / '尚未使用的目录'
    assert desktop_main(['status', '--data-dir', str(target), '--human']) == 0
    assert '未检测到此目录的已托管服务' in capsys.readouterr().out
    assert not target.exists()


def test_non_object_control_record_rejected(tmp_path):
    (tmp_path / CONTROL_FILE).write_text('[]')
    with pytest.raises(RuntimeError, match='格式错误'):
        status(tmp_path)


def test_status_cannot_follow_redirects_from_reused_local_port(tmp_path):
    paths = []
    class Redirector(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            paths.append(self.path)
            self.send_response(302)
            self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/must-not-follow')
            self.end_headers()
    with ThreadingHTTPServer(('127.0.0.1', 0), Redirector) as server:
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            record = {'instanceId': 'a' * 32, 'pid': 123, 'port': server.server_port, 'token': 'b' * 64}
            (tmp_path / CONTROL_FILE).write_text(json.dumps(record))
            assert not status(tmp_path)['running']
            assert paths == ['/api/runtime']
        finally:
            server.shutdown(); thread.join(timeout=2)
