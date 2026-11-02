"""The local database (SQLite): what is on the destination, per job, and
the history of runs.

The engine works on a plain dict per job (load() / save()):
    root_id      id of the job's top folder
    index_id     id of the current _index.txt
    manifest_id  id of the current _backup.json
    folders      relative folder -> id
    units        bundle key -> {id, sig, size, dir, name, zip, members, parts}
                 (parts: a file too big for one upload - id is then a folder of part001, part002 ...)
    files        relative path -> {size, mtime, sha1, usn, read} as of the last complete run
                 (usn: the file's change-journal number, read: when it was last read - see scan.py)
    versions     [{id, key, stamp, created, size, dir, zip, parts}] - replaced bundles in _versions
                 (dir/zip: None for versions made before they were kept)
"""
import json
import os
import sqlite3
import time

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, root_id INTEGER, index_id INTEGER, manifest_id INTEGER);
CREATE TABLE IF NOT EXISTS folders (job_id TEXT, rel TEXT, id INTEGER, PRIMARY KEY (job_id, rel));
CREATE TABLE IF NOT EXISTS units (job_id TEXT, key TEXT, id INTEGER, sig TEXT, size INTEGER,
                                  dir TEXT, name TEXT, zip INTEGER, members TEXT, parts INTEGER,
                                  PRIMARY KEY (job_id, key));
CREATE TABLE IF NOT EXISTS files (job_id TEXT, rel TEXT, size INTEGER, mtime INTEGER, sha1 TEXT,
                                  usn INTEGER, read REAL, PRIMARY KEY (job_id, rel));
CREATE TABLE IF NOT EXISTS versions (job_id TEXT, id INTEGER, key TEXT, stamp TEXT, created REAL, size INTEGER,
                                     dir TEXT, zip INTEGER, parts INTEGER, PRIMARY KEY (job_id, id));
CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, time REAL, full INTEGER,
                                   bundles INTEGER, files INTEGER, bad INTEGER, problems TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, started REAL, finished REAL,
                                 status TEXT, new INTEGER, changed INTEGER, deleted INTEGER, bundles INTEGER,
                                 sent INTEGER, report TEXT, error TEXT, changes TEXT);
"""
RUN_COLUMNS = "id, job_id, started, finished, status, new, changed, deleted, bundles, sent, report, error"


def empty():
    return {"root_id": None, "index_id": None, "manifest_id": None,
            "folders": {}, "units": {}, "files": {}, "versions": []}


class Store:
    def __init__(self, path=None):
        self.path = path or paths.DB_FILE
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version < 5:
            # 2: what each run found (lists of files), for the History page
            # 3: the folder and kind (zip or not) of each old version, for restoring from it
            # 4: files uploaded in parts (bigger than files.ir takes in one piece)
            # 5: each file's change-journal number and when it was read (changes the date hides)
            for table, column, kind in (("runs", "changes", "TEXT"), ("versions", "dir", "TEXT"),
                                        ("versions", "zip", "INTEGER"), ("units", "parts", "INTEGER"),
                                        ("versions", "parts", "INTEGER"), ("files", "usn", "INTEGER"),
                                        ("files", "read", "REAL")):
                if column not in [c[1] for c in self.db.execute(f"PRAGMA table_info({table})")]:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            self.db.execute("PRAGMA user_version = 5")
        self._saved_files = {}      # job id -> the files dict last written (rewritten only when replaced)

    def close(self):
        self.db.close()

    # ---- job state ----

    def load(self, job):
        row = self.db.execute("SELECT root_id, index_id, manifest_id FROM jobs WHERE job_id = ?", (job.id,)).fetchone()
        if row is None:
            return empty()
        q = lambda sql: self.db.execute(sql, (job.id,)).fetchall()  # noqa: E731
        state = empty()
        state["root_id"], state["index_id"], state["manifest_id"] = row
        state["folders"] = {rel: fid for rel, fid in q("SELECT rel, id FROM folders WHERE job_id = ?")}
        state["units"] = {
            key: {"id": i, "sig": sig, "size": size, "dir": d, "name": name, "zip": None if z is None else bool(z),
                  "members": json.loads(m) if m else None, "parts": bool(pt)}
            for key, i, sig, size, d, name, z, m, pt in
            q("SELECT key, id, sig, size, dir, name, zip, members, parts FROM units WHERE job_id = ?")}
        state["files"] = {rel: {"size": s, "mtime": mt, "sha1": h, "usn": u, "read": r}
                          for rel, s, mt, h, u, r in q("SELECT rel, size, mtime, sha1, usn, read FROM files WHERE job_id = ?")}
        state["versions"] = [{"id": i, "key": k, "stamp": st, "created": c, "size": s, "dir": d,
                              "zip": None if z is None else bool(z), "parts": bool(pt)}
                             for i, k, st, c, s, d, z, pt in
                             q("SELECT id, key, stamp, created, size, dir, zip, parts FROM versions "
                               "WHERE job_id = ? ORDER BY created")]
        self._saved_files[job.id] = state["files"]
        return state

    def save(self, job, state):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?)",
                            (job.id, state["root_id"], state["index_id"], state["manifest_id"]))
            for table in ("folders", "units", "versions"):
                self.db.execute(f"DELETE FROM {table} WHERE job_id = ?", (job.id,))
            self.db.executemany("INSERT INTO folders VALUES (?, ?, ?)",
                                [(job.id, rel, fid) for rel, fid in state["folders"].items()])
            self.db.executemany(
                "INSERT INTO units (job_id, key, id, sig, size, dir, name, zip, members, parts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                    (job.id, key, u["id"], u["sig"], u["size"], u.get("dir"), u.get("name"),
                     None if u.get("zip") is None else int(u["zip"]),
                     None if u.get("members") is None else json.dumps(u["members"], ensure_ascii=False),
                     int(bool(u.get("parts"))))
                    for key, u in state["units"].items()])
            self.db.executemany(
                "INSERT INTO versions (job_id, id, key, stamp, created, size, dir, zip, parts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                    (job.id, v["id"], v["key"], v["stamp"], v["created"], v["size"], v.get("dir"),
                     None if v.get("zip") is None else int(v["zip"]), int(bool(v.get("parts"))))
                    for v in state["versions"]])
            # the file list is big and only replaced at the end of a run
            if self._saved_files.get(job.id) is not state["files"]:
                self.db.execute("DELETE FROM files WHERE job_id = ?", (job.id,))
                self.db.executemany("INSERT INTO files (job_id, rel, size, mtime, sha1, usn, read) "
                                    "VALUES (?, ?, ?, ?, ?, ?, ?)", [
                    (job.id, rel, f["size"], f["mtime"], f["sha1"], f.get("usn"), f.get("read"))
                    for rel, f in state["files"].items()])
                self._saved_files[job.id] = state["files"]

    # ---- verify results ----

    def add_check(self, job, full, bundles, files, problems):
        with self.db:
            self.db.execute("INSERT INTO checks (job_id, time, full, bundles, files, bad, problems) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (job.id, time.time(), int(full), bundles, files, len(problems),
                             json.dumps(problems, ensure_ascii=False)))

    def last_check(self, job):
        cur = self.db.execute("SELECT time, full, bundles, files, bad, problems FROM checks WHERE job_id = ? "
                              "ORDER BY id DESC LIMIT 1", (job.id,))
        row = cur.fetchone()
        if not row:
            return None
        check = dict(zip([d[0] for d in cur.description], row))
        check["problems"] = json.loads(check["problems"] or "[]")
        return check

    # ---- history ----

    def start_run(self, job):
        with self.db:
            return self.db.execute("INSERT INTO runs (job_id, started, status) VALUES (?, ?, 'running')",
                                   (job.id, time.time())).lastrowid

    def finish_run(self, run_id, status, changes=None, **fields):
        """changes: {"new": [...], "changed": [...], "deleted": [...], "bundles": [...]} - kept for the History page."""
        if changes is not None:
            fields["changes"] = json.dumps(changes, ensure_ascii=False)
        cols = ["finished", "status"] + list(fields)
        with self.db:
            self.db.execute(f"UPDATE runs SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                            [time.time(), status] + list(fields.values()) + [run_id])

    def report_count(self, job):
        return self.db.execute("SELECT COUNT(*) FROM runs WHERE job_id = ? AND report IS NOT NULL",
                               (job.id,)).fetchone()[0]

    def runs(self, job, limit=20, before=None):
        """Newest first, without the file lists; before = a run id, for paging."""
        cur = self.db.execute(f"SELECT {RUN_COLUMNS} FROM runs WHERE job_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                              (job.id, before or 2 ** 62, limit))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def run(self, job, run_id):
        """One run with its file lists (changes: None for runs made before they were kept)."""
        cur = self.db.execute(f"SELECT {RUN_COLUMNS}, changes FROM runs WHERE job_id = ? AND id = ?", (job.id, run_id))
        row = cur.fetchone()
        if row is None:
            return None
        run = dict(zip([d[0] for d in cur.description], row))
        run["changes"] = json.loads(run["changes"]) if run["changes"] else None
        return run
