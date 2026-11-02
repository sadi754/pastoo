"""Start Pastoo from anywhere (used by "Start with Windows"):
    pythonw.exe start.pyw [--minimized]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from pastoo.__main__ import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
