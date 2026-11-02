"""The app's own log in %LOCALAPPDATA%\\Pastoo (and the terminal, when there is one).
The lines of each backup go to backup.log (backuplog.py)."""
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import paths

log = logging.getLogger("pastoo")


def setup(filename, debug=False):
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    handlers = [RotatingFileHandler(os.path.join(paths.DATA_DIR, filename), maxBytes=1_000_000, backupCount=1,
                                    encoding="utf-8")]
    if sys.stderr:  # pythonw.exe has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Without a console, crashes would vanish silently - write them to the log.
    sys.excepthook = lambda *exc: log.critical("Unhandled error", exc_info=exc)
    threading.excepthook = lambda a: log.critical("Unhandled error in thread %s", a.thread.name,
                                                  exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
