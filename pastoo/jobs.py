"""Backup jobs: what to back up, where to, and how. They live in settings.json
(settings.py) and are edited on the Settings page."""
import re
from dataclasses import dataclass, field

from . import settings

EDITABLE = ("name", "source", "remote_root", "skip_dir_names", "skip_paths", "skip_files",
            "bundle_limit", "big_file", "keep_versions", "keep_days", "schedule", "schedule_time", "schedule_hours")
SCHEDULES = ("off", "daily", "hours")


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    source: str                         # local folder
    remote_root: str                    # top-level folder on the destination
    skip_dir_names: tuple = ()          # folder names skipped anywhere (any case)
    skip_paths: tuple = ()              # paths relative to source, with / (any case)
    skip_files: tuple = ()              # file name patterns, e.g. *.mkv (any case)
    bundle_limit: int = 10 << 20        # a folder this size or smaller = one zip
    big_file: int = 5 << 20             # loose files this big go up on their own
    keep_versions: int = 5              # a replaced bundle is deleted only when it is older than
    keep_days: int = 30                 # keep_days AND not one of the keep_versions newest of its bundle
    schedule: str = "off"               # automatic backups (while the app runs): "off" | "daily" | "hours"
    schedule_time: str = "21:00"        # "daily": at this time (HH:MM, local)
    schedule_hours: int = 6             # "hours": this long after the last backup
    part_size: int = 45 << 20           # bigger files go up in parts (files.ir's limit per file; from the plan)
    keep_reports: int = 50              # _changes/*.txt kept on files.ir (the History page keeps them all)
    changes_dir: str = "_changes"
    index_name: str = "_index.txt"
    manifest_name: str = "_backup.json"
    versions_dir: str = "_versions"     # replaced bundles go to _versions/<run time>/<their folder>
    stored_ext: frozenset = field(default_factory=lambda: frozenset(
        {".zip", ".rar", ".7z", ".gz", ".fzz", ".fzpz", ".png", ".jpg", ".jpeg", ".mp3", ".mp4"}))

    def to_dict(self):
        return {"id": self.id, **{k: list(v) if isinstance(v, (tuple, frozenset)) else v
                                  for k, v in ((k, getattr(self, k)) for k in EDITABLE)}}

    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], **{k: tuple(d[k]) if isinstance(d.get(k), list) else d[k]
                                  for k in EDITABLE + ("part_size",) if k in d})


def new_id(name, taken):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "job"
    job_id, n = base, 2
    while job_id in taken:
        job_id, n = f"{base}-{n}", n + 1
    return job_id


def load():
    data = settings.load()
    return [Job.from_dict({**d, "part_size": settings.part_size(data)}) for d in data["jobs"]]


JOBS = load()


def reload():
    global JOBS
    JOBS = load()
    return JOBS


def get(job_id):
    for job in JOBS:
        if job.id == job_id:
            return job
    raise KeyError(f"no job {job_id!r} (have: {', '.join(j.id for j in JOBS)})")
