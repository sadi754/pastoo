"""System tray icon: the backup's health as a colour, a status line on hover,
and a small menu."""
import logging
import time

import pystray

from . import icons, winutil
from .i18n import t
from .util import human

log = logging.getLogger(__name__)


def ago(when):
    if not when:
        return t("never")
    s = time.time() - when
    if s < 90:
        return t("just now")
    if s < 3600:
        return t("{n} min ago", n=round(s / 60))
    if s < 86400 * 2:
        return t("{n} h ago", n=round(s / 3600))
    return t("{n} days ago", n=round(s / 86400))


class _Icon(pystray.Icon):
    def _assert_icon_handle(self):
        # pystray saves every new icon to a temporary .ico file and loads it back; build it in memory instead
        if self._icon_handle:
            return
        self._icon_handle = winutil.icon_from_png(icons.png(self.icon), self.icon.width)


class Tray:
    def __init__(self, on_open, on_backup, can_back_up, may_exit=lambda: True):
        self._size = winutil.small_icon_size()
        self._health = None
        self._icon = _Icon(
            "Pastoo",
            icon=icons.icon(self._size, "ok"),
            title="Pastoo",
            menu=pystray.Menu(
                # texts as functions: read when the menu opens, so a language change shows at once
                pystray.MenuItem(lambda _: t("Open Pastoo"), lambda: on_open(), default=True),  # also a left-click
                pystray.MenuItem(lambda _: t("Back up now"), lambda: on_backup(), enabled=lambda _: can_back_up()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(lambda _: t("Exit"), lambda: may_exit() and self.stop()),
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
            line = t("No backups set up yet - open Pastoo to add a folder")
        elif health == "running":
            line = t("Backing up {name}", name=detail["name"])
            if detail.get("total"):
                line += t(" - {i}/{total} bundles, {sent}", i=detail["i"], total=detail["total"], sent=human(detail["sent"]))
        elif health == "failed":
            line = t("{name}: the last backup failed", name=detail["name"])
        elif health == "held":
            line = t("{name}: an automatic backup waits for your OK", name=detail["name"])
        else:
            line = t("Last backup: {ago}", ago=ago(detail["last_ok"])) + (t(" - time for a backup") if health == "old" else "")
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
