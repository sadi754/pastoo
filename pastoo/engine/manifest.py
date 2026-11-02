"""_backup.json: the whole job state on the destination, so a backup can be
continued or restored from any PC (with only the job's settings and the key)."""
import json

from .. import VERSION
from ..store import empty

FORMAT = 1


def build(job, state, stamp):
    return json.dumps({
        "format": FORMAT,
        "app": f"Pastoo {VERSION}",
        "created": stamp,
        "job": {"id": job.id, "name": job.name, "source": job.source, "remote_root": job.remote_root,
                "bundle_limit": job.bundle_limit, "big_file": job.big_file,
                "keep_versions": job.keep_versions, "keep_days": job.keep_days},
        "folders": state["folders"],
        "units": state["units"],
        # size, date and sha1 only: the journal numbers mean something on this PC alone
        "files": {r: {k: f[k] for k in ("size", "mtime", "sha1")} for r, f in state["files"].items()},
        "versions": state["versions"],
    }, ensure_ascii=False, indent=1).encode("utf8")


def fetch(job, dest):
    """The job state rebuilt from the destination's _backup.json, or None."""
    root = dest.find_root(job.remote_root)
    if root is None:
        return None
    entries = {e["name"]: e for e in dest.entries(root) if e["type"] != "folder"}
    if job.manifest_name not in entries:
        return None
    data = json.loads(dest.download(int(entries[job.manifest_name]["id"])))
    if data.get("format") != FORMAT:
        raise ValueError(f"{job.manifest_name} has format {data.get('format')}, this version reads {FORMAT}")
    state = empty()
    state.update(root_id=root, manifest_id=int(entries[job.manifest_name]["id"]),
                 index_id=int(entries[job.index_name]["id"]) if job.index_name in entries else None,
                 folders=data["folders"], units=data["units"], files=data["files"], versions=data["versions"])
    return state
