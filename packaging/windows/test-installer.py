"""Opt-in actual Windows install/upgrade/uninstall, isolated inside release/."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg

ROOT = Path(__file__).resolve().parents[2]
KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A782FB3C-E802-4CC0-B55E-C94FDABFD980}_is1'
TEST_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{9B718A31-9E03-48B8-A2EC-5D0784A7C7E1}_is1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--previous-setup', type=Path, help='可选：先装旧版，再验证保留数据升级')
    parser.add_argument('--isolated-identity', action='store_true', help='仅用于专用验收标识的安装包，保护现有正式安装')
    args = parser.parse_args()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY if args.isolated_identity else KEY):
            raise RuntimeError('已有 SHAD 安装记录，拒绝覆盖用户安装。')
    except FileNotFoundError:
        pass
    setup = args.setup.resolve()
    work = ROOT / 'release/installer-checks' / time.strftime('%Y%m%d-%H%M%S')
    app = work / '安装目录 空格'
    data = work / '业务数据 保留'
    work.mkdir(parents=True)
    def run(command, ok=True):
        p = subprocess.run(list(map(str, command)), capture_output=True, timeout=180)
        if ok:
            assert p.returncode == 0, (p.returncode, p.stderr.decode('utf-8', errors='replace'))
        return p
    def install():
        return [setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                '/TASKS=', '/GROUP=SHAD 安装验收', '/DIR=' + str(app), '/LOG=' + str(work / 'setup.log')]
    if args.previous_setup:
        previous = install()
        previous[0] = str(args.previous_setup.resolve())
        run(previous)
        old_exe = app / 'SHAD.exe'
        run([old_exe, '--json', 'start', '--data-dir', data, '--no-browser', '--port', '18779'])
        run([old_exe, '--json', 'stop', '--data-dir', data])
        before_upgrade = hashlib.sha256((data / 'shad.sqlite3').read_bytes()).hexdigest()
        run(install())
        assert hashlib.sha256((data / 'shad.sqlite3').read_bytes()).hexdigest() == before_upgrade
    else:
        run(install())
    exe = app / 'resources/backend/SHAD.exe'
    uninstaller = app / 'unins000.exe'
    assert exe.exists() and uninstaller.exists()
    try:
        run([sys.executable, '-m', 'backend.tests.desktop_http_smoke', '--exe', exe,
             '--out', ROOT / 'verification/windows-installer/installed-workflow.json'])
        # Persist a real empty service database outside the installation directory.
        run([exe, '--json', 'start', '--data-dir', data, '--no-browser', '--port', '18779'])
        assert run(install(), ok=False).returncode != 0, '运行中必须拒绝覆盖安装'
        blocked = run([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], ok=False)
        assert blocked.returncode != 0 and exe.exists(), '运行中必须拒绝卸载'
        run([exe, '--json', 'stop', '--data-dir', data])
        guard = subprocess.Popen([str(exe), 'guard'], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            time.sleep(.5)
            assert run(install(), ok=False).returncode != 0, '窗口保护期间必须拒绝覆盖安装'
        finally:
            guard.stdin.close()
            guard.wait(timeout=10)
        digest = hashlib.sha256((data / 'shad.sqlite3').read_bytes()).hexdigest()
        run(install())
        assert hashlib.sha256((data / 'shad.sqlite3').read_bytes()).hexdigest() == digest
        run([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'])
        assert not exe.exists()
        assert hashlib.sha256((data / 'shad.sqlite3').read_bytes()).hexdigest() == digest
        result = {'passed': True, 'checks': ['silent install to Chinese/spaced path',
                  'installed EXE actual model and backup/restore', 'running upgrade blocked',
                  'running uninstall blocked', 'stopped upgrade preserves database',
                  'uninstall preserves external database'], 'cleanWindowsOffline': 'not tested'}
        result['checks'] += ['desktop-window installation mutex']
        result['installationIdentity'] = 'isolated acceptance ID' if args.isolated_identity else 'production ID'
        if args.previous_setup:
            result['checks'].append('0.6 browser edition upgrades to 0.7 desktop edition without changing database')
        (ROOT / 'verification/windows-installer/install-lifecycle.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Installer lifecycle passed.')
    finally:
        if exe.exists():
            run([exe, '--json', 'stop', '--data-dir', data], ok=False)
            run([uninstaller, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], ok=False)


if __name__ == '__main__':
    main()
