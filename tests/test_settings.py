"""Settings: jobs in settings.json, measuring the rules, the key in Credential Manager, start with Windows."""
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pastoo import autostart, jobs as jobs_mod, keystore, paths, settings  # noqa: E402
from pastoo.engine.scan import measure  # noqa: E402
from pastoo.jobs import Job  # noqa: E402
from pastoo.remote.base import RemoteError  # noqa: E402
from pastoo.remote.fake import FakeDestination  # noqa: E402
from pastoo.runlock import RunLock  # noqa: E402
from pastoo.service import BackupService  # noqa: E402
from pastoo.store import Store  # noqa: E402

TEST_TARGET = "Pastoo/unit-test"
# the job every test starts with: skips folders named .venv and *.mkv files
TEST_JOB = {"id": "photos", "name": "Photos", "source": "", "remote_root": "Photos backup",
            "skip_dir_names": [".venv"], "skip_paths": [], "skip_files": ["*.mkv"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = jobs_mod.JOBS, paths.DATA_DIR, paths.LOG_FILE
        paths.DATA_DIR = self.tmp
        paths.LOG_FILE = os.path.join(self.tmp, "backup.log")
        self.src = os.path.join(self.tmp, "src")
        for rel, n in (("a/one.txt", 30), ("a/.venv/lib.py", 500), ("b/movie.mkv", 900), ("b/two.txt", 20),
                       ("Old/x.txt", 40)):
            path = os.path.join(self.src, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("x" * n)
        settings.save({"jobs": [dict(TEST_JOB, source=self.src)]})
        jobs_mod.reload()
        self.dest = FakeDestination()
        self.db = os.path.join(self.tmp, "state.db")
        self.service = BackupService(
            store_factory=lambda: Store(self.db),
            destination_factory=lambda: self.dest, lock_factory=lambda: RunLock(os.path.join(self.tmp, "run.lock")))

    def tearDown(self):
        jobs_mod.JOBS, paths.DATA_DIR, paths.LOG_FILE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def form(self, **over):
        f = {"name": "Docs", "source": self.src, "remote_root": "Docs backup", "skip_dir_names": [".venv"],
             "skip_paths": ["old"], "skip_files": ["*.MKV"], "bundle_mb": 10, "big_file_mb": 5,
             "keep_versions": 5, "keep_days": 30}
        f.update(over)
        return f


class Jobs(Base):
    def test_no_jobs_until_one_is_added(self):
        os.remove(settings.file_path())
        self.assertEqual(jobs_mod.reload(), [])
        self.assertEqual(self.service.health(), ("old", None))

    def test_add_change_remove(self):
        saved = self.service.save_job(self.form())
        self.assertEqual(saved["id"], "docs")
        self.assertEqual([j.id for j in jobs_mod.JOBS], ["photos", "docs"])
        self.assertEqual(jobs_mod.get("docs").bundle_limit, 10 << 20)
        self.service.save_job(self.form(id="docs", name="My docs", keep_days=60))
        self.assertEqual((jobs_mod.get("docs").name, jobs_mod.get("docs").keep_days), ("My docs", 60))
        self.assertEqual(settings.load()["jobs"][1]["name"], "My docs")       # on disk too
        self.service.remove_job("docs")
        self.assertEqual([j.id for j in jobs_mod.JOBS], ["photos"])
        self.service.remove_job("photos")                                   # the last one may go too
        self.assertEqual(jobs_mod.JOBS, [])

    def test_checks(self):
        for bad, why in (({"source": os.path.join(self.tmp, "nope")}, "no such folder"),
                         ({"source": "relative"}, "no such folder"),
                         ({"remote_root": "a/b"}, "plain name"),
                         ({"remote_root": "photos BACKUP"}, "used by"),
                         ({"name": ""}, "name"),
                         ({"bundle_mb": 0}, "bundle mb"),
                         ({"keep_versions": "5"}, "keep versions")):
            with self.assertRaises(ValueError) as cm:
                self.service.save_job(self.form(**bad))
            self.assertIn(why, str(cm.exception))

    def test_folders_are_locked_once_backed_up(self):
        saved = self.service.save_job(self.form())
        done = threading.Event()
        self.service.listeners.append(lambda m: m["type"] == "run" and m["run"]["phase"] == "done" and done.set())
        self.service.start("docs")
        self.assertTrue(done.wait(10))
        self.service.wait_idle(5)
        view = self.service.settings_view()
        self.assertTrue(next(j for j in view["jobs"] if j["id"] == "docs")["locked"])
        with self.assertRaises(ValueError):
            self.service.save_job(self.form(id=saved["id"], remote_root="Elsewhere"))
        self.service.save_job(self.form(id=saved["id"], skip_files=[]))         # rules can change

    def test_measure(self):
        m = self.service.measure(self.form())
        self.assertEqual((m["files"], m["size"]), (2, 50))                      # a/one.txt, b/two.txt
        self.assertEqual(m["skipped_files"], 3)
        self.assertEqual(m["skipped"][0], ["*.mkv", 1, 900])                   # biggest first; patterns ignore case
        self.assertIn([".venv  (folders named so)", 1, 500], m["skipped"])
        self.assertIn(["Old", 1, 40], m["skipped"])                            # path rules ignore case
        self.assertEqual(m["bundles"], 2)

    def test_scan_and_measure_agree(self):
        from pastoo.engine.scan import local_files
        job = Job.from_dict({**self.form(), "id": "x", "bundle_limit": 1, "big_file": 1})
        self.assertEqual(set(local_files(job)), set(measure(job)["sizes"]))


class App(Base):
    def test_reminder_days(self):
        self.service.save_app({"reminder_days": 3})
        self.assertEqual(settings.load()["reminder_days"], 3)
        with self.assertRaises(ValueError):
            self.service.save_app({"reminder_days": 0})

    def test_reminder_lists_jobs_with_changes(self):
        # never backed up; its rules skip a/.venv and *.mkv -> 3 files waiting
        self.assertEqual(self.service.reminder(), [("Photos", None, 3)])

    def test_key_is_checked_before_it_is_kept(self):
        self.service.key_check = lambda key: (_ for _ in ()).throw(RemoteError("HTTP 401"))
        with self.assertRaises(ValueError) as cm:
            self.service.set_key("a-key-files-ir-refuses")
        self.assertIn("did not accept", str(cm.exception))
        with self.assertRaises(ValueError):
            self.service.set_key("short")


class KeyStore(unittest.TestCase):
    def tearDown(self):
        keystore.delete(TEST_TARGET)

    def test_write_read_delete(self):
        self.assertIsNone(keystore.read(TEST_TARGET))
        keystore.write("sk-test-كلید-123", TEST_TARGET)
        self.assertEqual(keystore.read(TEST_TARGET), "sk-test-كلید-123")
        keystore.delete(TEST_TARGET)
        self.assertIsNone(keystore.read(TEST_TARGET))


class AutoStart(unittest.TestCase):
    def setUp(self):
        self.saved = autostart.NAME
        autostart.NAME = "Pastoo unit test"

    def tearDown(self):
        autostart.set_enabled(False)
        autostart.NAME = self.saved

    def test_on_and_off(self):
        self.assertFalse(autostart.enabled())
        autostart.set_enabled(True)
        self.assertTrue(autostart.enabled())
        self.assertIn("start.pyw", autostart.command())
        self.assertIn("--minimized", autostart.command())
        autostart.set_enabled(False)
        self.assertFalse(autostart.enabled())

    def write_entry(self, command):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart._KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, autostart.NAME, 0, winreg.REG_SZ, command)

    def test_refresh_follows_a_moved_folder_but_keeps_another_copy(self):
        tmp = tempfile.mkdtemp()
        try:
            other = os.path.join(tmp, "Pastoo.exe")                     # e.g. the installed copy
            self.write_entry(f'"{os.path.join(tmp, "gone", "Pastoo.exe")}" --minimized')
            autostart.refresh()
            self.assertEqual(autostart.registered(), autostart.command())  # that one is gone: points here
            with open(other, "w") as f:
                f.write("")
            self.write_entry(f'"{other}" --minimized')
            autostart.refresh()
            self.assertEqual(autostart.registered(), f'"{other}" --minimized')    # still there: kept
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
