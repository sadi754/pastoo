"""The backup engine against the in-memory destination.

    python -m unittest discover -s tests
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pastoo.engine import manifest, restore, runner  # noqa: E402
from pastoo.jobs import Job  # noqa: E402
from pastoo.remote.fake import FakeDestination  # noqa: E402
from pastoo.store import Store  # noqa: E402

DAY = 86400
T0 = time.mktime((2026, 10, 17, 12, 0, 0, 0, 0, -1))


def stamp(minute=0, days=0):
    return time.strftime("%Y-%m-%d_%H%M", time.localtime(T0 + days * DAY + minute * 60))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.job = Job(id="t", name="t", source=self.src, remote_root="T backup",
                       skip_dir_names=frozenset({".pio"}), skip_paths=frozenset({"skip/me.txt"}),
                       skip_files=("*.mkv",), bundle_limit=100, big_file=50)
        self.store = self.new_store()
        self.dest = FakeDestination()
        self.events = []
        self.ticks = 0
        self.write("a/one.txt", "1" * 30)
        self.write("a/two.txt", "2" * 30)
        self.write("b/c/three.txt", "3" * 20)
        self.write("b/big.bin", "B" * 90)           # >= big_file: goes up on its own; b/ = 111 > limit
        self.write("b/small.txt", "s")
        self.write("top.txt", "t")
        self.write("a/.pio/build.o", "x")           # skipped folder
        self.write("skip/me.txt", "x")              # skipped path
        self.write("a/film.mkv", "x")               # skipped pattern

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new_store(self, name="state.db"):
        return Store(os.path.join(self.tmp, name))

    def write(self, rel, text):
        path = os.path.join(self.src, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        self.ticks += 1         # make every write look like a change, even within the same clock tick
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000 * self.ticks))

    def run_backup(self, minute=0, days=0, **kw):
        state = self.store.load(self.job)
        sc = runner.scan(self.job, state)
        runner.annotate(state, sc)
        if not runner.needs_run(state, sc):
            return sc, None
        res = runner.upload(self.job, state, sc, self.dest, save=lambda: self.store.save(self.job, state),
                            emit=lambda kind, msg, **d: self.events.append((kind, d)),
                            clock=lambda: T0 + days * DAY + minute * 60, **kw)
        return sc, res

    def live(self):
        return self.dest.live_files()

    def zip_names(self, path):
        return sorted(zipfile.ZipFile(io.BytesIO(self.live()[path])).namelist())


class FirstRun(Base):
    def test_bundles_and_reports(self):
        sc, res = self.run_backup()
        self.assertTrue(sc.first)
        self.assertEqual(sorted(self.live()), [
            "T backup/_backup.json",
            f"T backup/_changes/{stamp()}.txt",
            "T backup/_files.zip",
            "T backup/_index.txt",
            "T backup/a.zip",
            "T backup/b/_files.zip",
            "T backup/b/big.bin",
            "T backup/b/c.zip",
        ])
        self.assertEqual(self.zip_names("T backup/a.zip"), ["a/one.txt", "a/two.txt"])
        self.assertEqual(self.zip_names("T backup/b/c.zip"), ["c/three.txt"])
        self.assertEqual(self.zip_names("T backup/b/_files.zip"), ["small.txt"])
        self.assertEqual(self.zip_names("T backup/_files.zip"), ["top.txt"])
        self.assertEqual(self.live()["T backup/b/big.bin"], b"B" * 90)
        self.assertIn("first full backup: 6 files in 5 bundles",
                      self.live()[f"T backup/_changes/{stamp()}.txt"].decode())

    def test_manifest_holds_everything(self):
        self.run_backup()
        m = json.loads(self.live()["T backup/_backup.json"])
        self.assertEqual(m["format"], 1)
        self.assertEqual(sorted(m["files"]), ["a/one.txt", "a/two.txt", "b/big.bin", "b/c/three.txt",
                                              "b/small.txt", "top.txt"])
        self.assertEqual(m["units"]["b/c.zip"]["members"], ["b/c/three.txt"])
        self.assertEqual(m["files"]["top.txt"]["sha1"], hashlib.sha1(b"t").hexdigest())

    def test_second_run_does_nothing(self):
        self.run_backup()
        calls = len(self.dest.calls)
        sc, res = self.run_backup()
        self.assertIsNone(res)
        self.assertEqual(len(self.dest.calls), calls)

    def test_touch_without_change_is_not_a_change(self):
        self.run_backup()
        path = os.path.join(self.src, "a", "one.txt")
        os.utime(path, ns=(0, os.stat(path).st_mtime_ns + 5_000_000_000))
        sc, res = self.run_backup()
        self.assertIsNone(res)


class Changes(Base):
    def setUp(self):
        super().setUp()
        self.run_backup()
        self.dest.calls.clear()

    def test_changed_file_uploads_only_its_bundle_and_keeps_the_old_one(self):
        old_id = self.store.load(self.job)["units"]["a.zip"]["id"]
        old_zip = self.dest.items[old_id]["data"]
        self.write("a/one.txt", "changed")
        sc, res = self.run_backup(minute=1)
        self.assertEqual(sc.changed, ["a/one.txt"])
        self.assertEqual(self.dest.uploads(), ["a.zip", f"{stamp(1)}.txt", "_index.txt", "_backup.json"])
        self.assertEqual(self.live()[f"T backup/_versions/{stamp(1)}/a.zip"], old_zip)
        self.assertEqual(self.dest.items[old_id]["parent_id"],
                         self.store.load(self.job)["folders"][f"_versions/{stamp(1)}"])
        self.assertIn("* a/one.txt", self.live()[f"T backup/_changes/{stamp(1)}.txt"].decode())
        self.assertEqual(len([p for p in self.live() if p.endswith("_index.txt")]), 1)
        self.assertEqual(len([p for p in self.live() if p.endswith("_backup.json")]), 1)
        self.assertEqual([v["key"] for v in self.store.load(self.job)["versions"]], ["a.zip"])

    def test_old_version_in_a_subfolder(self):
        self.write("b/c/three.txt", "x" * 20)
        self.run_backup(minute=1)
        self.assertIn(f"T backup/_versions/{stamp(1)}/b/c.zip", self.live())

    def test_new_and_deleted_files(self):
        self.write("b/c/four.txt", "4")
        os.remove(os.path.join(self.src, "a", "two.txt"))
        sc, _ = self.run_backup(minute=2)
        self.assertEqual(sorted(self.dest.uploads()[:2]), ["a.zip", "c.zip"])
        self.assertEqual(self.zip_names("T backup/a.zip"), ["a/one.txt"])
        self.assertEqual(self.zip_names(f"T backup/_versions/{stamp(2)}/a.zip"), ["a/one.txt", "a/two.txt"])
        self.assertEqual(self.zip_names("T backup/b/c.zip"), ["c/four.txt", "c/three.txt"])
        report = self.live()[f"T backup/_changes/{stamp(2)}.txt"].decode()
        self.assertIn("+ b/c/four.txt", report)
        self.assertIn("- a/two.txt", report)

    def test_folder_growing_past_the_limit_is_split(self):
        self.write("a/sub/three.txt", "3" * 50)      # a/ is now 110 bytes > 100
        sc, _ = self.run_backup(minute=3)
        self.assertEqual(sc.stale, ["a.zip"])
        live = self.live()
        self.assertNotIn("T backup/a.zip", live)
        self.assertIn(f"T backup/_versions/{stamp(3)}/a.zip", live)
        self.assertIn("T backup/a/_files.zip", live)
        self.assertIn("T backup/a/sub.zip", live)
        self.assertIn("bundles replaced by smaller ones", live[f"T backup/_changes/{stamp(3)}.txt"].decode())


class ChangeList(Base):
    def test_changes_name_the_bundles(self):
        self.run_backup()
        self.write("a/one.txt", "x" * 30)
        self.write("b/c/four.txt", "4")
        os.remove(os.path.join(self.src, "b", "small.txt"))
        state = self.store.load(self.job)
        ch = runner.changes(state, runner.scan(self.job, state))
        self.assertFalse(ch["first"])
        self.assertEqual(ch["new"], [["b/c/four.txt", 1, "b/c.zip"]])
        self.assertEqual(ch["changed"], [["a/one.txt", 30, "a.zip"]])
        self.assertEqual(ch["deleted"], [["b/small.txt", 1, "b/_files.zip"]])
        self.assertEqual([b[0] for b in ch["bundles"]], ["a.zip", "b/c.zip"])    # b/_files.zip is gone: stale
        self.assertEqual(ch["stale"], ["b/_files.zip"])

    def test_runs_keep_their_changes(self):
        run_id = self.store.start_run(self.job)
        self.store.finish_run(run_id, "ok", changes={"new": [["x", 1, "y.zip"]]}, new=1)
        self.assertEqual(self.store.run(self.job, run_id)["changes"], {"new": [["x", 1, "y.zip"]]})
        self.assertNotIn("changes", self.store.runs(self.job)[0])

    def test_old_database_gets_the_changes_column(self):
        import sqlite3
        path = os.path.join(self.tmp, "v1.db")
        db = sqlite3.connect(path)
        db.executescript("""CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, started REAL,
            finished REAL, status TEXT, new INTEGER, changed INTEGER, deleted INTEGER, bundles INTEGER,
            sent INTEGER, report TEXT, error TEXT); INSERT INTO runs (job_id, started, status) VALUES ('t', 1, 'ok');
            PRAGMA user_version = 1;""")
        db.close()
        store = Store(path)
        self.assertIsNone(store.run(self.job, 1)["changes"])
        store.close()


class Retention(Base):
    def change_a(self, n, days):
        self.write("a/one.txt", chr(64 + n) * 30)    # A..H - never the original "1" * 30
        self.run_backup(days=days)

    def versions_of_a(self):
        return sorted(p.split("/")[2] for p in self.live() if p.startswith("T backup/_versions/"))

    def test_keeps_5_newest_or_30_days(self):
        self.run_backup()
        for n in range(1, 8):                   # 7 changes, one every 10 days -> 7 old versions of a.zip
            self.change_a(n, days=10 * n)
        # now = day 70; versions from days 0..60; beyond the 5 newest: day 0 and day 10 - both > 30 days
        self.assertEqual(self.versions_of_a(), [stamp(days=d) for d in (30, 40, 50, 60, 70)])
        self.assertEqual(len(self.store.load(self.job)["versions"]), 5)
        self.assertNotIn(f"_versions/{stamp(days=10)}", self.store.load(self.job)["folders"])

    def test_young_versions_stay_even_beyond_5(self):
        self.run_backup()
        for n in range(1, 9):                   # 8 changes within a day
            self.change_a(n, days=0.1 * n)
        self.assertEqual(len(self.versions_of_a()), 8)


class Restore(Base):
    def setUp(self):
        super().setUp()
        self.run_backup()
        self.out = os.path.join(self.tmp, "out")

    def restore(self, *wanted, state=None, **kw):
        state = state or self.store.load(self.job)
        return restore.restore(self.job, state, self.dest, restore.select(state, list(wanted)), self.out, **kw)

    def read(self, rel):
        with open(os.path.join(self.out, *rel.split("/"))) as f:
            return f.read()

    def test_folder(self):
        res = self.restore("b")
        self.assertEqual(res["written"], 3)
        self.assertEqual(self.read("b/c/three.txt"), "3" * 20)
        self.assertEqual(self.read("b/big.bin"), "B" * 90)
        self.assertEqual(os.stat(os.path.join(self.out, "b", "small.txt")).st_mtime_ns,
                         os.stat(os.path.join(self.src, "b", "small.txt")).st_mtime_ns)
        self.assertFalse(os.path.exists(os.path.join(self.out, "a")))

    def test_only_needed_bundles_are_downloaded(self):
        downloads = []
        real = self.dest.download
        self.dest.download = lambda eid: downloads.append(eid) or real(eid)
        self.restore("a/two.txt")
        self.assertEqual(downloads, [self.store.load(self.job)["units"]["a.zip"]["id"]])
        self.assertEqual(os.listdir(os.path.join(self.out, "a")), ["two.txt"])

    def test_everything_and_existing_files_are_skipped(self):
        os.makedirs(os.path.join(self.out, "a"))
        with open(os.path.join(self.out, "a", "one.txt"), "w") as f:
            f.write("mine")
        res = self.restore("")
        self.assertEqual((res["written"], res["skipped"]), (5, ["a/one.txt"]))
        self.assertEqual(self.read("a/one.txt"), "mine")
        self.restore("a/one.txt", overwrite=True)
        self.assertEqual(self.read("a/one.txt"), "1" * 30)

    def test_damaged_bundle_is_not_written(self):
        uid = self.store.load(self.job)["units"]["b/big.bin"]["id"]
        self.dest.items[uid]["data"] = b"X" * 90
        res = self.restore("b/big.bin")
        self.assertEqual(res["bad"], ["b/big.bin"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "b", "big.bin")))

    def test_unknown_path(self):
        with self.assertRaises(restore.RestoreError):
            self.restore("nope")

    def test_from_another_pc(self):
        state = manifest.fetch(self.job, self.dest)    # nothing local: only the destination
        here = {r: {k: f[k] for k in ("size", "mtime", "sha1")} for r, f in self.store.load(self.job)["files"].items()}
        self.assertEqual(state["files"], here)          # (the journal numbers stay on this PC)
        res = self.restore("", state=state)
        self.assertEqual(res["written"], 6)


class Recovery(Base):
    def test_lost_database_reads_back_from_manifest(self):
        self.write("a/one.txt", "v2" * 15)
        self.run_backup()
        self.write("a/one.txt", "v3" * 15)
        self.run_backup(minute=1)
        before = self.store.load(self.job)
        self.store.close()
        self.store = self.new_store("other.db")         # a fresh PC
        self.store.save(self.job, manifest.fetch(self.job, self.dest))
        self.dest.calls.clear()
        sc, res = self.run_backup(minute=2)
        self.assertIsNone(res)                            # nothing to upload
        self.assertEqual(self.store.load(self.job)["versions"], before["versions"])

    def test_failed_bundle_is_retried_and_reported_next_time(self):
        self.run_backup()
        self.write("a/one.txt", "x")
        self.write("b/c/three.txt", "y" * 20)   # same size, so b/ stays split
        self.dest.fail_names = {"c.zip"}
        with self.assertRaises(runner.Failed) as cm:
            self.run_backup(minute=1)
        self.assertEqual(cm.exception.keys, ["b/c.zip"])
        self.assertNotIn(f"{stamp(1)}.txt", self.dest.uploads())   # no report for a failed run
        self.dest.fail_names = set()
        self.dest.calls.clear()
        self.run_backup(minute=2)
        self.assertEqual(self.dest.uploads(), ["c.zip", f"{stamp(2)}.txt", "_index.txt", "_backup.json"])
        report = self.live()[f"T backup/_changes/{stamp(2)}.txt"].decode()
        self.assertIn("* a/one.txt", report)          # still reported though a.zip went up last time
        self.assertIn("* b/c/three.txt", report)

    def test_no_state_and_no_manifest_takes_over_by_name_and_size(self):
        self.run_backup()
        self.dest.trash(self.store.load(self.job)["manifest_id"])
        self.store.close()
        self.store = self.new_store("other.db")
        self.dest.calls.clear()
        self.run_backup(minute=1)
        self.assertEqual([n for n in self.dest.uploads() if not n.startswith("_") and not n.endswith(".txt")], [])

    def test_stopped_run_continues_without_duplicates(self):
        self.dest.fail_after = 2                      # the "network" dies after 2 uploads
        with self.assertRaises(runner.Failed):
            self.run_backup(jobs=1)
        self.dest.fail_after = None
        self.run_backup(minute=1, jobs=1)
        names = sorted(p for p in self.live() if not p.endswith(".txt") and not p.endswith(".json"))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 5)

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(runner.Cancelled):
            self.run_backup(cancel=cancel)
        self.assertIn("cancelled", [k for k, _ in self.events])


class HiddenChanges(Base):
    """Programs that put a file's date back after writing it (VeraCrypt does with its containers)."""

    def write_keeping_the_date(self, rel, text):
        path = os.path.join(self.src, *rel.split("/"))
        st = os.stat(path)
        with open(path, "w") as f:
            f.write(text)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))

    def test_the_change_journal_sees_it(self):
        self.run_backup()
        self.write_keeping_the_date("a/one.txt", "9" * 30)            # same size, same date
        self.dest.calls.clear()
        sc, _ = self.run_backup(minute=1)
        self.assertEqual(sc.changed, ["a/one.txt"])
        self.assertIn("a.zip", self.dest.uploads())

    def test_reading_leaves_the_journal_alone(self):
        self.run_backup()
        sc, res = self.run_backup(minute=1)
        self.assertIsNone(res)                                          # nothing to do
        state = self.store.load(self.job)
        self.assertFalse(runner.remember(state, runner.scan(self.job, state)))     # and nothing read again

    def test_without_a_journal_files_are_read_again_now_and_then(self):
        from pastoo.engine import scan
        saved = scan.winfile.usn, scan.REREAD_DAYS
        scan.winfile.usn = lambda path: None                          # FAT / exFAT / network drive
        try:
            self.run_backup()
            self.write_keeping_the_date("a/one.txt", "9" * 30)
            sc, _ = self.run_backup(minute=1)
            self.assertEqual(sc.changed, [])                           # read less than REREAD_DAYS ago
            scan.REREAD_DAYS = 0
            sc, _ = self.run_backup(minute=2)
            self.assertEqual(sc.changed, ["a/one.txt"])
        finally:
            scan.winfile.usn, scan.REREAD_DAYS = saved


class InUse(Base):
    """A file another program is writing to (a mounted VeraCrypt container, an open .pst)."""

    def hold(self, rel):
        f = open(os.path.join(self.src, *rel.split("/")), "r+b")      # open for writing, like that program
        self.addCleanup(f.close)
        return f

    def test_its_last_copy_stays_and_its_bundle_waits(self):
        self.run_backup()
        before = self.zip_names("T backup/a.zip")
        self.write("a/two.txt", "x" * 30)                             # a change in the same bundle
        held = self.hold("a/one.txt")
        self.dest.calls.clear()
        sc, _ = self.run_backup(minute=1)
        self.assertEqual((sc.busy, sc.waiting), (["a/one.txt"], ["a.zip"]))
        self.assertEqual((sc.gone, sc.changed), ([], []))              # not deleted; nothing went up
        self.assertNotIn("a.zip", self.dest.uploads())
        self.assertEqual(self.zip_names("T backup/a.zip"), before)
        held.close()
        sc, _ = self.run_backup(minute=2)                              # closed: the waiting change goes up
        self.assertEqual((sc.busy, sc.changed), ([], ["a/two.txt"]))
        self.assertIn("a.zip", self.dest.uploads())

    def test_unchanged_file_in_use_is_no_trouble(self):
        self.run_backup()
        self.hold("b/big.bin")
        sc, res = self.run_backup(minute=1)
        self.assertEqual((sc.busy, sc.waiting, sc.gone), ([], [], []))  # not read: nothing to hold back
        self.assertIsNone(res)

    def test_changed_file_in_use(self):
        self.run_backup()
        self.write("b/big.bin", "C" * 90)
        self.hold("b/big.bin")
        sc, res = self.run_backup(minute=1)
        self.assertEqual((sc.busy, sc.changed, sc.gone), (["b/big.bin"], [], []))
        self.assertIsNone(res)

    def test_new_file_waits(self):
        self.run_backup()
        self.write("a/new.txt", "n")
        held = self.hold("a/new.txt")
        sc, _ = self.run_backup(minute=1)
        self.assertEqual((sc.busy, sc.new, sc.waiting), (["a/new.txt"], [], []))     # not in any bundle yet
        held.close()
        sc, _ = self.run_backup(minute=2)
        self.assertEqual(sc.new, ["a/new.txt"])
        self.assertIn("a/new.txt", self.zip_names("T backup/a.zip"))


if __name__ == "__main__":
    unittest.main()
