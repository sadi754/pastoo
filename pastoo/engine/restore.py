"""Getting files back - from the latest backup or from an old version of a bundle.

From the latest backup only the bundles holding the chosen files are
downloaded, only the chosen files are taken out of them, and each one is
checked against its sha1 before it is written. Old versions have no sha1 list;
zip's own checksum (CRC) is checked instead.
"""
import hashlib
import io
import os
import time
import zipfile
import zlib

from ..util import join
from . import blob


class RestoreError(Exception):
    pass


def select(state, wanted):
    """Relative paths in the backup matching `wanted` (files or folders, "" = everything)."""
    out = []
    for w in wanted:
        w = w.replace("\\", "/").strip("/")
        hits = [r for r in state["files"] if not w or r == w or r.startswith(w + "/")]
        if not hits:
            raise RestoreError(f"not in the backup: {w or '(everything)'}")
        out += hits
    return sorted(set(out))


def plan(state, rels):
    """{bundle key: [rel, ...]} for the chosen files."""
    where = {}
    for key, u in state["units"].items():
        for rel in u.get("members") or []:
            where[rel] = key
    by_unit = {}
    for rel in rels:
        if rel not in where:
            raise RestoreError(f"no bundle known for {rel} - run a backup once with this version first")
        by_unit.setdefault(where[rel], []).append(rel)
    return by_unit


def restore(job, state, dest, rels, to_dir, overwrite=False, emit=lambda kind, msg, **d: None):
    """Write the files under to_dir/<their relative path>. Existing files are
    skipped unless overwrite. Returns {"written", "skipped", "bad"}."""
    written, skipped, bad = 0, [], []
    by_unit = plan(state, rels)
    for n, (key, members) in enumerate(sorted(by_unit.items()), 1):
        u = state["units"][key]
        targets = {rel: os.path.join(to_dir, *rel.split("/")) for rel in members}
        todo = [rel for rel in members if overwrite or not os.path.exists(targets[rel])]
        skipped += [rel for rel in members if rel not in todo]
        if not todo:
            continue
        if u.get("parts"):              # one big file in parts: straight to the disk, checked as it comes
            emit("bundle", f"[{n}/{len(by_unit)}] {key}  (in parts)", key=key, files=1)
            rel = todo[0]
            ok = _write_parts(dest, u, targets[rel], state["files"][rel])
            if ok:
                written += 1
            else:
                bad.append(rel)
                emit("bad", f"   CHECK FAILED, not written: {rel}", rel=rel)
            continue
        data = dest.download(u["id"])
        emit("bundle", f"[{n}/{len(by_unit)}] {key}  ({len(todo)} files)", key=key, files=len(todo))
        z = zipfile.ZipFile(io.BytesIO(data)) if u["zip"] else None
        cut = len(u["dir"]) + 1 if u["dir"] else 0
        for rel in todo:
            content = z.read(rel[cut:]) if z else data
            if hashlib.sha1(content).hexdigest() != state["files"][rel]["sha1"]:
                bad.append(rel)
                emit("bad", f"   CHECK FAILED, not written: {rel}", rel=rel)
                continue
            os.makedirs(os.path.dirname(targets[rel]), exist_ok=True)
            with open(targets[rel], "wb") as f:
                f.write(content)
            mtime = state["files"][rel]["mtime"]
            os.utime(targets[rel], ns=(mtime, mtime))
            written += 1
    return {"written": written, "skipped": skipped, "bad": bad}


def _write_parts(dest, unit, target, known):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".pastoo-restoring"
    h = hashlib.sha1()
    with open(tmp, "wb") as f:
        for chunk in blob.chunks(dest, unit):
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != known["sha1"]:
        os.remove(tmp)
        return False
    os.replace(tmp, target)
    os.utime(target, ns=(known["mtime"], known["mtime"]))
    return True


# ---- old versions (_versions) ----

def version_kind(state, version, data):
    """(folder, is it a zip bundle) of an old version. Versions from before
    this was kept: a bundle with the same key today has the same kind; else a
    .zip that opens as one is taken for a bundle."""
    folder = version["dir"] if version.get("dir") is not None else version["key"].rpartition("/")[0]
    if version.get("zip") is not None:
        return folder, version["zip"]
    if version["key"] in state["units"] and state["units"][version["key"]].get("zip") is not None:
        return folder, state["units"][version["key"]]["zip"]
    return folder, version["key"].lower().endswith(".zip") and zipfile.is_zipfile(io.BytesIO(data))


def version_files(state, version, data):
    """[[relative path, size, mtime]] of what an old version holds."""
    folder, zipped = version_kind(state, version, data)
    if not zipped:
        return [[version["key"], len(data), None]]
    out = []
    for info in zipfile.ZipFile(io.BytesIO(data)).infolist():
        if not info.is_dir():
            out.append([join(folder, info.filename), info.file_size, time.mktime(info.date_time + (0, 0, -1))])
    return out


def restore_version(state, version, data, rels, to_dir, overwrite=False, emit=lambda kind, msg, **d: None):
    """Like restore(), from one old version already downloaded (data)."""
    folder, zipped = version_kind(state, version, data)
    z = zipfile.ZipFile(io.BytesIO(data)) if zipped else None
    cut = len(folder) + 1 if folder else 0
    written, skipped, bad = 0, [], []
    for rel in rels:
        target = os.path.join(to_dir, *rel.split("/"))
        if os.path.exists(target) and not overwrite:
            skipped.append(rel)
            continue
        try:
            if z:
                info = z.getinfo(rel[cut:])
                content = z.read(info)              # raises if the CRC does not match
                mtime = time.mktime(info.date_time + (0, 0, -1))
            else:
                content, mtime = data, None
        except (KeyError, zipfile.BadZipFile, zlib.error) as e:
            bad.append(rel)
            emit("bad", f"   CHECK FAILED, not written: {rel} ({e})", rel=rel)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(content)
        if mtime:
            os.utime(target, (mtime, mtime))
        written += 1
    return {"written": written, "skipped": skipped, "bad": bad}
