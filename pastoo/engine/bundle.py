import io
import os
import shutil
import zipfile

from . import winfile


def build(job, unit):
    """The bytes that go up for a unit: a zip, or the file itself. Files are read only while no
    other program writes to them (winfile.InUse otherwise - the bundle then fails and is retried)."""
    if not unit["zip"]:
        with winfile.open_read(os.path.join(job.source, unit["files"][0])) as f:
            return f.read()
    buf = io.BytesIO()
    cut = len(unit["dir"]) + 1 if unit["dir"] else 0     # paths inside the zip start at its folder
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in unit["files"]:
            path = os.path.join(job.source, rel)
            info = zipfile.ZipInfo.from_file(path, rel[cut:])
            stored = os.path.splitext(rel)[1].lower() in job.stored_ext
            info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            with winfile.open_read(path) as src, z.open(info, "w") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    return buf.getvalue()
