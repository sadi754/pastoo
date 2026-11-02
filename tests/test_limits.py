"""files.ir plan limits: files bigger than one upload go up in parts, reports are capped,
replaced _index.txt / _backup.json are deleted for good, and the usage count."""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pastoo.engine import manifest, restore, runner  # noqa: E402
from pastoo.engine.verify import verify  # noqa: E402
from pastoo.jobs import Job  # noqa: E402
from pastoo.remote.fake import FakeDestination  # noqa: E402
from pastoo.store import Store  # noqa: E402

T0 = time.mktime((2026, 10, 17, 12, 0, 0, 0, 0, -1))
BIG = bytes(range(256)) * 5          # 1280 bytes, all byte values


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.job = Job(id="t", name="t", source=self.src, remote_root="T backup",
                       bundle_limit=100, big_file=50, part_size=500, keep_reports=2)
        self.store = Store(os.path.join(self.tmp, "state.db"))
        self.dest = FakeDestination()
        self.ticks = 0
        self.write("a/one.txt", b"1" * 30)
        self.write("b/big.bin", BIG)         # > part_size: 3 parts (500 + 500 + 280)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, data):
        path = os.path.join(self.src, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        self.ticks += 1
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000 * self.ticks))

    def run_backup(self, minute=0, **kw):
        state = self.store.load(self.job)
        sc = runner.scan(self.job, state)
        if not runner.needs_run(state, sc):
            return None
        return runner.upload(self.job, state, sc, self.dest, save=lambda: self.store.save(self.job, state),
                             emit=lambda kind, msg, **d: None, clock=lambda: T0 + minute * 60, **kw)

    def live(self):
        return self.dest.live_files()


class Parts(Base):
    def test_big_file_goes_up_in_parts(self):
        self.run_backup()
        live = self.live()
        parts = sorted(p for p in live if p.startswith("T backup/b/big.bin.parts/"))
        self.assertEqual(parts, ["T backup/b/big.bin.parts/part001", "T backup/b/big.bin.parts/part002",
                                 "T backup/b/big.bin.parts/part003"])
        self.assertEqual(b"".join(live[p] for p in parts), BIG)
        self.assertTrue(all(len(live[p]) <= 500 for p in parts))
        unit = self.store.load(self.job)["units"]["b/big.bin"]
        self.assertTrue(unit["parts"])
        self.assertEqual(unit["size"], len(BIG))

    def test_restore_and_verify(self):
        self.run_backup()
        state = self.store.load(self.job)
        out = os.path.join(self.tmp, "out")
        res = restore.restore(self.job, state, self.dest, ["b/big.bin"], out)
        self.assertEqual(res["written"], 1)
        with open(os.path.join(out, "b", "big.bin"), "rb") as f:
            self.assertEqual(f.read(), BIG)
        self.assertEqual(verify(state, self.dest, sorted(state["units"]))["problems"], [])
        # a damaged part is caught, and nothing half-written is left
        part = next(e for e in self.dest.items.values() if e["name"] == "part002")
        part["data"] = b"x" * len(part["data"])
        problems = verify(state, self.dest, ["b/big.bin"])["problems"]
        self.assertEqual(problems, [["b/big.bin", "b/big.bin", "content differs"]])
        os.remove(os.path.join(out, "b", "big.bin"))
        res = restore.restore(self.job, state, self.dest, ["b/big.bin"], out)
        self.assertEqual(res["bad"], ["b/big.bin"])
        self.assertEqual(os.listdir(os.path.join(out, "b")), [])

    def test_changed_big_file_keeps_the_old_parts_as_a_version(self):
        self.run_backup()
        self.write("b/big.bin", BIG[::-1])
        self.run_backup(minute=1)
        state = self.store.load(self.job)
        v = state["versions"][0]
        self.assertEqual((v["key"], v["parts"]), ("b/big.bin", True))
        self.assertEqual(manifest.fetch(self.job, self.dest)["versions"][0]["parts"], True)
        from pastoo.engine import blob
        self.assertEqual(blob.read(self.dest, v), BIG)                     # the old content, from _versions
        self.assertEqual(blob.read(self.dest, state["units"]["b/big.bin"]), BIG[::-1])

    def test_stopped_half_way_leaves_nothing_behind(self):
        self.dest.fail_after = 2            # a.zip, part001 - then part002 fails
        with self.assertRaises(runner.Failed):
            self.run_backup(jobs=1)
        self.dest.fail_after = None
        self.run_backup(minute=1, jobs=1)
        folders = [e for e in self.dest.items.values() if e["type"] == "folder" and e["name"] == "big.bin.parts"]
        self.assertEqual(len(folders), 1)   # the half-done one was deleted
        self.assertEqual(len([e for e in self.dest.items.values() if e["parent_id"] == folders[0]["id"]]), 3)

    def test_small_files_stay_whole(self):
        self.run_backup()
        self.assertIn("T backup/a.zip", self.live())
        self.assertFalse(self.store.load(self.job)["units"]["a.zip"]["parts"])


class Tidy(Base):
    def test_only_the_newest_reports_stay(self):
        for minute in range(4):
            self.write("a/one.txt", str(minute).encode() * 30)
            self.run_backup(minute=minute)
        reports = sorted(p for p in self.live() if p.startswith("T backup/_changes/"))
        self.assertEqual([p[-8:] for p in reports], ["1202.txt", "1203.txt"])

    def test_old_index_and_manifest_are_deleted_for_good(self):
        self.run_backup()
        first = self.store.load(self.job)
        self.write("a/one.txt", b"2" * 30)
        self.run_backup(minute=1)
        self.assertNotIn(first["index_id"], self.dest.items)       # not in the trash: gone
        self.assertNotIn(first["manifest_id"], self.dest.items)


class Usage(Base):
    def test_file_count(self):
        from pastoo import jobs as jobs_mod
        from pastoo.service import BackupService
        saved = jobs_mod.JOBS
        jobs_mod.JOBS = [self.job]
        try:
            self.run_backup()
            service = BackupService(store_factory=lambda: Store(os.path.join(self.tmp, "state.db")),
                                    destination_factory=lambda: self.dest)
            store = service.store_factory()
            store.finish_run(store.start_run(self.job), "ok", report="_changes/x.txt")
            store.close()
            u = service.usage()
            # a.zip + 3 parts + _index + _backup.json + 1 report
            self.assertEqual(u["files"], 7)
            self.assertEqual(u["files"], sum(1 for _ in self.live()))
            self.assertIsNone(u["space_used"])                      # the fake can't tell
        finally:
            jobs_mod.JOBS = saved


class CannedFilesIr:
    """FilesIr.plan() against canned answers instead of the network."""

    PRODUCTS = [
        {"id": 1, "name": "Free", "free": True, "available_space": 5 << 30, "max_file_count": 1000,
         "max_upload_size": 50 << 20},
        {"id": 2, "name": "Growth", "free": False, "available_space": 10 << 30, "max_file_count": 3000,
         "max_upload_size": 500 << 20},
    ]

    def make(self, user, available):
        from pastoo.remote.filesir import FilesIr

        class Canned(FilesIr):
            def call(_, method, path, body=None, multipart=None, raw=False):
                if path.startswith("/users/me"):
                    return 200, {"user": user}
                if path.startswith("/billing/products"):
                    return 200, {"pagination": {"data": self.PRODUCTS}}
                if path.startswith("/user/space-usage"):
                    return 200, {"used": 1, "available": available}
                raise AssertionError(path)
        return Canned("key")


class PlanDetection(unittest.TestCase, CannedFilesIr):
    def test_free_without_a_subscription(self):
        limits = self.make({"subscriptions": []}, 5 << 30).plan()
        self.assertEqual(limits, {"name": "Free", "space": 5 << 30, "files": 1000, "file": 50 << 20})

    def test_subscription_wins(self):
        limits = self.make({"subscriptions": [{"product_id": 2}]}, 10 << 30).plan()
        self.assertEqual((limits["name"], limits["files"], limits["file"]), ("Growth", 3000, 500 << 20))

    def test_matched_by_space_when_the_subscription_says_nothing(self):
        self.assertEqual(self.make({"subscriptions": [{}]}, 10 << 30).plan()["name"], "Growth")

    def test_limits_set_on_the_account_win(self):
        limits = self.make({"subscriptions": [], "max_file_count": 1234}, 5 << 30).plan()
        self.assertEqual(limits["files"], 1234)


class LimitSettings(unittest.TestCase, CannedFilesIr):
    def setUp(self):
        from pastoo import jobs as jobs_mod, paths, settings
        self.tmp = tempfile.mkdtemp()
        self.saved = jobs_mod.JOBS, paths.DATA_DIR
        paths.DATA_DIR = self.tmp
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        settings.save({"jobs": [{"id": "photos", "name": "Photos", "source": src, "remote_root": "Photos backup"}]})
        jobs_mod.reload()

    def tearDown(self):
        from pastoo import jobs as jobs_mod, paths
        jobs_mod.JOBS, paths.DATA_DIR = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def service(self, dest):
        from pastoo.service import BackupService
        return BackupService(store_factory=lambda: Store(os.path.join(self.tmp, "state.db")),
                             destination_factory=lambda: dest)

    def test_free_until_files_ir_has_said(self):
        from pastoo import jobs as jobs_mod, settings
        self.assertEqual(settings.limits(), settings.FREE)
        self.assertEqual(jobs_mod.JOBS[0].part_size, (50 << 20) * 9 // 10)

    def test_detected_plan_is_kept_and_sets_the_part_size(self):
        from pastoo import jobs as jobs_mod, settings
        u = self.service(self.make({"subscriptions": [{"product_id": 2}]}, 10 << 30)).usage()
        self.assertEqual((u["limits"]["name"], u["files_total"], u["space_total"]), ("Growth", 3000, 10 << 30))
        self.assertEqual(settings.load()["detected_limits"]["files"], 3000)              # kept for next time
        self.assertEqual(jobs_mod.JOBS[0].part_size, (500 << 20) * 9 // 10)

    def test_set_by_hand(self):
        from pastoo import jobs as jobs_mod
        service = self.service(self.make({"subscriptions": []}, 5 << 30))
        service.save_app({"limits_mode": "custom", "custom_limits": {"space_gb": 20, "files": 4000, "file_mb": 100}})
        u = service.usage()
        self.assertEqual((u["mode"], u["files_total"], u["space_total"]), ("custom", 4000, 20 << 30))
        self.assertEqual(jobs_mod.JOBS[0].part_size, (100 << 20) * 9 // 10)
        with self.assertRaises(ValueError):
            service.save_app({"custom_limits": {"space_gb": 0, "files": 4000, "file_mb": 100}})
        service.save_app({"limits_mode": "auto"})
        self.assertEqual(service.usage()["files_total"], 1000)                           # back to files.ir's

    def test_files_ir_unreachable_keeps_the_last_known_plan(self):
        from pastoo.remote.base import RemoteError
        self.service(self.make({"subscriptions": [{"product_id": 2}]}, 10 << 30)).usage()

        class Down(FakeDestination):
            def plan(self):
                raise RemoteError("no network")
        u = self.service(Down()).usage()
        self.assertEqual((u["plan_error"], u["files_total"]), ("no network", 3000))


if __name__ == "__main__":
    unittest.main()
