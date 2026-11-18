"""OS-owned directory leases, shared by service and offline maintenance tools."""
import os


class DataDirectoryLease:
    def __init__(self, directory, filename='service.lock'):
        if filename not in ('service.lock', 'launcher.lock'):
            raise ValueError('Invalid lock filename')
        self.path = directory / filename
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            raise RuntimeError('当前进程已经持有数据目录锁。')
        self.handle = self.path.open('a+b')
        self.handle.seek(0, 2)
        if not self.handle.tell():
            self.handle.write(b'0'); self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close(); self.handle = None
            raise RuntimeError('数据目录正在使用（另一个 SHAD 服务或维护操作），请先停止对应服务，或选择独立目录。') from exc

    def release(self):
        if self.handle:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
