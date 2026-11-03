"""The app's backup service (threads, events, history, the lock) against the in-memory destination."""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pastoo import app, backuplog, jobs as jobs_mod, paths, settings  # noqa: E402
from pastoo.engine import runner  # noqa: E402
from pastoo.jobs import Job  # noqa: E402
from pastoo.remote.fake import FakeDestination  # noqa: E402
from pastoo.runlock import RunLock  # noqa: E402
from pastoo.service import BackupService, next_auto  # noqa: E402
from pastoo.store import Store  # noqa: E402


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        for rel, text in (("a/one.txt", "1" * 30), ("b/two.txt", "2" * 30), ("top.txt", "t")):
            path = os.path.join(self.src, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
        self.job = Job(id="t", name="Test", source=self.src, remote_root="T backup", bundle_limit=100, big_file=50)
        self.saved = jobs_mod.JOBS, paths.DATA_DIR, paths.LOG_FILE
        jobs_mod.JOBS = [self.job]
        paths.DATA_DIR = self.tmp
        paths.LOG_FILE = os.path.join(self.tmp, "backup.log")
        self.dest = FakeDestination()
        self.lock_path = os.path.join(self.tmp, "run.lock")
        db = os.path.join(self.tmp, "state.db")
        self.service = BackupService(
            store_factory=lambda: Store(db),
            destination_factory=lambda: self.dest,
            lock_factory=lambda: RunLock(self.lock_path))
        self.messages = []
        self.done = threading.Event()
        self.service.listeners.append(self.on_message)

    def tearDown(self):
        jobs_mod.JOBS, paths.DATA_DIR, paths.LOG_FILE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def on_message(self, m):
        self.messages.append(m)
        if m["type"] == "run" and m["run"]["phase"] == "done":
            self.result = m["run"]["result"]
            self.done.set()

    def backup(self):
        self.done.clear()
        self.assertTrue(self.service.start("t"))
        self.assertTrue(self.done.wait(10), "the backup did not finish")
        self.service.wait_idle(5)
        return self.result

    def test_backup_records_history_and_status(self):
        self.assertEqual(self.backup()["status"], "ok")
        s = self.service.status(self.job)
        self.assertEqual((s["files"], s["bundles"]), (3, 3))
        self.assertEqual(s["last_run"]["status"], "ok")
        self.assertIsNotNone(s["last_ok"])
        self.assertEqual(s["pending"]["todo"], 0)
        self.assertFalse(s["running"])
        self.assertIn("ok", [r["status"] for r in s["recent"]])
        progress = [m for m in self.messages if m["type"] == "run" and m["run"]["phase"] == "uploading"]
        self.assertTrue(any(m["run"]["i"] == m["run"]["total"] == 3 for m in progress))
        with open(paths.LOG_FILE, encoding="utf8") as f:
            self.assertIn("== done", f.read())

    def test_second_backup_is_nothing(self):
        self.backup()
        self.assertEqual(self.backup()["status"], "nothing")
        self.assertEqual([r["status"] for r in self.service.status(self.job)["recent"]], ["nothing", "ok"])

    def test_check_finds_changes(self):
        self.backup()
        with open(os.path.join(self.src, "top.txt"), "w") as f:
            f.write("changed")
        self.service.check("t")
        for _ in range(100):
            if self.service.status(self.job)["pending"]["changed"]:
                break
            threading.Event().wait(0.05)
        p = self.service.status(self.job)["pending"]
        self.assertEqual((p["changed"], p["todo"]), (1, 1))

    def test_preview_and_history_detail(self):
        self.backup()
        with open(os.path.join(self.src, "top.txt"), "w") as f:
            f.write("changed")
        os.remove(os.path.join(self.src, "b", "two.txt"))
        p = self.service.preview("t")
        self.assertEqual([c[0] for c in p["changed"]], ["top.txt"])
        self.assertEqual(p["deleted"], [["b/two.txt", 30, "b.zip"]])
        self.assertEqual(self.service.status(self.job)["pending"]["deleted"], 1)
        self.backup()
        runs = self.service.history("t")
        self.assertEqual([r["status"] for r in runs], ["ok", "ok"])
        detail = self.service.run_detail("t", runs[0]["id"])
        self.assertEqual(detail["changes"]["deleted"], [["b/two.txt", 30, "b.zip"]])
        self.assertEqual(detail["changes"]["changed"], [["top.txt", 7, "_files.zip"]])

    def test_old_run_detail_reads_the_report_from_the_destination(self):
        self.backup()
        store = Store(os.path.join(self.tmp, "state.db"))
        store.db.execute("UPDATE runs SET changes = NULL")
        store.db.commit()
        store.close()
        run = self.service.history("t")[0]
        detail = self.service.run_detail("t", run["id"])
        self.assertIn("first full backup: 3 files", detail["report_text"])

    def test_only_one_backup_at_a_time(self):
        other = RunLock(self.lock_path)             # e.g. backup.bat running
        self.assertTrue(other.acquire())
        try:
            self.assertEqual(self.backup()["status"], "busy")
        finally:
            other.release()
        self.assertEqual(self.backup()["status"], "ok")

    def test_stop(self):
        gate = threading.Event()
        real = self.dest.upload
        self.dest.upload = lambda *a: gate.wait(5) and real(*a)     # uploads hang until released
        self.done.clear()
        self.service.start("t")
        self.assertFalse(self.service.start("t"))   # already running
        threading.Event().wait(0.3)
        self.service.stop()
        self.assertTrue(self.done.wait(5))
        gate.set()
        self.assertEqual(self.result["status"], "cancelled")
        self.assertEqual(self.service.status(self.job)["last_run"]["status"], "cancelled")

    def auto_backup(self):
        self.done.clear()
        self.assertTrue(self.service.start("t", auto=True))
        self.assertTrue(self.done.wait(10), "the backup did not finish")
        self.service.wait_idle(5)
        return self.result

    def low_guard(self):
        """The guard's limits for a folder of 3 files."""
        saved = runner.GUARD_DELETED, runner.GUARD_MIN_FILES
        runner.GUARD_DELETED, runner.GUARD_MIN_FILES = 100, 1
        self.addCleanup(lambda: setattr(runner, "GUARD_DELETED", saved[0]) or setattr(runner, "GUARD_MIN_FILES", saved[1]))

    def test_automatic_backup_waits_when_many_files_go(self):
        self.backup()
        self.low_guard()
        os.remove(os.path.join(self.src, "a", "one.txt"))
        result = self.auto_backup()
        self.assertEqual((result["status"], result["error"]), ("held", "1 of 3 files deleted"))
        self.assertEqual(self.service.status(self.job)["last_run"]["status"], "held")
        self.assertEqual(self.service.health()[0], "held")
        self.assertEqual(self.dest.uploads().count("_index.txt"), 1)        # nothing went up after the first
        self.assertEqual(self.backup()["status"], "ok")                       # pressed by hand: it goes
        self.assertNotEqual(self.service.health()[0], "held")

    def test_moved_files_are_not_deleted_ones(self):
        self.backup()
        self.low_guard()
        os.makedirs(os.path.join(self.src, "c"))
        os.replace(os.path.join(self.src, "a", "one.txt"), os.path.join(self.src, "c", "one.txt"))
        self.assertEqual(self.auto_backup()["status"], "ok")

    def test_automatic_backup_with_nothing_to_do_stays_out_of_the_history(self):
        self.backup()
        before = len(self.service.history("t"))
        self.assertEqual(self.auto_backup()["status"], "nothing")
        self.assertEqual(len(self.service.history("t")), before)
        self.assertIn("t", settings.load()["auto_checked"])

    def test_missing_folder_is_refused(self):
        self.backup()
        shutil.rmtree(self.src)                                              # e.g. its drive unplugged
        result = self.auto_backup()
        self.assertEqual(result["status"], "failed")
        self.assertIn("isn't there", result["error"])
        self.assertEqual(self.service.status(self.job)["files"], 3)         # the backup still has them all

    def test_due_job(self):
        hourly = Job(**{**self.job.__dict__, "schedule": "hours", "schedule_hours": 2})
        jobs_mod.JOBS = [hourly]
        self.assertEqual(self.service.due_job(), hourly)                     # never backed up: due
        self.backup()
        self.assertIsNone(self.service.due_job())
        self.assertEqual(self.service.due_job(time.time() + 3 * 3600), hourly)
        jobs_mod.JOBS = [self.job]                                           # "off"
        self.assertIsNone(self.service.due_job(time.time() + 99 * 3600))

    def test_next_daily_backup(self):
        job = Job(**{**self.job.__dict__, "schedule": "daily", "schedule_time": "21:00"})
        day = time.mktime((2026, 11, 2, 0, 0, 0, 0, 0, -1))
        at = lambda h, m=0, d=0: day + d * 86400 + h * 3600 + m * 60   # noqa: E731
        self.assertEqual(next_auto(job, at(21, 30, -1), at(20)), at(21))     # later today
        self.assertEqual(next_auto(job, at(21, 30, -1), at(22)), at(21))     # passed today, not done: due
        self.assertEqual(next_auto(job, at(21, 5), at(22)), at(21, 0, 1))    # done today: tomorrow
        self.assertEqual(next_auto(job, at(9, 0, -3), at(8)), at(21, 0, -1))  # the PC was off: due now

    def test_tray_listener_takes_every_event(self):
        class FakeTray:
            def __init__(self):
                self.shown, self.notes = [], []

            def show(self, *args):
                self.shown.append(args[0])

            def notify(self, title, text):
                self.notes.append(title)

        tray = FakeTray()
        self.service.listeners.append(app.tray_listener(tray, lambda: tray.show("refreshed")))
        with self.assertNoLogs("pastoo.service", "ERROR"):
            self.assertEqual(self.backup()["status"], "ok")
            self.service._publish({"type": "task", "task": {"phase": "done"}, "line": ""})
            self.service._publish({"type": "usage", "usage": {"used": 1, "total": 2}})
        self.assertIn("running", tray.shown)
        self.assertEqual(tray.notes, ["Backup finished"])


if __name__ == "__main__":
    unittest.main()
