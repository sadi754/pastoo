"""The window: a native desktop window (Edge WebView2) showing the web UI.

It runs as its own process, like NetMon's: closing the window ends that
process and frees the browser engine's memory; the app keeps running in the tray.
"""
import os

import webview

from . import icons, winutil

BACKGROUND = "#0a0e14"
CAPTION_RGB = (13, 18, 27)  # matches the top bar (#0d121b)


class WindowApi:
    """Called from the page as window.pywebview.api.<name>()."""

    def pick_folder(self, start=""):
        """Windows' folder dialog; the chosen folder or None."""
        kind = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        chosen = webview.windows[0].create_file_dialog(kind, directory=start if os.path.isdir(start) else "")
        return chosen[0] if chosen else None


def run(url):
    winutil.set_app_id()
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    # PASTOO_WINDOW_HIDDEN=1: build check - make the window without showing it
    window = webview.create_window("Pastoo", url, width=1000, height=720, min_size=(760, 540),
                                   background_color=BACKGROUND, js_api=WindowApi(),
                                   hidden=os.environ.get("PASTOO_WINDOW_HIDDEN") == "1")
    window.events.shown += _decorate
    webview.start()


def _decorate():
    """Dark title bar and our own icon instead of Python's."""
    small, big = winutil.small_icon_size(), winutil.big_icon_size()
    small_icon = winutil.icon_from_png(icons.png(icons.icon(small)), small)
    big_icon = winutil.icon_from_png(icons.png(icons.icon(big)), big)
    for hwnd in winutil.windows_of(os.getpid()):
        winutil.style_dark_window(hwnd, CAPTION_RGB)
        winutil.set_window_icon(hwnd, small_icon, big_icon)
