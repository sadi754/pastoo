"""Pastoo: the app (Pastoo.exe, run.bat) or the command line
(pastoo-cli.exe, backup.bat, python -m pastoo).

    Pastoo.exe [--minimized] [--debug]      the app: tray icon + window
    pastoo-cli run [--dry-run] [--jobs N] [--rescan]
    pastoo-cli restore PATH... --to FOLDER [--overwrite] [--dry-run]
    pastoo-cli history
    pastoo-cli jobs

run        upload the bundles whose files changed
  --dry-run  only show the bundles and what changed
  --jobs N   uploads at the same time (default 4)
  --rescan   forget what this PC remembers and read it back from _backup.json
restore    get files or folders (relative to the job's folder, "." = all)
           back from the latest backup into FOLDER; existing files are
           skipped unless --overwrite; --dry-run only lists them
Every command takes --job ID (default: the first job).
"""
import sys
import time

from . import backuplog, jobs as jobs_mod
from .engine import manifest, restore as restore_mod, runner
from .remote.base import RemoteError
from .remote.filesir import FilesIr, load_key
from .runlock import RunLock
from .store import Store, empty
from .util import human


def log(msg):
    backuplog.write(msg, echo=True)


def opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def positional(args, with_value=("--job", "--jobs", "--to")):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in with_value:
            skip = True
        elif not a.startswith("--"):
            out.append(a)
    return out


def destination():
    return FilesIr(load_key(), on_retry=log)


def cmd_run(job, store, args):
    state = store.load(job)
    if "--rescan" in args:
        fetched = manifest.fetch(job, destination())
        state = fetched or dict(empty(), files=state["files"])
        log(f"== read back from {job.manifest_name}" if fetched else
            f"== no {job.manifest_name} yet - bundles already there are found by name and size")
        store.save(job, state)
    sc = runner.scan(job, state, warn=log)
    if runner.annotate(state, sc):
        store.save(job, state)
    log(sc.summary(job))

    if "--dry-run" in args:
        for k in sorted(sc.units):
            u = sc.units[k]
            mark = "upload" if k in sc.todo else "  same"
            print(f"  {mark}  {human(sum(sc.files[r][0] for r in u['files'])):>9}  {len(u['files']):>4} files  {k}")
        for k in sc.stale:
            print(f"  retire  {k}")
        if not sc.first:
            for r in sc.new:
                print(f"  + {r}")
            for r in sc.changed:
                print(f"  * {r}")
            for r in sc.gone:
                print(f"  - {r}")
        return 0

    run_id = store.start_run(job)
    counts = {"new": len(sc.new), "changed": len(sc.changed), "deleted": len(sc.gone),
              "changes": runner.changes(state, sc)}
    if not runner.needs_run(state, sc):
        if runner.remember(state, sc):
            store.save(job, state)
        log("== nothing changed")
        store.finish_run(run_id, "nothing", **counts)
        return 0
    try:
        res = runner.upload(job, state, sc, destination(), save=lambda: store.save(job, state),
                            emit=lambda kind, msg, **data: log(msg), jobs=int(opt(args, "--jobs", runner.JOBS)))
    except runner.Cancelled:
        store.finish_run(run_id, "cancelled", **counts)
        return 1
    except runner.Failed as e:
        store.finish_run(run_id, "failed", error=f"{len(e.keys)} bundles failed", **counts)
        return 1
    except RemoteError as e:
        log(f"== error: {e}")
        store.finish_run(run_id, "failed", error=str(e), **counts)
        return 1
    store.finish_run(run_id, "ok", bundles=res["bundles"], sent=res["sent"], report=res["report"], **counts)
    return 0


def cmd_restore(job, store, args):
    to = opt(args, "--to")
    wanted = ["" if p == "." else p for p in positional(args)]
    if not to or not wanted:
        print(__doc__)
        return 2
    state = store.load(job)
    dest = destination()
    if not state["files"]:
        log(f"== nothing known on this PC - reading {job.manifest_name} from {dest.label}")
        state = manifest.fetch(job, dest)
        if not state:
            log(f"== no {job.manifest_name} on {dest.label} for {job.remote_root}")
            return 1
    try:
        rels = restore_mod.select(state, wanted)
        by_unit = restore_mod.plan(state, rels)
    except restore_mod.RestoreError as e:
        log(f"== {e}")
        return 1
    size = sum(state["files"][r]["size"] for r in rels)
    log(f"== restore {len(rels)} files ({human(size)}) from {len(by_unit)} bundles into {to}")
    if "--dry-run" in args:
        for key, members in sorted(by_unit.items()):
            print(f"  {key}")
            for rel in members:
                print(f"     {rel}")
        return 0
    try:
        res = restore_mod.restore(job, state, dest, rels, to, overwrite="--overwrite" in args,
                                  emit=lambda kind, msg, **d: log(msg))
    except RemoteError as e:
        log(f"== error: {e}")
        return 1
    log(f"== done: {res['written']} files written"
        + (f", {len(res['skipped'])} already there (skipped; --overwrite to replace)" if res["skipped"] else "")
        + (f", {len(res['bad'])} FAILED THE CHECK" if res["bad"] else ""))
    return 1 if res["bad"] else 0


def cmd_history(job, store):
    for r in store.runs(job):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started"]))
        print(f"{when}  {r['status']:9}  new {r['new'] or 0:>4}  changed {r['changed'] or 0:>4}  "
              f"deleted {r['deleted'] or 0:>4}  {r['bundles'] or 0:>3} bundles {human(r['sent'] or 0):>9}"
              f"  {r['report'] or r['error'] or ''}")
    return 0


def main(args):
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):     # None under pythonw.exe
        sys.stdout.reconfigure(encoding="utf8", errors="replace")
    cmd = args[0] if args else None
    if cmd == "--window":                   # internal: the window process
        from . import logs, window
        logs.setup("window.log")
        window.run(args[1])
        return 0
    if cmd is None or cmd in ("--minimized", "--debug"):
        from . import app
        app.run(minimized="--minimized" in args, debug="--debug" in args)
        return 0
    if cmd == "jobs":
        for j in jobs_mod.JOBS:
            print(f"{j.id:10} {j.source}  ->  {j.remote_root}")
        return 0
    if cmd not in ("run", "restore", "history"):
        print(__doc__)
        return 2
    if not jobs_mod.JOBS:
        print("No backup jobs yet - add a folder in the app (Settings -> Backup jobs).")
        return 1
    job = jobs_mod.get(opt(args, "--job", jobs_mod.JOBS[0].id))
    lock = RunLock()
    if cmd == "run" and "--dry-run" not in args and not lock.acquire():
        log("== another backup is running (the app?) - try again when it is done")
        return 1
    store = Store()
    try:
        if cmd == "run":
            return cmd_run(job, store, args[1:])
        if cmd == "restore":
            return cmd_restore(job, store, args[1:])
        return cmd_history(job, store)
    except (RemoteError, runner.SourceMissing) as e:        # e.g. no key, the drive not plugged in
        log(f"== error: {e}")
        return 1
    finally:
        store.close()
        lock.release()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
