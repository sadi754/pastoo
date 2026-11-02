"""Where Pastoo keeps its files.

Data (database, settings, logs) goes to %LOCALAPPDATA%\\Pastoo; the files.ir
key is in Windows Credential Manager (keystore.py).
"""
import os
import sys

LOCAL = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
DATA_DIR = os.path.join(LOCAL, "Pastoo")
DB_FILE = os.path.join(DATA_DIR, "state.db")
LOG_FILE = os.path.join(DATA_DIR, "backup.log")         # every run's lines, from the app and the command line
APP_LOG = os.path.join(DATA_DIR, "app.log")             # the app itself (errors, start/stop)
RUN_LOCK = os.path.join(DATA_DIR, "run.lock")           # one backup at a time, app or command line
# PASTOO_INSTANCE=<suffix> runs a separate copy, e.g. to check a build next to the one in use
INSTANCE = os.environ.get("PASTOO_INSTANCE", "")
INSTANCE_FILE = os.path.join(DATA_DIR, f"instance{INSTANCE}.json")  # how a second launch finds the running app

FROZEN = bool(getattr(sys, "frozen", False))            # running as Pastoo.exe
if FROZEN:
    BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BUNDLE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the project folder
WEB_DIR = os.path.join(BUNDLE, "web")
