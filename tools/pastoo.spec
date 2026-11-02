# PyInstaller recipe for Pastoo: a portable folder, dist\Pastoo, with
#   Pastoo.exe       the app (tray icon + window), no console
#   pastoo-cli.exe   the command line (run / restore / history), for scripts and Task Scheduler
# Run build.bat rather than this directly (it makes the icon and version info first).
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is set by PyInstaller

a = Analysis(
    [str(ROOT / "tools" / "app_entry.py"), str(ROOT / "tools" / "cli_entry.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "web"), "web")],         # the window's UI
    # uvicorn picks its event loop and protocols by name at run time; pystray its Windows backend
    hiddenimports=collect_submodules("uvicorn") + ["pystray._win32"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
common = dict(icon=str(ROOT / "build" / "pastoo.ico"), version=str(ROOT / "build" / "version_info.txt"),
              upx=False)    # compressed executables upset antivirus programs more often
app = EXE(pyz, [s for s in a.scripts if s[0] == "app_entry"], [], exclude_binaries=True,
          name="Pastoo", console=False, **common)
cli = EXE(pyz, [s for s in a.scripts if s[0] == "cli_entry"], [], exclude_binaries=True,
          name="pastoo-cli", console=True, **common)
coll = COLLECT(app, cli, a.binaries, a.datas, name="Pastoo", upx=False)
