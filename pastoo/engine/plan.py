"""Which files go into which bundle.

Every folder of job.bundle_limit or less goes up as one "<folder>.zip" (next
to where the folder would be); bigger folders are split into their
subfolders. Files left directly in a big folder go into "_files.zip" there,
except files of job.big_file or more, which go up as they are.
"""
import hashlib

from ..util import join


def plan_units(job, files):
    """{key: unit} - key is the bundle's path under the job's remote root.
    unit = {"dir": folder there (relative), "name": file name there,
            "files": [relative paths], "zip": bool}"""
    size_of, subdirs, loose = {}, {}, {}
    for rel, (size, _) in files.items():
        parts = rel.split("/")
        loose.setdefault("/".join(parts[:-1]), []).append(rel)
        for i in range(len(parts)):                  # every folder above the file
            d = "/".join(parts[:i])
            size_of[d] = size_of.get(d, 0) + size
            if i:
                subdirs.setdefault("/".join(parts[:i - 1]), set()).add(d)

    units = {}

    def add(d, name, members, zipped):
        units[join(d, name)] = {"dir": d, "name": name, "files": sorted(members), "zip": zipped}

    def visit(d):
        here = loose.get(d, [])
        taken = set()
        for rel in here:
            if files[rel][0] >= job.big_file:
                name = rel.rpartition("/")[2]
                taken.add(name.lower())
                add(d, name, [rel], False)
        small = [r for r in here if files[r][0] < job.big_file]
        if small:
            taken.add("_files.zip")
            add(d, "_files.zip", small, True)
        for s in sorted(subdirs.get(d, ())):
            if size_of[s] <= job.bundle_limit:
                base = s.rpartition("/")[2]
                name = base + ".zip" if (base + ".zip").lower() not in taken else base + " (folder).zip"
                add(d, name, [r for r in files if r.startswith(s + "/")], True)
            else:
                visit(s)

    visit("")
    return units


def signature(unit, hashes):
    """Changes when any file of the bundle is added, removed, renamed or edited."""
    h = hashlib.sha1()
    for rel in unit["files"]:
        h.update(f"{rel}\t{hashes[rel]}\n".encode())
    return h.hexdigest()
