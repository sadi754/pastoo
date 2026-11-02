"""The desktop app: backup service + local web server + tray icon + window."""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request

from . import VERSION, autostart, logs, paths, winutil
from .service import BackupService
from .server import WebServer
from .tray import Tray
from .util import human

log = logging.getLogger(__name__)

STATUS_EVERY = 60           # seconds between tray refreshes ("Last backup: 3 h ago")
REMIND_EVERY = 86400        # at most one "time for a backup" notification a day (first one a minute after start)


def _self_command():
    """How to start another copy of ourselves (the window runs as a separate process)."""
    if paths.FROZEN:
        return [sys.executable]
    return [sys.executable, "-m", "pastoo"]


class WindowProcess:
    def __init__(self):
        self.url = ""
        self._process = None
        self._lock = threading.Lock()

    def open(self):
        """Open the window, or bring it to the front."""
        with self._lock:
            if self._process and self._process.poll() is None:
                for hwnd in winutil.windows_of(self._process.pid):
                    winutil.bring_to_front(hwnd)
                return
            self._process = subprocess.Popen([*_self_command(), "--window", self.url], cwd=paths.BUNDLE)

    def close(self):
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    log.warning("The window process did not exit in time")


def _wake_running_instance():
    """The app is already running: ask it to show its window, then quit."""
    try:
        with open(paths.INSTANCE_FILE, encoding="utf-8") as f:
            info = json.load(f)
        winutil.allow_any_foreground()
        url = f"http://127.0.0.1:{info['port']}/api/show?token={info['token']}"
        urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=5)
    except (OSError, ValueError, KeyError) as e:
        log.warning("Pastoo is already running but did not answer: %s", e)


def tray_listener(tray, refresh):
    """A service listener that keeps the tray icon and its notifications up to date."""
    def on_event(message):
        if message["type"] == "job":
            refresh()
            return
        if message["type"] != "run":        # "task" (restore / verify), "usage": nothing for the tray
            return
        run_info = message["run"]
        if run_info["phase"] != "done":
            tray.show("running", run_info)
            return
        result = run_info["result"]
        if result["status"] == "ok":
            tray.notify("Backup finished", f"{run_info['name']}: {result.get('bundles', 0)} bundles, "
                                           f"{human(result.get('sent', 0))} uploaded")
        elif result["status"] in ("failed", "busy"):
            tray.notify("Backup failed", f"{run_info['name']}: {result.get('error', 'see the log')}")
    return on_event


def run(minimized=False, debug=False):
    logs.setup("app.log", debug)
    winutil.enable_dpi_awareness()
    if not winutil.claim_single_instance():
        _wake_running_instance()
        return
    log.info("Pastoo %s starting (data in %s)", VERSION, paths.DATA_DIR)
    winutil.set_app_id()
    try:
        autostart.refresh()     # the project moved? point "start with Windows" here
    except OSError:
        log.warning("Couldn't check the Windows start-up entry", exc_info=True)

    service = BackupService()
    window = WindowProcess()
    server = WebServer(service, on_show=window.open)
    window.url = server.url
    tray = Tray(on_open=window.open,
                on_backup=lambda: service.start(service.jobs()[0].id),
                can_back_up=lambda: service.run is None and bool(service.jobs()))
    stopping = threading.Event()

    def refresh():
        try:
            tray.show(*service.health())
        except Exception:
            log.exception("Refreshing the tray failed")

    service.listeners.append(tray_listener(tray, refresh))

    def remind():
        """Not backed up for a while and files changed: say so (at most once a day)."""
        for name, age, changed in service.reminder():
            since = f"{age:.0f} days since the last backup" if age is not None else "never backed up"
            tray.notify("Time for a backup", f"{name}: {since}, {changed} files changed. "
                                             "Right-click the tray icon -> Back up now.")

    def keep_fresh():
        last_reminder = 0.0
        while not stopping.wait(STATUS_EVERY):
            if service.run or service.task:
                continue
            refresh()
            if time.time() - last_reminder > REMIND_EVERY:
                last_reminder = time.time()
                try:
                    remind()
                except Exception:
                    log.exception("The backup reminder failed")

    server.start()
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    with open(paths.INSTANCE_FILE, "w", encoding="utf-8") as f:
        json.dump({"port": server.port, "token": server.token}, f)
    refresh()
    threading.Thread(target=keep_fresh, name="tray-status", daemon=True).start()
    threading.Thread(target=service.refresh_usage, name="usage", daemon=True).start()   # files.ir space for the window
    try:
        if not minimized:
            window.open()
        tray.run()          # blocks until "Exit" in the tray menu
    finally:
        log.info("Pastoo exiting")
        stopping.set()
        service.stop()      # a running backup stops and saves; the next run continues it
        service.wait_idle(timeout=15)
        server.stop()
        window.close()
        try:
            os.remove(paths.INSTANCE_FILE)
        except OSError:
            pass
