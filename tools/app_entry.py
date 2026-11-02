"""Entry point of Pastoo.exe (PyInstaller needs a script; the app itself is the pastoo package)."""
import sys

from pastoo.__main__ import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
