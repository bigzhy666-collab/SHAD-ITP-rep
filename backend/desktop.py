"""Local startup controller. Never signals a PID or stops an unrelated listener."""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from .locking import DataDirectoryLease

ROOT = Path(__file__).resolve().parents[1]
CONTROL_FILE = 'desktop-runtime.json'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def default_data_dir():
    if os.environ.get('SHAD_DATA_DIR'):
        return Path(os.environ['SHAD_DATA_DIR']).resolve()
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    return (base / 'SHAD/data').resolve()


def control_record(directory):
    path = directory / CONTROL_FILE
    if not path.exists():
        return None
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise RuntimeError('启动记录位置异常，已停止操作。')
    if path.stat().st_size > 4096:
        raise RuntimeError('启动记录格式错误，请检查数据目录。')
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or set(value) != {'instanceId', 'pid', 'port', 'token'} or type(value['pid']) is not int or value['pid'] <= 0
            or type(value['port']) is not int or not 1 <= value['port'] <= 65535
            or not isinstance(value['instanceId'], str) or not re.fullmatch('[a-f0-9]{32}', value['instanceId'])
            or not isinstance(value['token'], str) or not re.fullmatch('[a-f0-9]{64}', value['token'])):
        raise RuntimeError('启动记录格式错误，请检查数据目录。')
    return value


def call(record, stop=False):
    # Only a validated port is read from disk. Host, path and proxy policy are fixed.
    request = Request(f"http://127.0.0.1:{record['port']}/api/" + ('desktop/stop' if stop else 'runtime'),
                      data=b'{}' if stop else None,
                      headers={'Content-Type': 'application/json', **({'X-SHAD-Control': record['token']} if stop else {})})
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=2) as response:
        return json.loads(response.read(65536))['data']


def status(directory):
    record = control_record(directory)
    if record is None:
        return {'running': False, 'dataDir': str(directory)}
    try:
        runtime = call(record)
    except (HTTPError, URLError, OSError, ValueError, KeyError):
        return {'running': False, 'dataDir': str(directory), 'staleRecord': True}
    identity = runtime.get('desktop', {})
    if identity.get('instanceId') != record['instanceId'] or identity.get('pid') != record['pid']:
        return {'running': False, 'dataDir': str(directory), 'foreignListener': True}
    return {'running': True, 'dataDir': str(directory), 'url': f"http://127.0.0.1:{record['port']}",
            'serviceVersion': runtime['serviceVersion'], 'instanceId': record['instanceId']}


def start(directory, port=8765, *, registry=None, model_dir=None, open_browser=True, timeout=40):
    directory = directory.resolve()
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise RuntimeError('找不到界面文件，请先构建前端或检查安装资源。')
    if not 1 <= port <= 65535:
        raise ValueError('端口必须在 1..65535。')
    directory.mkdir(parents=True, exist_ok=True)
    with DataDirectoryLease(directory, 'launcher.lock'):
        current = status(directory)
        if current['running']:
            if open_browser:
                webbrowser.open(current['url'] + '/model?service=local')
            return {**current, 'reused': True}
        # A service started manually may own this directory without a controller record.
        with DataDirectoryLease(directory):
            pass
        logs = directory / 'logs'
        logs.mkdir(exist_ok=True)
        env = dict(os.environ, SHAD_CONTROL_INSTANCE=uuid4().hex, SHAD_CONTROL_TOKEN=secrets.token_hex(32))
        command = ([sys.executable, 'serve'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'backend'])
        command += ['--port', str(port), '--serve-frontend', '--data-dir', str(directory)]
        if registry:
            command += ['--registry', str(registry.resolve())]
        if model_dir:
            command += ['--model-dir', str(model_dir.resolve())]
        with (logs / 'launcher.log').open('ab') as output:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if process.poll() is not None:
                raise RuntimeError(f'服务未能启动，可能端口已占用或目录不可写。请查看 {logs / "launcher.log"}。')
            current = status(directory)
            if current['running'] and current['instanceId'] == env['SHAD_CONTROL_INSTANCE']:
                if open_browser:
                    webbrowser.open(current['url'] + '/model?service=local')
                return {**current, 'reused': False}
            time.sleep(.1)
        # No PID killing: a slow service may still be starting and holds its own data lease.
        raise RuntimeError(f'启动等待超时，服务可能仍在启动。请先查询状态，日志位于 {logs}。')


def stop(directory, timeout=30, *, expected_instance=None):
    directory = directory.resolve()
    current = status(directory)
    if current['running'] and expected_instance is not None and current['instanceId'] != expected_instance:
        raise RuntimeError('服务实例已变化，未停止其他实例。')
    if not current['running']:
        if current.get('foreignListener'):
            raise RuntimeError('端口由其他进程使用，未向该进程发送停止操作。')
        # Refuse to report success if an unmanaged/starting service still owns the directory.
        if directory.exists():
            with DataDirectoryLease(directory):
                pass
        return {'running': False, 'dataDir': str(directory), 'alreadyStopped': True}
    record = control_record(directory)
    if record is None or record['instanceId'] != current['instanceId']:
        raise RuntimeError('服务实例已变化，请重新查询状态。')
    try:
        result = call(record, stop=True)
        if result.get('instanceId') != record['instanceId'] or not result.get('stopping'):
            raise RuntimeError('服务未确认停止请求。')
    except (HTTPError, URLError, OSError, ValueError, KeyError) as exc:
        raise RuntimeError('停止请求未确认，请查询状态后重试；没有强制结束其他进程。') from exc
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        current = status(directory)
        if not current['running']:
            try:
                with DataDirectoryLease(directory):
                    return {'running': False, 'dataDir': str(directory), 'alreadyStopped': False}
            except RuntimeError:
                pass
        elif current['instanceId'] != record['instanceId']:
            raise RuntimeError('原服务已退出，但此目录出现新服务，未停止新实例。')
        time.sleep(.1)
    raise RuntimeError('服务仍在退出，请稍后查询；未强制终止，数据目录仍受保护。')


def main(argv=None):
    parser = argparse.ArgumentParser(description='SHAD 本地启动、停止与状态管理')
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--data-dir', type=Path, default=default_data_dir())
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--expected-instance', help='仅停止此实例，供桌面窗口安全退出使用')
    parser.add_argument('--human', action='store_true', help='显示便于阅读的中文状态')
    args = parser.parse_args(argv)
    try:
        directory = args.data_dir.resolve()
        result = start(directory, args.port, registry=args.registry, model_dir=args.model_dir,
                       open_browser=not args.no_browser) if args.action == 'start' else (
                           stop(directory, expected_instance=args.expected_instance) if args.action == 'stop' else status(directory))
        if args.human:
            print('SHAD 已在运行。' if result['running'] else (
                '未检测到此目录的已托管服务；手动启动的服务请在原窗口核查。' if args.action == 'status' else 'SHAD 已停止。'))
            if result.get('reused'):
                print('已打开原来的服务实例。')
            if result.get('url'):
                print('本机地址：' + result['url'])
            print('数据目录：' + result['dataDir'])
        else:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'SHAD：{exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
