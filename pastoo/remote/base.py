"""A backup destination is anything with these operations, by entry id.
Tree adds what the engine needs on top: folders by relative path (made on
demand, remembered in the job state) and finding bundles already there."""


class RemoteError(Exception):
    pass


class Destination:
    label = "destination"

    def find_root(self, name):
        """id of the top-level folder `name` (not in the trash), or None."""
        raise NotImplementedError

    def make_folder(self, name, parent_id):
        """id of a new folder; parent_id None = top level."""
        raise NotImplementedError

    def entries(self, folder_id):
        """Everything directly inside a folder, not in the trash:
        dicts with at least id, name, type ("folder" or a file type), file_size."""
        raise NotImplementedError

    def upload(self, name, data, parent_id):
        """id of the new file."""
        raise NotImplementedError

    def download(self, entry_id):
        raise NotImplementedError

    def move(self, entry_id, folder_id):
        """Same entry (same id) into another folder."""
        raise NotImplementedError

    def trash(self, entry_id):
        raise NotImplementedError

    def usage(self):
        """{"used": bytes, "total": bytes} of the whole account, or None if the destination can't tell."""
        return None

    def plan(self):
        """The account's limits {name, space, files, file}, or None if the destination can't tell."""
        return None

    def delete(self, entry_id):
        """Gone for good, not into the trash."""
        raise NotImplementedError


class Tree:
    """Folder ids by relative path, made on demand. Folders that already
    existed are listed once so bundles already in them can be taken over."""

    def __init__(self, dest, state, root_name, on_made_root=None):
        self.dest, self.state, self.root_name = dest, state, root_name
        self.on_made_root = on_made_root
        self.fresh = set()       # folder ids made in this run - known to be empty
        self.listing = {}        # folder id -> its entries

    def children(self, folder_id):
        if folder_id in self.fresh:
            return []
        if folder_id not in self.listing:
            self.listing[folder_id] = self.dest.entries(folder_id)
        return self.listing[folder_id]

    def root(self):
        if not self.state["root_id"]:
            rid = self.dest.find_root(self.root_name)
            if rid is None:
                rid = self.dest.make_folder(self.root_name, None)
                self.fresh.add(rid)
                if self.on_made_root:
                    self.on_made_root()
            self.state["root_id"] = rid
        return self.state["root_id"]

    def folder(self, rel_dir):
        if not rel_dir:
            return self.root()
        fid = self.state["folders"].get(rel_dir)
        if fid:
            return fid
        parent_rel, _, name = rel_dir.rpartition("/")
        pid = self.folder(parent_rel)
        fid = next((int(e["id"]) for e in self.children(pid) if e["type"] == "folder" and e["name"] == name), None)
        if fid is None:
            fid = self.dest.make_folder(name, pid)
            self.fresh.add(fid)
        self.state["folders"][rel_dir] = fid
        return fid

    def existing(self, folder_id, name, size):
        return next((int(e["id"]) for e in self.children(folder_id)
                     if e["type"] != "folder" and e["name"] == name and int(e.get("file_size", -1)) == size), None)
