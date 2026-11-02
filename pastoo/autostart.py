"""Start with Windows: an entry in HKCU\\...\\Run (no admin rights needed) that
starts the app in the tray when you sign in.

If the Pastoo folder moves, the entry is pointed at the new place on the next
start; an entry for another copy that is still there (e.g. the installed one,
while a copy from the source runs) stays.
"""
import os
import sys
import winreg

from . import paths

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "Pastoo"


def _program():
    if paths.FROZEN:
        return sys.executable
    return os.path.join(os.path.dirname(sys.executable), "pythonw.exe")     # no console window


def command():
    if paths.FROZEN:
        return f'"{_program()}" --minimized'
    # start.pyw so the package is found from any folder
    return f'"{_program()}" "{os.path.join(paths.BUNDLE, "start.pyw")}" --minimized'


def _target(entry):
    """The program a Run entry starts: its first part, usually in quotes."""
    entry = entry.strip()
    if entry.startswith('"'):
        end = entry.find('"', 1)
        return entry[1:end] if end > 1 else None
    return entry.split(" ", 1)[0] or None


def _is_this_program(path):
    try:
        return os.path.samefile(path, _program())
    except OSError:
        return False


def registered(name=None):
    """The command of a Run entry (ours unless named), or None."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as key:
            return winreg.QueryValueEx(key, name or NAME)[0]
    except OSError:
        return None


def enabled():
    return registered() is not None


def set_enabled(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        elif registered() is not None:
            winreg.DeleteValue(key, NAME)


def refresh():
    """At start: if Pastoo starts with Windows from a place that's gone (the folder moved), point it
    here. Another copy that is still there keeps the entry - this one may be a portable copy, or a
    build being tested."""
    if paths.INSTANCE:
        return      # a separate copy, started next to the one in use
    entry = registered()
    if entry is None or entry == command():
        return
    target = _target(entry)
    if target is None or not os.path.isfile(target) or _is_this_program(target):
        set_enabled(True)
