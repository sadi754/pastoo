"""backup.log: the lines of every run, from the app and the command line alike."""
import os
import threading
import time

from . import paths

_lock = threading.Lock()


def write(msg, echo=False):
    with _lock:
        if echo:
            print(msg, flush=True)
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        with open(paths.LOG_FILE, "a", encoding="utf8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
