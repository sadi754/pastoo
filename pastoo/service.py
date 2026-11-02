"""The app's side of the engine: job status, "check for changes", and one
heavy job at a time in a background thread - a backup, a restore or a verify.

Listeners get plain dicts (called from worker threads):
    {"type": "job", "job": status(job)}              a job's card changed
    {"type": "run", "run": run_info, "line": str}    progress of the running backup
    {"type": "task", "task": task_info, "line": str} progress of a restore or verify
"""
import collections
import logging
import os
import random
import threading
import time

from . import autostart, backuplog, jobs as jobs_mod, keystore, settings as settings_mod
from .settings import GB, MB
from .engine import blob, restore as restore_mod, runner
from .engine.plan import plan_units
from .engine.scan import measure
from .engine.verify import verify
from .remote.base import RemoteError
from .remote.filesir import FilesIr, load_key
from .runlock import RunLock
from .store import Store

log = logging.getLogger(__name__)

LOG_LINES = 200             # lines of the current run kept for a window that opens late


class BackupService:
    def __init__(self, store_factory=Store, destination_factory=None, lock_factory=RunLock):
        self.store_factory = store_factory          # one Store per thread (SQLite connections are per thread)
        self.destination_factory = destination_factory or (lambda: FilesIr(load_key(), on_retry=self._line))
        self.key_check = lambda key: FilesIr(key).find_root("Pastoo key check")   # raises if files.ir refuses
        self.lock_factory = lock_factory
        self.listeners = []
        self.pending = {}           # job id -> what "check for changes" found
        self.run = None             # info about the running backup, None when idle
        self.task = None            # info about a running restore or verify
        self.last_usage = None      # usage() as last seen
        self._cancel = threading.Event()
        self._busy = threading.Lock()   # one backup / restore / verify at a time (in this app)
        self._versions = collections.OrderedDict()     # version id -> downloaded bytes (a few, for browsing)

    # ---- status ----

    def jobs(self):
        return jobs_mod.JOBS

    def status(self, job):
        store = self.store_factory()
        try:
            state = store.load(job)
            runs = store.runs(job, limit=50)
        finally:
            store.close()
        last = runs[0] if runs else None
        last_ok = next((r for r in runs if r["status"] in ("ok", "nothing")), None)
        return {
            "id": job.id, "name": job.name, "source": job.source, "remote_root": job.remote_root,
            "files": len(state["files"]),
            "size": sum(f["size"] for f in state["files"].values()),
            "bundles": len(state["units"]),
            "remote_size": sum(u["size"] for u in state["units"].values()),
            "versions": len(state["versions"]),
            "versions_size": sum(v["size"] for v in state["versions"]),
            "last_run": last,
            "last_ok": last_ok["finished"] if last_ok else None,
            "recent": runs[:8],
            "pending": self.pending.get(job.id),
            "running": bool(self.run and self.run["job"] == job.id),
        }

    def statuses(self):
        return [self.status(j) for j in self.jobs()]

    def health(self, reminder_days=None):
        """For the tray: "running", "failed", "old" (no good backup for a while) or "ok"."""
        reminder_days = reminder_days or settings_mod.load()["reminder_days"]
        if self.run:
            return "running", self.run
        statuses = self.statuses()
        if not statuses:
            return "old", None      # nothing set up yet
        for s in statuses:
            if s["last_run"] and s["last_run"]["status"] == "failed":
                return "failed", s
        oldest = min(statuses, key=lambda s: s["last_ok"] or 0)
        old = not oldest["last_ok"] or time.time() - oldest["last_ok"] > reminder_days * 86400
        return ("old" if old else "ok"), oldest

    def history(self, job_id, before=None, limit=50):
        store = self.store_factory()
        try:
            return store.runs(jobs_mod.get(job_id), limit=limit, before=before)
        finally:
            store.close()

    def run_detail(self, job_id, run_id):
        """One run with its file lists. Runs from before the lists were kept get
        their report text from files.ir instead (report_text)."""
        job = jobs_mod.get(job_id)
        store = self.store_factory()
        try:
            run = store.run(job, run_id)
            state = store.load(job) if run and not run["changes"] and run["report"] else None
        finally:
            store.close()
        if state:
            try:
                dest = self.destination_factory()
                name = run["report"].rpartition("/")[2]
                entry = next(e for e in dest.entries(state["folders"][job.changes_dir]) if e["name"] == name)
                run["report_text"] = dest.download(int(entry["id"])).decode("utf8")
            except (RemoteError, KeyError, StopIteration, OSError) as e:
                run["report_text"] = f"(the report {run['report']} could not be read from files.ir: {e})"
        return run

    def preview(self, job_id):
        """Scan now and list the changes file by file (also refreshes "pending")."""
        job = jobs_mod.get(job_id)
        store = self.store_factory()
        try:
            state = store.load(job)
            sc = runner.scan(job, state)
            runner.annotate(state, sc)          # bundles from the first script: so deleted files show their bundle
            result = dict(runner.changes(state, sc), checked=time.time())
        finally:
            store.close()
        self.pending[job.id] = self._pending(sc)
        self._publish_job(job)
        return result

    # ---- actions ----

    def check(self, job_id):
        """Scan without uploading; the result lands in status()["pending"]."""
        job = jobs_mod.get(job_id)
        threading.Thread(target=self._check, args=(job,), name="check", daemon=True).start()

    def start(self, job_id):
        """Start a backup; False if one is already running."""
        job = jobs_mod.get(job_id)
        if not self._busy.acquire(blocking=False):
            return False
        self._cancel.clear()
        self.run = {"job": job.id, "name": job.name, "phase": "scanning", "started": time.time(),
                    "i": 0, "total": 0, "sent": 0, "lines": [], "result": None}
        threading.Thread(target=self._run, args=(job,), name="backup", daemon=True).start()
        return True

    def stop(self):
        self._cancel.set()

    def wait_idle(self, timeout):
        """After stop(): wait until the run has saved its state and ended."""
        if self._busy.acquire(timeout=timeout):
            self._busy.release()

    # ---- workers ----

    def _publish(self, message):
        for fn in list(self.listeners):
            try:
                fn(message)
            except Exception:
                log.exception("A listener failed")

    def _publish_job(self, job):
        self._publish({"type": "job", "job": self.status(job)})

    def _line(self, msg, **update):
        backuplog.write(msg)
        if self.run is None:
            return
        self.run.update(update)
        self.run["lines"] = (self.run["lines"] + msg.split("\n"))[-LOG_LINES:]
        self._publish({"type": "run", "run": dict(self.run), "line": msg})     # a copy: the run goes on changing

    def _pending(self, sc):
        return {"new": len(sc.new), "changed": len(sc.changed), "deleted": len(sc.gone),
                "todo": len(sc.todo), "stale": len(sc.stale), "bundles": len(sc.units),
                "files": len(sc.files), "busy": sc.busy[:5], "busy_count": len(sc.busy),
                "waiting": len(sc.waiting), "checked": time.time()}

    def _check(self, job):
        store = self.store_factory()
        try:
            state = store.load(job)
            sc = runner.scan(job, state)
            self.pending[job.id] = self._pending(sc)
        except Exception as e:
            log.exception("Checking for changes failed")
            self.pending[job.id] = {"error": str(e), "checked": time.time()}
        finally:
            store.close()
        self._publish_job(job)

    def _run(self, job):
        status, fields = "failed", {}
        store = self.store_factory()
        lock = self.lock_factory()
        locked = lock.acquire()
        try:
            if locked:
                self._publish_job(job)          # the card shows "running"
                status, fields = self._backup(job, store)
            else:
                self._line("== another backup is running (the command line?) - try again when it is done")
                status, fields = "busy", {"error": "another backup was running"}
        except Exception as e:
            log.exception("Backup failed")
            self._line(f"== error: {e}")
            fields = dict(fields, error=str(e))
        finally:
            if locked:
                lock.release()
            store.close()
            if status in ("ok", "nothing"):
                self.pending[job.id] = dict(self.pending.get(job.id) or {}, new=0, changed=0, deleted=0, todo=0,
                                            stale=0, checked=time.time())
            if status == "ok":
                self.refresh_usage()
            self.run.update(phase="done", result={"status": status, **fields})
            self._publish({"type": "run", "run": dict(self.run), "line": ""})
            self.run = None
            self._busy.release()
            self._publish_job(job)

    def _backup(self, job, store):
        """One run, recorded in the history. Returns (status, fields)."""
        state = store.load(job)
        sc = runner.scan(job, state, warn=self._line)
        if runner.annotate(state, sc):
            store.save(job, state)
        self.pending[job.id] = self._pending(sc)
        self._line(sc.summary(job), phase="uploading", total=len(sc.todo))
        fields = {"new": len(sc.new), "changed": len(sc.changed), "deleted": len(sc.gone)}
        details = runner.changes(state, sc)
        run_id = store.start_run(job)
        if not runner.needs_run(state, sc):
            if runner.remember(state, sc):
                store.save(job, state)
            self._line("== nothing changed")
            store.finish_run(run_id, "nothing", **fields)
            return "nothing", fields
        status = "failed"
        try:
            res = runner.upload(job, state, sc, self.destination_factory(), save=lambda: store.save(job, state),
                                emit=self._emit, cancel=self._cancel)
            status = "ok"
            fields.update(bundles=res["bundles"], sent=res["sent"], report=res["report"])
        except runner.Cancelled:
            status = "cancelled"
        except runner.Failed as e:
            fields["error"] = f"{len(e.keys)} bundles failed"
        except RemoteError as e:
            self._line(f"== error: {e}")
            fields["error"] = str(e)
        finally:
            store.finish_run(run_id, status, changes=details, **fields)
        return status, fields

    def _emit(self, kind, msg, **data):
        update = {}
        if kind == "bundle":
            update = {"i": data["i"], "sent": (self.run or {}).get("sent", 0) + (
                data["size"] if data["action"] != "adopted" else 0)}
        elif kind == "bundle_failed":
            update = {"i": data["i"]}
        elif kind == "done":
            update = {"phase": "finishing"}
        self._line(msg, **update)

    # ---- restore and verify ----

    def browse(self, job_id):
        """What the Restore page shows: every file of the latest backup and the old versions."""
        job = jobs_mod.get(job_id)
        store = self.store_factory()
        try:
            state = store.load(job)
            check = store.last_check(job)
        finally:
            store.close()
        return {
            "source": job.source,
            "files": [[rel, f["size"], f["mtime"] / 1e9] for rel, f in sorted(state["files"].items())],
            "versions": sorted(state["versions"], key=lambda v: (-v["created"], v["key"])),
            "remote_size": sum(u["size"] for u in state["units"].values()),
            "bundles": len(state["units"]),
            "last_check": check,
        }

    def _version(self, job, version_id):
        store = self.store_factory()
        try:
            state = store.load(job)
        finally:
            store.close()
        version = next((v for v in state["versions"] if v["id"] == version_id), None)
        if version is None:
            raise KeyError(f"no old version {version_id}")
        if version_id not in self._versions:
            self._versions[version_id] = blob.read(self.destination_factory(), version)
            while len(self._versions) > 3:
                self._versions.popitem(last=False)
        return state, version, self._versions[version_id]

    def version_files(self, job_id, version_id):
        """[[path, size, mtime]] inside an old version (downloads it)."""
        state, version, data = self._version(jobs_mod.get(job_id), version_id)
        return restore_mod.version_files(state, version, data)

    def start_restore(self, job_id, source, rels, to, overwrite=False):
        """source: "latest" or an old version's id; to: a folder ("" = the job's own folder).
        Returns None when started, else why not."""
        job = jobs_mod.get(job_id)
        return self._start_task("restore", job, self._restore, source, list(rels), to or job.source, overwrite)

    def start_verify(self, job_id, sample=None):
        """Check `sample` random bundles, or all of them (None). Returns None when started, else why not."""
        job = jobs_mod.get(job_id)
        return self._start_task("verify", job, self._verify, sample)

    def _start_task(self, kind, job, target, *args):
        if not self._busy.acquire(blocking=False):
            return "A backup, restore or check is running already."
        lock = self.lock_factory()
        if not lock.acquire():
            self._busy.release()
            return "A backup is running (the command line?) - try again when it is done."
        self._cancel.clear()
        self.task = {"kind": kind, "job": job.id, "name": job.name, "phase": "working", "started": time.time(),
                     "i": 0, "total": 0, "lines": [], "result": None}
        threading.Thread(target=self._task_main, args=(job, lock, target, args), name=kind, daemon=True).start()
        return None

    def _task_main(self, job, lock, target, args):
        try:
            result = target(job, *args)
        except (ValueError, KeyError) as e:     # a request that can't be done - no traceback needed
            self._task_line(f"== error: {e}")
            result = {"status": "failed", "error": str(e)}
        except Exception as e:
            log.exception("%s failed", self.task["kind"])
            self._task_line(f"== error: {e}")
            result = {"status": "failed", "error": str(e)}
        finally:
            lock.release()
        self.task.update(phase="done", result=result)
        self._publish({"type": "task", "task": dict(self.task), "line": ""})
        self.task = None
        self._busy.release()
        self._publish_job(job)

    def _task_line(self, msg, **update):
        backuplog.write(msg)
        self.task.update(update)
        self.task["lines"] = (self.task["lines"] + msg.split("\n"))[-LOG_LINES:]
        self._publish({"type": "task", "task": dict(self.task), "line": msg})

    def _task_emit(self, kind, msg, **data):
        self._task_line(msg, **({"i": self.task["i"] + 1} if kind == "bundle" else {}))

    def _restore(self, job, source, rels, to, overwrite):
        if not os.path.isabs(to):
            raise ValueError(f"not a full folder path: {to}")
        if source == "latest":
            store = self.store_factory()
            try:
                state = store.load(job)
            finally:
                store.close()
            unknown = [r for r in rels if r not in state["files"]]
            if unknown:
                raise ValueError(f"not in the backup: {unknown[0]}")
            by_unit = restore_mod.plan(state, rels)
            self._task_line(f"== restore {len(rels)} files from the latest backup ({len(by_unit)} bundles) into {to}",
                            total=len(by_unit))
            res = restore_mod.restore(job, state, self.destination_factory(), rels, to, overwrite=overwrite,
                                      emit=self._task_emit)
        else:
            self._task_line(f"== restore {len(rels)} files from an old version into {to}", total=1)
            state, version, data = self._version(job, int(source))
            known = {f[0] for f in restore_mod.version_files(state, version, data)}
            unknown = [r for r in rels if r not in known]
            if unknown:
                raise ValueError(f"not in that version: {unknown[0]}")
            res = restore_mod.restore_version(state, version, data, rels, to, overwrite=overwrite,
                                              emit=self._task_emit)
            self._task_line(f"[1/1] {version['stamp']}/{version['key']}", i=1)
        self._task_line(f"== done: {res['written']} files written"
                        + (f", {len(res['skipped'])} already there (skipped)" if res["skipped"] else "")
                        + (f", {len(res['bad'])} FAILED THE CHECK" if res["bad"] else ""))
        return {"status": "failed" if res["bad"] else "ok", "written": res["written"], "to": to,
                "skipped": res["skipped"][:200], "skipped_count": len(res["skipped"]), "bad": res["bad"][:200]}

    def _verify(self, job, sample):
        store = self.store_factory()
        try:
            state = store.load(job)
            keys = sorted(state["units"])
            if sample:
                keys = sorted(random.sample(keys, min(sample, len(keys))))
            size = sum(state["units"][k]["size"] for k in keys)
            self._task_line(f"== checking {len(keys)} of {len(state['units'])} bundles ({size / 1048576:.1f} MB)",
                            total=len(keys))
            res = verify(state, self.destination_factory(), keys, emit=self._task_emit, cancel=self._cancel)
            stopped = self._cancel.is_set()
            if not stopped:
                store.add_check(job, sample is None, res["bundles"], res["files"], res["problems"])
        finally:
            store.close()
        for bundle, rel, what in res["problems"][:50]:
            self._task_line(f"   PROBLEM {bundle} {rel}: {what}")
        self._task_line("== stopped" if stopped else
                        f"== checked {res['files']} files in {res['bundles']} bundles: "
                        + (f"{len(res['problems'])} PROBLEMS" if res["problems"] else "all good"))
        return {"status": "cancelled" if stopped else "failed" if res["problems"] else "ok",
                "bundles": res["bundles"], "files": res["files"], "problems": res["problems"][:200]}

    # ---- settings ----

    def _has_backup(self, job):
        store = self.store_factory()
        try:
            state = store.load(job)
        finally:
            store.close()
        return bool(state["root_id"] or state["files"])

    def settings_view(self):
        data = settings_mod.load()
        return {
            "app": {"reminder_days": data["reminder_days"], "start_with_windows": autostart.enabled()},
            "jobs": [dict(j.to_dict(), locked=self._has_backup(j)) for j in jobs_mod.JOBS],
            "key": "stored" if keystore.read() is not None else None,
            "new_job": settings_mod.NEW_JOB_SKIPS,
            "common_skips": settings_mod.COMMON_SKIPS,
        }

    def _job_from(self, d, check_taken=True):
        """A Job from the Settings page's form, checked. Raises ValueError with what is wrong."""
        def text(key, most=200):
            v = d.get(key)
            if not isinstance(v, str) or not v.strip() or len(v) > most:
                raise ValueError(f"{key.replace('_', ' ')}: missing or too long")
            return v.strip()

        def strings(key):
            v = d.get(key) or []
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError(f"{key}: a list of names")
            return tuple(x.strip().replace("\\", "/").strip("/") if key == "skip_paths" else x.strip()
                         for x in v if x.strip())

        def number(key, low, high, scale=1):
            v = d.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not low <= v <= high:
                raise ValueError(f"{key.replace('_', ' ')}: between {low} and {high}")
            return int(v * scale)

        source = os.path.normpath(text("source", 260))
        if not os.path.isabs(source) or not os.path.isdir(source):
            raise ValueError(f"no such folder: {source}")
        remote_root = text("remote_root", 100)
        if any(c in remote_root for c in '/\\:*?"<>|'):
            raise ValueError('the folder on files.ir: a plain name, without / \\ : * ? " < > |')
        if check_taken:
            for other in jobs_mod.JOBS:
                if other.id != d.get("id") and other.remote_root.lower() == remote_root.lower():
                    raise ValueError(f"the folder on files.ir is used by \"{other.name}\" already")
        return jobs_mod.Job(
            id=d.get("id") or "new", name=text("name", 60), source=source, remote_root=remote_root,
            skip_dir_names=strings("skip_dir_names"), skip_paths=strings("skip_paths"),
            skip_files=strings("skip_files"),
            bundle_limit=number("bundle_mb", 1, 45, 1 << 20), big_file=number("big_file_mb", 1, 45, 1 << 20),
            keep_versions=number("keep_versions", 1, 100), keep_days=number("keep_days", 0, 3650))

    def measure(self, form):
        """What a job's rules (as on the form) would back up - for the live numbers on the Settings page."""
        job = self._job_from(form, check_taken=False)
        m = measure(job)
        sizes = m.pop("sizes")
        m["bundles"] = len(plan_units(job, {r: (s, 0) for r, s in sizes.items()}))
        return m

    def save_job(self, form):
        """Add (no id) or change a job. Returns the saved job as a dict."""
        if self.run or self.task:
            raise ValueError("wait until the backup / restore / check has finished")
        job = self._job_from(form)
        data = settings_mod.load()
        if not form.get("id"):
            job = jobs_mod.Job(**{**job.__dict__, "id": jobs_mod.new_id(job.name, {j["id"] for j in data["jobs"]})})
            data["jobs"].append(job.to_dict())
        else:
            i = next((i for i, j in enumerate(data["jobs"]) if j["id"] == job.id), None)
            if i is None:
                raise ValueError("that job is gone")
            old = jobs_mod.Job.from_dict(data["jobs"][i])
            if self._has_backup(old) and (os.path.normcase(old.source) != os.path.normcase(job.source)
                                          or old.remote_root != job.remote_root):
                raise ValueError("this job has backups already - its folder and its folder on files.ir stay as they are")
            data["jobs"][i] = job.to_dict()
        settings_mod.save(data)
        jobs_mod.reload()
        self.pending.pop(job.id, None)
        return job.to_dict()

    def remove_job(self, job_id):
        """Forget a job (its backup on files.ir stays untouched)."""
        if self.run or self.task:
            raise ValueError("wait until the backup / restore / check has finished")
        data = settings_mod.load()
        data["jobs"] = [j for j in data["jobs"] if j["id"] != job_id]
        settings_mod.save(data)
        jobs_mod.reload()

    def save_app(self, changes):
        data = settings_mod.load()
        if "reminder_days" in changes:
            v = changes["reminder_days"]
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 365:
                raise ValueError("reminder: between 1 and 365 days")
            data["reminder_days"] = v
        if "limits_mode" in changes:
            if changes["limits_mode"] not in ("auto", "custom"):
                raise ValueError("limits: automatic or set by hand")
            data["limits_mode"] = changes["limits_mode"]
        if "custom_limits" in changes:
            c = changes["custom_limits"] if isinstance(changes["custom_limits"], dict) else {}

            def number(key, low, high):
                v = c.get(key)
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not low <= v <= high:
                    raise ValueError(f"{key.replace('_', ' ')}: between {low:,} and {high:,}")
                return v
            data["custom_limits"] = {"name": "Set by hand", "space": int(number("space_gb", 1, 1_000_000) * GB),
                                     "files": int(number("files", 10, 100_000_000)),
                                     "file": int(number("file_mb", 1, 1_000_000) * MB)}
        if "start_with_windows" in changes:
            autostart.set_enabled(bool(changes["start_with_windows"]))
            data["start_with_windows"] = bool(changes["start_with_windows"])
        settings_mod.save(data)
        if "limits_mode" in changes or "custom_limits" in changes:
            jobs_mod.reload()           # the part size comes from the limits
            self.refresh_usage()

    def set_key(self, key):
        """Check a new files.ir key with files.ir, then keep it in Credential Manager."""
        key = (key or "").strip()
        if len(key) < 10 or len(key) > 500 or any(c.isspace() for c in key):
            raise ValueError("that does not look like a files.ir key")
        try:
            self.key_check(key)
        except RemoteError as e:
            raise ValueError(f"files.ir did not accept this key: {e}")
        keystore.write(key)

    def test_key(self):
        try:
            self.key_check(load_key())
            return None
        except RemoteError as e:
            return str(e)

    def reminder(self):
        """For the tray, about once an hour: [(job name, days since its last good backup, changed files)]
        of the jobs whose last good backup is older than the reminder and that have changes waiting."""
        days = settings_mod.load()["reminder_days"]
        due = []
        for job in jobs_mod.JOBS:
            s = self.status(job)
            age = (time.time() - s["last_ok"]) / 86400 if s["last_ok"] else None
            if age is not None and age < days:
                continue
            store = self.store_factory()
            try:
                sc = runner.scan(job, store.load(job))
            finally:
                store.close()
            n = len(sc.new) + len(sc.changed) + len(sc.gone)
            if n:
                due.append((job.name, age, n))
        return due

    def save_fold(self, job_id, folded):
        """Which dashboard cards are folded (the window's own storage changes with the app's port)."""
        data = settings_mod.load()
        data.setdefault("folded", {})[job_id] = folded
        settings_mod.save(data)

    # ---- files.ir usage ----

    def _file_count(self, job, store):
        """Files this job keeps on the destination (folders don't count)."""
        state = store.load(job)
        if not state["root_id"]:
            return 0

        def count(record):
            return -(-record["size"] // job.part_size) if record.get("parts") else 1

        return (sum(count(u) for u in state["units"].values()) + sum(count(v) for v in state["versions"])
                + bool(state["index_id"]) + bool(state["manifest_id"])
                + min(store.report_count(job), job.keep_reports))

    def detect_limits(self, dest):
        """Ask files.ir for the account's plan; keep it in settings.json (so the command line and an
        offline start know it too). Returns an error message or None."""
        try:
            found = dest.plan()
        except RemoteError as e:
            return str(e)
        if not found:
            return None
        data = settings_mod.load()
        old = data.get("detected_limits") or {}
        data["detected_limits"] = dict(found, checked=time.time())
        settings_mod.save(data)
        if {k: old.get(k) for k in found} != found:
            log.info("files.ir plan: %s", found)
            jobs_mod.reload()           # the part size follows the plan
        return None

    def usage(self):
        """Space (from files.ir, whole account) and files (Pastoo's own, counted here)
        against the account's limits - read from files.ir, or set by hand."""
        dest = self.destination_factory()
        data = settings_mod.load()
        plan_error = self.detect_limits(dest) if data["limits_mode"] == "auto" else None
        data = settings_mod.load()
        limits = settings_mod.limits(data)
        result = {"mode": data["limits_mode"], "limits": limits, "detected": data["detected_limits"],
                  "custom": data["custom_limits"], "plan_error": plan_error,
                  "files_total": limits["files"], "space_total": limits["space"], "space_used": None,
                  "part_size": settings_mod.part_size(data), "checked": time.time(), "error": None}
        store = self.store_factory()
        try:
            result["files"] = sum(self._file_count(job, store) for job in jobs_mod.JOBS)
        finally:
            store.close()
        try:
            space = dest.usage()
            if space:
                result["space_used"] = space["used"]
                if data["limits_mode"] == "auto":
                    result["space_total"] = space["total"]
        except RemoteError as e:
            result["error"] = str(e)
        return result

    def refresh_usage(self):
        """usage(), kept in last_usage and sent to the windows; never raises."""
        try:
            self.last_usage = self.usage()
            self._publish({"type": "usage", "usage": self.last_usage})
        except Exception:
            log.exception("Reading the files.ir usage failed")
