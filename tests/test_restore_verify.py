"""Restore (latest and old versions) and verify, through the service, against the in-memory destination."""
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pastoo import jobs as jobs_mod, paths  # noqa: E402
from pastoo.jobs import Job  # noqa: E402
from pastoo.remote.fake import FakeDestination  # noqa: E402
from pastoo.runlock import RunLock  # noqa: E402
from pastoo.service import BackupService  # noqa: E402
from pastoo.store import Store  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.out = os.path.join(self.tmp, "out")
        self.write("a/one.txt", "1" * 30)
        self.write("a/two.txt", "2" * 30)
        self.write("b/big.bin", "B" * 120)      # its own bundle (>= big_file); b/ > limit
        self.write("top.txt", "t")
        self.job = Job(id="t", name="Test", source=self.src, remote_root="T backup", bundle_limit=100, big_file=50)
        self.saved = jobs_mod.JOBS, paths.DATA_DIR, paths.LOG_FILE
        jobs_mod.JOBS = [self.job]
        paths.DATA_DIR = self.tmp
        paths.LOG_FILE = os.path.join(self.tmp, "backup.log")
        self.dest = FakeDestination()
        self.db = os.path.join(self.tmp, "state.db")
        self.lock_path = os.path.join(self.tmp, "run.lock")
        self.service = BackupService(
            store_factory=lambda: Store(self.db),
            destination_factory=lambda: self.dest, lock_factory=lambda: RunLock(self.lock_path))
        self.done = threading.Event()
        self.service.listeners.append(self.on_message)

    def tearDown(self):
        jobs_mod.JOBS, paths.DATA_DIR, paths.LOG_FILE = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.src, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, rel, base=None):
        with open(os.path.join(base or self.out, *rel.split("/"))) as f:
            return f.read()

    def on_message(self, m):
        if m["type"] in ("run", "task") and m[m["type"]]["phase"] == "done":
            self.result = m[m["type"]]["result"]
            self.done.set()

    def wait(self, why_not=None):
        self.assertIsNone(why_not)
        self.assertTrue(self.done.wait(10), "did not finish")
        self.service.wait_idle(5)
        self.done.clear()
        return self.result

    def backup(self):
        self.assertTrue(self.service.start("t"))
        return self.wait()


class RestoreTest(Base):
    def test_latest_into_another_folder(self):
        self.backup()
        res = self.wait(self.service.start_restore("t", "latest", ["a/two.txt", "b/big.bin"], self.out))
        self.assertEqual((res["status"], res["written"]), ("ok", 2))
        self.assertEqual(self.read("a/two.txt"), "2" * 30)
        self.assertEqual(self.read("b/big.bin"), "B" * 120)
        self.assertFalse(os.path.exists(os.path.join(self.out, "a", "one.txt")))

    def test_into_the_original_place_skips_or_replaces(self):
        self.backup()
        os.remove(os.path.join(self.src, "a", "one.txt"))       # deleted by mistake
        self.write("a/two.txt", "edited since")
        res = self.wait(self.service.start_restore("t", "latest", ["a/one.txt", "a/two.txt"], ""))
        self.assertEqual((res["written"], res["skipped"]), (1, ["a/two.txt"]))
        self.assertEqual(self.read("a/one.txt", self.src), "1" * 30)
        self.assertEqual(self.read("a/two.txt", self.src), "edited since")
        res = self.wait(self.service.start_restore("t", "latest", ["a/two.txt"], "", overwrite=True))
        self.assertEqual(self.read("a/two.txt", self.src), "2" * 30)

    def test_old_version(self):
        self.backup()
        self.write("a/one.txt", "x" * 30)
        self.backup()
        browse = self.service.browse("t")
        self.assertEqual([v["key"] for v in browse["versions"]], ["a.zip"])
        vid = browse["versions"][0]["id"]
        files = self.service.version_files("t", vid)
        self.assertEqual(sorted(f[0] for f in files), ["a/one.txt", "a/two.txt"])
        res = self.wait(self.service.start_restore("t", vid, ["a/one.txt"], self.out))
        self.assertEqual(res["written"], 1)
        self.assertEqual(self.read("a/one.txt"), "1" * 30)            # as it was before the change

    def test_old_version_of_a_single_file(self):
        self.backup()
        self.write("b/big.bin", "C" * 120)
        self.backup()
        v = next(v for v in self.service.browse("t")["versions"] if v["key"] == "b/big.bin")
        self.assertEqual(self.service.version_files("t", v["id"]), [["b/big.bin", 120, None]])
        self.wait(self.service.start_restore("t", v["id"], ["b/big.bin"], self.out))
        self.assertEqual(self.read("b/big.bin"), "B" * 120)

    def test_old_version_from_before_the_kind_was_kept(self):
        self.backup()
        self.write("a/one.txt", "x" * 30)
        self.backup()
        store = Store(self.db)
        store.db.execute("UPDATE versions SET dir = NULL, zip = NULL")
        store.db.commit()
        store.close()
        vid = self.service.browse("t")["versions"][0]["id"]
        self.assertEqual(sorted(f[0] for f in self.service.version_files("t", vid)), ["a/one.txt", "a/two.txt"])

    def test_bad_requests_fail_cleanly(self):
        self.backup()
        res = self.wait(self.service.start_restore("t", "latest", ["no/such.txt"], self.out))
        self.assertEqual(res["status"], "failed")
        self.assertIn("not in the backup", res["error"])
        res = self.wait(self.service.start_restore("t", "latest", ["top.txt"], "relative\\path"))
        self.assertIn("not a full folder path", res["error"])


class VerifyTest(Base):
    def test_all_good_and_recorded(self):
        self.backup()
        res = self.wait(self.service.start_verify("t"))
        self.assertEqual((res["status"], res["bundles"], res["files"]), ("ok", 3, 4))
        check = self.service.browse("t")["last_check"]
        self.assertEqual((check["full"], check["bad"]), (1, 0))

    def test_sample(self):
        self.backup()
        res = self.wait(self.service.start_verify("t", sample=2))
        self.assertEqual(res["bundles"], 2)
        self.assertEqual(self.service.browse("t")["last_check"]["full"], 0)

    def test_finds_damage(self):
        self.backup()
        state = Store(self.db).load(self.job)
        self.dest.items[state["units"]["b/big.bin"]["id"]]["data"] = b"X" * 120      # same size, other content
        a = self.dest.items[state["units"]["a.zip"]["id"]]
        a["data"] = a["data"][:-30]                                                 # cut short
        res = self.wait(self.service.start_verify("t"))
        self.assertEqual(res["status"], "failed")
        what = {(p[0], p[1]) for p in res["problems"]}
        self.assertIn(("b/big.bin", "b/big.bin"), what)
        self.assertIn(("a.zip", ""), what)
        self.assertEqual(self.service.browse("t")["last_check"]["bad"], len(res["problems"]))

    def test_one_thing_at_a_time(self):
        self.backup()
        gate = threading.Event()
        real = self.dest.download
        self.dest.download = lambda eid: gate.wait(5) and real(eid)
        self.assertIsNone(self.service.start_verify("t"))
        self.assertIsNotNone(self.service.start_restore("t", "latest", ["top.txt"], self.out))
        self.assertFalse(self.service.start("t"))
        gate.set()
        self.wait()
        other = RunLock(self.lock_path)             # backup.bat running
        self.assertTrue(other.acquire())
        try:
            self.assertIn("command line", self.service.start_verify("t"))
        finally:
            other.release()


if __name__ == "__main__":
    unittest.main()
