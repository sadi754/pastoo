"""settings.json in %LOCALAPPDATA%\\Pastoo: the backup jobs and the app's options.

Until it is first saved, the defaults below apply (and there are no jobs).
"""
import json
import os

from . import paths

MB, GB = 1 << 20, 1 << 30
# files.ir's Free plan (2026-10-17): until the plan has been read from files.ir.
# space: bytes; files: the most files the account may hold; file: the biggest single upload.
FREE = {"name": "Free", "space": 5 * GB, "files": 1000, "file": 50 * MB}

DEFAULTS = {
    "reminder_days": 7,             # tray turns yellow / a reminder after this many days without a backup
    "language": "auto",             # the window, tray and notifications: "auto" (as Windows) | "en" | "fa"
    "start_with_windows": False,
    # the account's limits drive the usage bars and the part size:
    "limits_mode": "auto",          # "auto": read from files.ir (detected_limits) | "custom": custom_limits
    "detected_limits": None,        # {name, space, files, file, checked} - the plan as files.ir last told it
    "custom_limits": dict(FREE, name="Set by hand"),
}


def limits(data=None):
    """The limits in force: set by hand, or as files.ir said, or Free until it has."""
    data = data or load()
    if data["limits_mode"] == "custom":
        return data["custom_limits"]
    return data["detected_limits"] or FREE


def part_size(data=None):
    """Bigger files go up in parts of this size: 90% of the biggest single upload (45 MB on Free)."""
    return limits(data)["file"] * 9 // 10

# A new job starts with no skips (so nothing looks carried over from another
# job); the Settings page's "+ Add common skips" adds these.
NEW_JOB_SKIPS = {"skip_dir_names": [], "skip_paths": [], "skip_files": []}
COMMON_SKIPS = {
    "skip_dir_names": [".venv", "venv", "__pycache__", "node_modules", ".pio", ".history", ".cache"],
    "skip_files": ["thumbs.db", "desktop.ini", "~$*", "*.tmp"],
}


def file_path():
    return os.path.join(paths.DATA_DIR, "settings.json")


def load():
    try:
        with open(file_path(), encoding="utf8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"jobs": []}
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    return data


def save(data):
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    tmp = file_path() + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, file_path())
