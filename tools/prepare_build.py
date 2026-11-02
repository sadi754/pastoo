"""Before PyInstaller: make build/pastoo.ico (the icon at every Windows size) and
build/version_info.txt (the version shown in the .exe's Properties) and build/version.txt
(for the installer). Run by build.bat."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pastoo import VERSION, icons  # noqa: E402

BUILD = ROOT / "build"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def make_icon():
    # each size drawn on its own (not scaled down from the big one), so small icons stay crisp
    images = [icons.icon(size) for size in SIZES]
    images[-1].save(BUILD / "pastoo.ico", sizes=[(s, s) for s in SIZES], append_images=images[:-1])


def make_version_info():
    numbers = tuple(int(n) for n in VERSION.split(".")) + (0,)
    strings = {
        "CompanyName": "sadi754",
        "FileDescription": "Pastoo",
        "FileVersion": VERSION,
        "InternalName": "Pastoo",
        "LegalCopyright": "(c) 2026 sadi754",
        "OriginalFilename": "Pastoo.exe",
        "ProductName": "Pastoo",
        "ProductVersion": VERSION,
    }
    table = ",\n          ".join(f"StringStruct('{k}', '{v}')" for k, v in strings.items())
    (BUILD / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
          {table}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")


if __name__ == "__main__":
    BUILD.mkdir(exist_ok=True)
    make_icon()
    make_version_info()
    (BUILD / "version.txt").write_text(VERSION, encoding="ascii")
    print(f"[build] Pastoo {VERSION}: icon and version info ready")
