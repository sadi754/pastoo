"""After PyInstaller: zip dist\\Pastoo into dist\\Pastoo-<version>-win64.zip, ready to share. Run by build.bat."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pastoo import VERSION  # noqa: E402

folder = ROOT / "dist" / "Pastoo"
target = ROOT / "dist" / f"Pastoo-{VERSION}-win64.zip"
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            archive.write(path, Path("Pastoo") / path.relative_to(folder))
print(f"[build] {target.relative_to(ROOT)}: {target.stat().st_size / 1024 / 1024:.1f} MB")
