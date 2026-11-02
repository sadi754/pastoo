"""Entry point of pastoo-cli.exe: the command line only - without a command it shows the help
instead of starting the app (Pastoo.exe does that)."""
import sys

from pastoo.__main__ import main

if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(main(args if args and not args[0].startswith("--") else ["help"]))
