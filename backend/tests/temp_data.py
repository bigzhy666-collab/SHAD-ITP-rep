"""Managed temporary data; Windows scanners can briefly hold a closed log file."""
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def isolated_data():
    directory = tempfile.TemporaryDirectory(prefix='shad-test-')
    target = Path(directory.name).resolve()
    if not target.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise RuntimeError('Test data must remain inside the system temporary directory')
    try:
        yield directory.name
    finally:
        for attempt in range(20):
            try:
                directory.cleanup()
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.1)
