"""System tray icon: the backup's health as a colour, a status line on hover,
and a small menu."""
import logging
import time

import pystray

from . import icons, winutil
from .util import human

log = logging.getLogger(__name__)


def ago(t):
    if not t:
        return "never"
    s = time.time() - t
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s / 60:.0f} min ago"
    if s < 86400 * 2:
        return f"{s / 3600:.0f} h ago"
    return f"{s / 86400:.0f} days ago"


class _Icon(pystray.Icon):
    def _assert_icon_handle(self):
        # pystray saves every new icon to a temporary .ico file and loads it back; build it in memory instead
        if self._icon_handle:
            return
        self._icon_handle = winutil.icon_from_png(icons.png(self.icon), self.icon.width)


class Tray:
    def __init__(self, on_open, on_backup, can_back_up):
        self._size = winutil.small_icon_size()
        self._health = None
        self._icon = _Icon(
            "Pastoo",
            icon=icons.icon(self._size, "ok"),
            title="Pastoo",
            menu=pystray.Menu(
                pystray.MenuItem("Open Pastoo", lambda: on_open(), default=True),  # also a left-click
                pystray.MenuItem("Back up now", lambda: on_backup(), enabled=lambda _: can_back_up()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self.stop),
            ),
        )

    def run(self):
        """Show the icon; blocks until Exit is chosen."""
        self._icon.run()

    def stop(self):
        self._icon.stop()

    def show(self, health, detail):
        """health and detail as BackupService.health() gives them."""
        if health != self._health:
            self._health = health
            self._icon.icon = icons.icon(self._size, health)
        if detail is None:
            line = "No backups set up yet - open Pastoo to add a folder"
        elif health == "running":
            line = f"Backing up {detail['name']}"
            if detail.get("total"):
                line += f" - {detail['i']}/{detail['total']} bundles, {human(detail['sent'])}"
        elif health == "failed":
            line = f"{detail['name']}: the last backup failed"
        else:
            line = f"Last backup: {ago(detail['last_ok'])}" + (" - time for a backup" if health == "old" else "")
        self._icon.title = f"Pastoo\n{line}"[:127]     # Windows' tooltip limit
        self._icon.update_menu()

    def notify(self, title, message):
        if not self._icon.visible:
            return False
        try:
            self._icon.notify(message, f"Pastoo: {title}")
            return True
        except Exception:
            log.exception("Showing a notification failed")
            return False
