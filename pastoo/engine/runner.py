"""One backup run: scan() works out what changed, upload() sends it.

upload() reports through emit(kind, msg, **data) - msg is a ready log line,
data the same for the UI:
    made_root
    bundle      i, total, key, action ("adopted" | "up" | "updated"), size, files
    bundle_failed  i, total, key, error
    warn
    failed      keys
    cancelled
    pruned      count
    done        bundles, sent, minutes, report
"""
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass

from ..remote.base import RemoteError, Tree
from ..util import human, join
from . import bundle, manifest, report, winfile
from .plan import plan_units, signature
from .scan import hash_files, local_files

JOBS = 4                    # uploads at the same time; files.ir takes ~4 s per request

# An automatic backup stops for a look first (guard()) when it would delete this many files, or this
# share of them (at least GUARD_MIN_FILES) - files that only moved don't count - or change this share
# of them at once (at least GUARD_MIN_CHANGED): an emptied folder, ransomware, a slip of the mouse.
GUARD_DELETED, GUARD_SHARE, GUARD_MIN_FILES = 100, 0.20, 10
GUARD_CHANGED_SHARE, GUARD_MIN_CHANGED = 0.5, 50


class Cancelled(Exception):
    pass


class Failed(Exception):
    def __init__(self, keys):
        super().__init__(f"{len(keys)} bundles failed")
        self.keys = keys


class SourceMissing(Exception):
    """The job's folder isn't there (its drive not plugged in, the letter changed): a scan would
    make every file look deleted, so there is none."""


@dataclass
class Scan:
    files: dict             # rel -> (size, mtime_ns)
    hashes: dict            # rel -> sha1
    records: dict           # rel -> {size, mtime, sha1, usn, read}: the file list once this run is up
    units: dict             # key -> unit
    sigs: dict              # key -> signature
    todo: list              # bundle keys to upload
    stale: list             # bundle keys no longer planned (their files are in other bundles now)
    new: list
    changed: list
    gone: list
    first: bool             # nothing backed up yet
    busy: list              # files that couldn't be read (another program writing to them)
    waiting: list           # bundle keys that changed but hold a busy file: they go up next time

    @property
    def nothing(self):
        return not (self.todo or self.stale or self.new or self.changed or self.gone)

    def summary(self, job):
        total = human(sum(v[0] for v in self.files.values()))
        return (f"== {job.source}: {len(self.files)} files ({total}) in {len(self.units)} bundles; "
                f"new {len(self.new)}, changed {len(self.changed)}, deleted {len(self.gone)} -> "
                f"{len(self.todo)} bundles to upload"
                + (f", {len(self.stale)} old bundles to _versions" if self.stale else "")
                + (f"; {len(self.busy)} files in use by another program"
                   + (f", {len(self.waiting)} bundles wait for them" if self.waiting else "") if self.busy else ""))


def scan(job, state, warn=None):
    if not os.path.isdir(job.source):
        raise SourceMissing(f"the folder {job.source} isn't there - is its drive connected?")
    known = state["files"]
    found = local_files(job)
    now = time.time()
    records, busy = hash_files(job, found, known, warn, now)
    # a file another program is writing to isn't gone: its last backed-up copy stays as it was
    records.update({r: known[r] for r in busy if r in known})
    files = {r: (rec["size"], rec["mtime"]) for r, rec in records.items()}
    hashes = {r: rec["sha1"] for r, rec in records.items()}
    units = plan_units(job, files)
    sigs = {k: signature(u, hashes) for k, u in units.items()}
    todo = [k for k in units if state["units"].get(k, {}).get("sig") != sigs[k]]
    # an unchanged file isn't read, so whether it's in use only shows when its bundle has to be made
    for k in todo:
        for r in units[k]["files"]:
            if r in known and r not in busy and records[r].get("read") != now \
                    and not winfile.readable(os.path.join(job.source, r)):
                busy.append(r)
                if warn:
                    warn(f"   cannot read {r} (another program is writing to it) - its last backed-up copy stays")
    # a changed bundle can't be made without reading all its files: it waits for the next backup,
    # and its files keep their old records, so that backup still sees them as changed
    waiting = [k for k in todo if any(r in busy for r in units[k]["files"])]
    for k in waiting:
        for r in units[k]["files"]:
            if r in known:
                records[r] = known[r]
            else:
                records.pop(r, None)
    return Scan(
        files=files, hashes=hashes, records=records, units=units, sigs=sigs,
        todo=[k for k in todo if k not in waiting],
        # retired only once nothing waits: a waiting file's last copy may be in one of them
        stale=[] if waiting else [k for k in state["units"] if k not in units],
        # what this run backs up (not what waits)
        new=[r for r in records if r not in known],
        changed=[r for r in records if r in known and known[r]["sha1"] != records[r]["sha1"]],
        gone=sorted(r for r in known if r not in files),
        first=not known,
        busy=sorted(busy),
        waiting=waiting,
    )


def changes(state, sc):
    """What scan() found, file by file, for the preview and the History page
    (call before upload(): it replaces the state's file list).
    Files are [path, size, bundle]; bundles are [key, files, size before zipping]."""
    now = {rel: key for key, u in sc.units.items() for rel in u["files"]}
    before = {rel: key for key, u in state["units"].items() for rel in (u.get("members") or [])}
    return {
        "first": sc.first,
        "new": [[r, sc.files[r][0], now[r]] for r in sorted(sc.new)],
        "changed": [[r, sc.files[r][0], now[r]] for r in sorted(sc.changed)],
        "deleted": [[r, state["files"][r]["size"], before.get(r)] for r in sc.gone],
        "bundles": [[k, len(sc.units[k]["files"]), sum(sc.files[f][0] for f in sc.units[k]["files"])]
                    for k in sorted(sc.todo)],
        "stale": sorted(sc.stale),
        "busy": sc.busy,                        # in use by another program: their last copy stays
        "waiting": sorted(sc.waiting),          # changed bundles that hold one of them: next time
    }


def unit_record(eid, sig, size, unit, parts=False):
    return {"id": eid, "sig": sig, "size": size, "dir": unit["dir"], "name": unit["name"],
            "zip": unit["zip"], "members": unit["files"], "parts": parts}


def annotate(state, sc):
    """Bundles imported from the first script have no member list; an
    unchanged bundle has exactly the members of today's plan."""
    filled = False
    for key, u in state["units"].items():
        if u.get("members") is None and key in sc.units and u["sig"] == sc.sigs[key]:
            state["units"][key] = unit_record(u["id"], u["sig"], u["size"], sc.units[key])
            filled = True
    return filled


def needs_run(state, sc):
    return not sc.nothing or not state["manifest_id"]


def really_deleted(state, sc):
    """The deleted files whose content isn't here under another name (moved or renamed ones are)."""
    here = {sc.hashes[r] for r in sc.new}
    return [r for r in sc.gone if state["files"][r]["sha1"] not in here]


def guard(state, sc):
    """Why an automatic backup should wait for you to look first, or None."""
    total = len(state["files"])
    deleted = len(really_deleted(state, sc))
    if deleted >= GUARD_DELETED or (deleted >= GUARD_MIN_FILES and deleted >= GUARD_SHARE * total):
        return f"{deleted} of {total} files deleted"
    changed = len(sc.changed)
    if changed >= GUARD_MIN_CHANGED and changed >= GUARD_CHANGED_SHARE * total:
        return f"{changed} of {total} files changed at once"
    return None


def remember(state, sc):
    """A run with nothing to upload still keeps what it learned (the files' journal numbers,
    when they were read), so the next scan needn't read them again. True if anything was new."""
    if sc.records == state["files"]:
        return False
    state["files"] = dict(sc.records)
    return True


def prune(job, state, dest, now, emit):
    """Delete replaced bundles that are both older than keep_days and not one
    of the keep_versions newest of their bundle; then their empty run folders."""
    by_key = {}
    for v in state["versions"]:
        by_key.setdefault(v["key"], []).append(v)
    doomed = []
    for versions in by_key.values():
        versions.sort(key=lambda v: v["created"], reverse=True)
        doomed += [v for v in versions[job.keep_versions:] if now - v["created"] > job.keep_days * 86400]
    for v in doomed:
        try:
            dest.delete(v["id"])
        except RemoteError as e:
            emit("warn", f"    old version {v['stamp']}/{v['key']} not deleted: {e}")
            continue
        state["versions"].remove(v)
    live_stamps = {v["stamp"] for v in state["versions"]}
    for stamp in sorted({v["stamp"] for v in doomed} - live_stamps):
        top = join(job.versions_dir, stamp)
        if top in state["folders"]:
            try:
                dest.delete(state["folders"][top])
            except RemoteError as e:
                emit("warn", f"    {top} not deleted: {e}")
                continue
            for rel in [r for r in state["folders"] if r == top or r.startswith(top + "/")]:
                del state["folders"][rel]
    if doomed:
        emit("pruned", f"   {len(doomed)} old versions deleted (older than {job.keep_days} days, "
                       f"beyond the {job.keep_versions} newest)", count=len(doomed))


def upload(job, state, sc, dest, save, emit, jobs=JOBS, cancel=None, clock=time.time):
    """Send what scan() found. save() persists state (called after every
    bundle, so a stopped run continues where it stopped). Raises Cancelled
    or Failed; on Failed the old file list stays, so the next run retries
    those bundles and still reports the same changes."""
    cancel = cancel or threading.Event()
    now = clock()
    stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime(now))
    tree = Tree(dest, state, job.remote_root,
                on_made_root=lambda: emit("made_root", f'made the folder "{job.remote_root}" on {dest.label}'))
    lock = threading.Lock()     # folder lookups and state writes one at a time

    def retire(key, old):
        """The replaced bundle into _versions/<this run>/<its folder>."""
        u = old if old.get("dir") is not None else sc.units.get(key) or {"dir": key.rpartition("/")[0]}
        with lock:
            vfid = tree.folder(join(join(job.versions_dir, stamp), u["dir"]))
        try:
            dest.move(old["id"], vfid)
        except RemoteError as e:
            emit("warn", f"    {key}: old version not moved to {job.versions_dir}: {e}")
            return None
        zipped = old.get("zip") if old.get("zip") is not None else (sc.units[key]["zip"] if key in sc.units else None)
        return {"id": old["id"], "key": key, "stamp": stamp, "created": now, "size": old["size"],
                "dir": u["dir"], "zip": zipped, "parts": bool(old.get("parts"))}

    def work(key):
        u = sc.units[key]
        if not u["zip"] and sc.files[u["files"][0]][0] > job.part_size:
            return work_in_parts(key, u)
        data = bundle.build(job, u)
        with lock:
            fid = tree.folder(u["dir"])
            old = state["units"].get(key)
            if not old:
                eid = tree.existing(fid, u["name"], len(data))
                if eid:
                    return "adopted", eid, len(data), None, False
        if cancel.is_set():
            raise Cancelled()
        eid = dest.upload(u["name"], data, fid)
        version = retire(key, old) if old else None
        return ("updated" if old else "up"), eid, len(data), version, False

    def work_in_parts(key, u):
        """A file bigger than one upload may be: a folder "<name>.parts" with part001, part002 ...
        read from the disk one part at a time."""
        with lock:
            fid = tree.folder(u["dir"])
            old = state["units"].get(key)
            known = {old["id"]} if old else set()
            leftovers = [int(e["id"]) for e in tree.children(fid)
                         if e["type"] == "folder" and e["name"] == u["name"] + ".parts" and int(e["id"]) not in known]
        for lid in leftovers:           # from a run that stopped half-way
            dest.delete(lid)
        if cancel.is_set():
            raise Cancelled()
        pid = dest.make_folder(u["name"] + ".parts", fid)
        size = n = 0
        with winfile.open_read(os.path.join(job.source, u["files"][0])) as f:
            while chunk := f.read(job.part_size):
                if cancel.is_set():
                    dest.delete(pid)
                    raise Cancelled()
                n += 1
                dest.upload(f"part{n:03d}", chunk, pid)
                size += len(chunk)
        version = retire(key, old) if old else None
        return ("updated" if old else "up"), pid, size, version, True

    sent, failed, uploaded = 0, [], []
    started = time.time()
    total = len(sc.todo)
    pool = ThreadPoolExecutor(jobs)
    try:
        pending = {pool.submit(work, k): k for k in sc.todo}
        i = 0
        while pending:
            done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            if cancel.is_set():
                raise Cancelled()
            for fut in done:
                key = pending.pop(fut)
                i += 1
                try:
                    action, eid, size, version, parts = fut.result()
                except Cancelled:
                    raise
                except (RemoteError, OSError) as e:
                    failed.append(key)
                    emit("bundle_failed", f"[{i}/{total}] FAILED  {key}: {e}", i=i, total=total, key=key,
                         error=str(e))
                    continue
                n = len(sc.units[key]["files"])
                with lock:
                    state["units"][key] = unit_record(eid, sc.sigs[key], size, sc.units[key], parts)
                    if version:
                        state["versions"].append(version)
                    save()
                uploaded.append(key)
                if action == "adopted":
                    msg = f"[{i}/{total}] already on {dest.label}  {key}"
                else:
                    sent += size
                    msg = f"[{i}/{total}] {'up     ' if action == 'up' else 'updated'} {human(size):>9}  {n:>4} files  {key}"
                emit("bundle", msg, i=i, total=total, key=key, action=action, size=size, files=n)
    except (Cancelled, KeyboardInterrupt):
        pool.shutdown(wait=False, cancel_futures=True)
        with lock:
            save()
        emit("cancelled", "stopped - run again to continue where it stopped")
        raise Cancelled()
    pool.shutdown()

    if failed:
        emit("failed", f"== {len(failed)} bundles failed - run again later:\n"
             + "\n".join(f"   {k}" for k in failed), keys=failed)
        raise Failed(failed)

    for key in sc.stale:        # their files are in other bundles now
        version = retire(key, state["units"][key])
        if version:
            state["versions"].append(version)
        else:
            try:
                dest.trash(state["units"][key]["id"])
            except RemoteError:
                pass
        del state["units"][key]
    prune(job, state, dest, now, emit)
    state["files"] = dict(sc.records)
    save()

    nice = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    report_path = None
    if not sc.nothing:
        text = report.changes_report(job, nice, sc.new, sc.changed, sc.gone, sorted(uploaded), sc.stale, sc.first)
        cfid = tree.folder(job.changes_dir)
        dest.upload(stamp + ".txt", text.encode("utf8"), cfid)
        report_path = f"{job.changes_dir}/{stamp}.txt"
        try:                    # only the newest keep_reports stay (files.ir counts files; History keeps them all)
            reports = sorted((e for e in dest.entries(cfid) if e["type"] != "folder"), key=lambda e: e["name"])
            for e in reports[:-job.keep_reports]:
                dest.delete(int(e["id"]))
        except RemoteError as e:
            emit("warn", f"    old reports not deleted: {e}")
    root = tree.root()
    old_ids = [state["index_id"], state["manifest_id"]]
    state["index_id"] = dest.upload(job.index_name, report.index_text(job, nice, sc.units, sc.files).encode("utf8"),
                                    root)
    state["manifest_id"] = dest.upload(job.manifest_name, manifest.build(job, state, nice), root)
    save()
    for eid in old_ids:         # the old _index.txt / _backup.json: gone for good, not into the trash
        if eid:
            try:
                dest.delete(eid)
            except RemoteError:
                pass
    minutes = (time.time() - started) / 60
    emit("done", f"== done: {len(uploaded)} bundles ({human(sent)}) in {minutes:.1f} min"
         + (f", report {report_path}" if report_path else ""),
         bundles=len(uploaded), sent=sent, minutes=minutes, report=report_path)
    return {"bundles": len(uploaded), "sent": sent, "report": report_path}
