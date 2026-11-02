"""An in-memory destination for the tests - behaves like files.ir, plus
switches to make uploads fail."""
import itertools
import threading

from .base import Destination, RemoteError


class FakeDestination(Destination):
    label = "fake"

    def __init__(self):
        self.items = {}             # id -> {id, name, type, parent_id, file_size, data, deleted}
        self.calls = []             # ("upload", name) ... in order
        self.fail_names = set()     # uploads of these names raise RemoteError
        self.fail_after = None      # raise on every upload after this many more
        self._ids = itertools.count(1000)
        self._lock = threading.Lock()

    def _add(self, name, kind, parent_id, data=None):
        with self._lock:
            eid = next(self._ids)
            self.items[eid] = {"id": eid, "name": name, "type": kind, "parent_id": parent_id,
                               "file_size": len(data) if data is not None else 0, "data": data, "deleted": False}
            return eid

    def find_root(self, name):
        self.calls.append(("find_root", name))
        return next((e["id"] for e in self.items.values()
                     if e["type"] == "folder" and e["name"] == name and e["parent_id"] is None and not e["deleted"]),
                    None)

    def make_folder(self, name, parent_id):
        self.calls.append(("make_folder", name))
        return self._add(name, "folder", parent_id)

    def entries(self, folder_id):
        self.calls.append(("entries", folder_id))
        return [dict(e) for e in self.items.values() if e["parent_id"] == folder_id and not e["deleted"]]

    def upload(self, name, data, parent_id):
        with self._lock:
            if name in self.fail_names or self.fail_after == 0:
                raise RemoteError(f"fake failure uploading {name}")
            if self.fail_after is not None:
                self.fail_after -= 1
        self.calls.append(("upload", name))
        return self._add(name, "file", parent_id, data)

    def download(self, entry_id):
        return self.items[entry_id]["data"]

    def move(self, entry_id, folder_id):
        self.calls.append(("move", entry_id))
        self.items[entry_id]["parent_id"] = folder_id

    def trash(self, entry_id):
        self.calls.append(("trash", entry_id))
        self.items[entry_id]["deleted"] = True

    def delete(self, entry_id):
        self.calls.append(("delete", entry_id))
        doomed = [entry_id]
        while doomed:
            eid = doomed.pop()
            doomed += [e["id"] for e in self.items.values() if e["parent_id"] == eid]
            del self.items[eid]

    # ---- for the tests ----

    def live_files(self):
        """{remote/path: data} of every file not in the trash."""
        out = {}
        for e in self.items.values():
            if e["type"] == "file" and not e["deleted"] and not self._in_trash(e):
                out[self.path_of(e["id"])] = e["data"]
        return out

    def _in_trash(self, e):
        while e["parent_id"] is not None:
            e = self.items[e["parent_id"]]
            if e["deleted"]:
                return True
        return False

    def path_of(self, eid):
        parts, e = [], self.items[eid]
        while True:
            parts.append(e["name"])
            if e["parent_id"] is None:
                return "/".join(reversed(parts))
            e = self.items[e["parent_id"]]

    def uploads(self):
        return [n for op, n in self.calls if op == "upload"]
