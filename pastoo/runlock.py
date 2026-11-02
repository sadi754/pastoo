"""One backup at a time - between the app and the command line too.
Windows releases the lock by itself if the process dies."""
import msvcrt
import os

from . import paths


class RunLock:
    def __init__(self, path=None):
        self.path = path or paths.RUN_LOCK
        self._file = None

    def acquire(self):
        """True if we hold the lock now; False if another backup is running."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        f = open(self.path, "a+")
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            f.close()
            return False
        self._file = f
        return True

    def release(self):
        if self._file:
            try:
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
