"""Download bundles and check every file in them against the sha1 taken at backup time."""
import hashlib
import io
import zipfile
import zlib

from ..remote.base import RemoteError
from . import blob


def verify(state, dest, keys, emit=lambda kind, msg, **d: None, cancel=None):
    """Returns {"bundles", "files", "problems": [[bundle, file or "", what]]}."""
    problems, files = [], 0
    for i, key in enumerate(keys, 1):
        if cancel is not None and cancel.is_set():
            break
        u = state["units"][key]
        if u.get("parts"):              # one big file in parts: checked as it streams in
            found, members = _verify_parts(dest, key, u, state), u.get("members") or []
            files += len(members)
            problems += found
            emit("bundle", f"[{i}/{len(keys)}] {'OK     ' if not found else 'PROBLEM'}  {key}  (in parts)",
                 i=i, total=len(keys), key=key, bad=len(found))
            continue
        try:
            data = dest.download(u["id"])
        except RemoteError as e:
            problems.append([key, "", f"download failed: {e}"])
            emit("bundle", f"[{i}/{len(keys)}] DOWNLOAD FAILED  {key}: {e}", i=i, total=len(keys), key=key, bad=1)
            continue
        found = []
        if len(data) != u["size"]:
            found.append([key, "", f"{len(data)} bytes, expected {u['size']}"])
        members = u.get("members") or []
        if u.get("zip"):
            cut = len(u["dir"]) + 1 if u["dir"] else 0
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
                for rel in members:
                    try:
                        ok = hashlib.sha1(z.read(rel[cut:])).hexdigest() == state["files"][rel]["sha1"]
                    except KeyError:
                        found.append([key, rel, "missing from the zip"])
                        continue
                    except (zipfile.BadZipFile, zlib.error) as e:
                        found.append([key, rel, f"damaged ({e})"])
                        continue
                    if not ok:
                        found.append([key, rel, "content differs"])
            except zipfile.BadZipFile as e:
                found.append([key, "", f"not a readable zip ({e})"])
        elif members and hashlib.sha1(data).hexdigest() != state["files"][members[0]]["sha1"]:
            found.append([key, members[0], "content differs"])
        files += len(members)
        problems += found
        emit("bundle", f"[{i}/{len(keys)}] {'OK     ' if not found else 'PROBLEM'}  {key}  ({len(members)} files)",
             i=i, total=len(keys), key=key, bad=len(found))
    return {"bundles": len(keys), "files": files, "problems": problems}


def _verify_parts(dest, key, u, state):
    h, size = hashlib.sha1(), 0
    try:
        for chunk in blob.chunks(dest, u):
            h.update(chunk)
            size += len(chunk)
    except RemoteError as e:
        return [[key, "", f"download failed: {e}"]]
    found = []
    if size != u["size"]:
        found.append([key, "", f"{size} bytes, expected {u['size']}"])
    members = u.get("members") or []
    if members and h.hexdigest() != state["files"][members[0]]["sha1"]:
        found.append([key, members[0], "content differs"])
    return found
