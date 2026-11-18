"""Frozen entry point. Serve and maintenance use the same installed executable."""
import sys

# Keep a reference until process exit. Inno Setup checks the same session mutex
# before updating/uninstalling, and never force-closes a detection or backup.
_installation_mutex = None


def protect_installation():
    global _installation_mutex
    if sys.platform == 'win32' and _installation_mutex is None:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        _installation_mutex = kernel.CreateMutexW(None, False, r'Local\SHAD.LocalService')
        if not _installation_mutex:
            raise ctypes.WinError(ctypes.get_last_error())


def main(args=None):
    protect_installation()
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    args = list(sys.argv[1:] if args is None else args)
    human = [] if '--json' in args else ['--human']
    if '--json' in args:
        args.remove('--json')
    action = args.pop(0) if args else 'start'
    if action == 'guard':
        # Hold the installation mutex for the desktop window lifetime.
        # The parent keeps stdin open; OS pipe cleanup releases it after a crash.
        sys.stdin.buffer.read()
        return 0
    if action == 'serve':
        from backend.__main__ import main as serve
        return serve(args)
    if action in ('start', 'stop', 'status'):
        from backend.desktop import main as desktop
        return desktop([action, *human, *args])
    if action in ('backup', 'restore'):
        from backend.maintenance import main as maintenance
        return maintenance([action, *human, *args])
    print('用法：SHAD.exe [start|stop|status|backup|restore] [选项]', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
