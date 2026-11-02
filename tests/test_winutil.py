"""Windows helpers: finding the window process's children (the tray brings its window to the front)."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pastoo import winutil  # noqa: E402

SPAWN_CHILD = ("import subprocess, sys, time\n"
               "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
               "print(c.pid, flush=True)\n"
               "time.sleep(30)\n")


class ProcessTree(unittest.TestCase):
    def test_includes_children_and_grandchildren(self):
        parent = subprocess.Popen([sys.executable, "-c", SPAWN_CHILD], stdout=subprocess.PIPE, text=True)
        try:
            child = int(parent.stdout.readline())
            tree = winutil.process_tree(parent.pid)
            self.assertIn(parent.pid, tree)
            self.assertIn(child, tree)
            self.assertNotIn(os.getpid(), tree)
        finally:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(parent.pid)], capture_output=True)
            parent.stdout.close()
            parent.wait()

    def test_unknown_pid_is_just_itself(self):
        self.assertEqual(winutil.process_tree(0xFFFFFFF0), {0xFFFFFFF0})


if __name__ == "__main__":
    unittest.main()
