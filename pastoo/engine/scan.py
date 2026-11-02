"""What is here: the files a job backs up, and their sha1."""
import fnmatch
import hashlib
import os
import time

from ..util import join
from . import winfile

REREAD_DAYS = 7     # without a change journal, a file whose size and date stay the same is read again this often


def rules(job):
    """The job's skip rules, ready for matching: (folder names, relative paths, file patterns), all lower-case."""
    return ({n.lower() for n in job.skip_dir_names},
            {p.replace("\\", "/").strip("/").lower() for p in job.skip_paths},
            tuple(p.lower() for p in job.skip_files))


def _skipped_file(name, rel, paths, patterns):
    """None if the file is backed up, else the rule that skips it."""
    if rel.lower() in paths:
        return rel
    return next((p for p in patterns if fnmatch.fnmatch(name.lower(), p)), None)


def local_files(job):
    """{relative/path: (size, mtime_ns)} of everything the job backs up."""
    names, paths, patterns = rules(job)
    out = {}
    for dirpath, dirnames, filenames in os.walk(job.source):
        rel_dir = os.path.relpath(dirpath, job.source).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in names and join(rel_dir, d).lower() not in paths)
        for name in sorted(filenames):
            rel = join(rel_dir, name)
            if _skipped_file(name, rel, paths, patterns):
                continue
            st = os.stat(os.path.join(dirpath, name))
            out[rel] = (st.st_size, st.st_mtime_ns)
    return out


def measure(job, top=10):
    """For the Settings page: what the rules keep and what they skip (no hashing).
    {"files", "size", "skipped_files", "skipped_size", "skipped": [[what, files, size]] biggest first,
     "sizes": {rel: size} of the files kept}"""
    if not os.path.isdir(job.source):
        raise ValueError(f"no such folder: {job.source}")
    names, paths, patterns = rules(job)
    why = {"": None}            # folder -> the rule that skips it (or None)
    sizes, skipped = {}, {}
    for dirpath, dirnames, filenames in os.walk(job.source):
        rel_dir = os.path.relpath(dirpath, job.source).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        for d in dirnames:
            sub = join(rel_dir, d)
            why[sub] = why[rel_dir] or (f"{d}  (folders named so)" if d.lower() in names else
                                        sub if sub.lower() in paths else None)
        for name in filenames:
            rel = join(rel_dir, name)
            try:
                size = os.stat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
            reason = why[rel_dir] or _skipped_file(name, rel, paths, patterns)
            if reason:
                entry = skipped.setdefault(reason, [0, 0])
                entry[0] += 1
                entry[1] += size
            else:
                sizes[rel] = size
    return {"files": len(sizes), "size": sum(sizes.values()),
            "skipped_files": sum(v[0] for v in skipped.values()), "skipped_size": sum(v[1] for v in skipped.values()),
            "skipped": sorted(([k, *v] for k, v in skipped.items()), key=lambda x: -x[2])[:top], "sizes": sizes}


def sha1_of(path):
    h = hashlib.sha1()
    with winfile.open_read(path) as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unchanged(k, size, mtime, usn, now):
    """Can the remembered sha1 stand? Size and date alone aren't enough: some programs put the
    date back after writing (VeraCrypt containers) - the change journal's number shows those."""
    if k["size"] != size or k["mtime"] != mtime:
        return False
    if usn is not None:
        return usn == k.get("usn")      # no number remembered yet: read it once to have one
    return now - (k.get("read") or 0) < REREAD_DAYS * 86400


def hash_files(job, files, known, warn=None, now=None):
    """The file records {size, mtime, sha1, usn, read} of every file, and the files that couldn't be
    read because another program is writing to them (or for another reason) - those are left out.
    A remembered record is used again when _unchanged() says so; otherwise the file is read."""
    now = now or time.time()
    out, busy = {}, []
    for rel, (size, mtime) in files.items():
        path = os.path.join(job.source, rel)
        usn = winfile.usn(path)
        k = known.get(rel)
        if k and _unchanged(k, size, mtime, usn, now):
            out[rel] = dict(k, usn=usn)
            continue
        try:
            out[rel] = {"size": size, "mtime": mtime, "sha1": sha1_of(path), "usn": usn, "read": now}
        except FileNotFoundError:
            pass                            # gone since the folder was listed
        except OSError as e:
            busy.append(rel)
            if warn:
                why = "another program is writing to it" if isinstance(e, winfile.InUse) else e.strerror or e
                warn(f"   cannot read {rel} ({why}) - "
                     + ("its last backed-up copy stays" if rel in known else "it waits for the next backup"))
    return out, busy
