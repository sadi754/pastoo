"""files.ir (my.files.ir) through its developer API."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .. import keystore
from .base import Destination, RemoteError

API = "https://my.files.ir/api/v1"


def load_key():
    key = keystore.files_ir_key()
    if not key:
        raise RemoteError("no files.ir key yet - add it on the Settings page")
    return key


class FilesIr(Destination):
    label = "files.ir"

    def __init__(self, key, on_retry=None):
        self.key = key
        self.on_retry = on_retry            # called with a message before each retry

    def call(self, method, path, body=None, multipart=None, raw=False):
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif multipart is not None:
            data, headers["Content-Type"] = multipart
        what = f"{method} {path.split('?')[0]}"
        for wait in (5, 15, 30, 60, None):
            req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    content = r.read()
                    if raw:
                        return r.status, content
                    return r.status, (json.loads(content) if content else None)
            except urllib.error.HTTPError as e:
                detail = e.read()[:300]
                if (e.code != 429 and e.code < 500) or wait is None:
                    raise RemoteError(f"{what}: HTTP {e.code} {detail!r}")
                problem = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if wait is None:
                    raise RemoteError(f"{what}: {e}")
                problem = str(e)
            if self.on_retry:
                self.on_retry(f"    {what}: {problem} - retrying in {wait}s")
            time.sleep(wait)

    def entries(self, folder_id):
        out, page = [], 1
        while True:
            _, j = self.call("GET", f"/drive/file-entries?perPage=100&page={page}&parentIds={folder_id}")
            out += [e for e in j["data"] if not e.get("deleted_at")]
            if not j.get("next_page"):
                return out
            page += 1

    def find_root(self, name):
        _, j = self.call("GET", "/drive/file-entries?type=folder&perPage=100&query=" + urllib.parse.quote(name))
        for e in j["data"]:
            if e["type"] == "folder" and e["name"] == name and not e.get("parent_id") and not e.get("deleted_at"):
                return int(e["id"])
        return None

    def make_folder(self, name, parent_id):
        _, j = self.call("POST", "/folders", {"name": name, "parentId": parent_id})
        return int(j["folder"]["id"])

    def upload(self, name, data, parent_id):
        b = uuid.uuid4().hex
        safe = name.replace('"', "_").encode("utf8")
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"parentId\"\r\n\r\n{parent_id}\r\n"
                f"--{b}\r\n").encode() + b'Content-Disposition: form-data; name="file"; filename="' + safe + \
            b'"\r\nContent-Type: application/octet-stream\r\n\r\n' + data + f"\r\n--{b}--\r\n".encode()
        _, j = self.call("POST", "/uploads", multipart=(body, f"multipart/form-data; boundary={b}"))
        entry = (j or {}).get("fileEntry") or {}
        if int(entry.get("file_size", -1)) != len(data):
            raise RemoteError(f"upload of {name}: files.ir reports {entry.get('file_size')} bytes, sent {len(data)}")
        return int(entry["id"])

    def download(self, entry_id):
        return self.call("GET", f"/file-entries/{entry_id}", raw=True)[1]

    def usage(self):
        _, j = self.call("GET", "/user/space-usage")
        return {"used": int(j["used"]), "total": int(j["available"])}

    def plan(self):
        """The account's limits: {name, space, files, file}. The plan is the active subscription's
        product, else the product whose space equals the account's, else the free one; limits set on
        the account itself win over the plan's."""
        _, me = self.call("GET", "/users/me")
        user = me["user"]
        _, j = self.call("GET", "/billing/products?perPage=100")
        products = j["pagination"]["data"]
        _, space = self.call("GET", "/user/space-usage")
        product = None
        for sub in user.get("subscriptions") or []:
            pid = sub.get("product_id") or (sub.get("price") or {}).get("product_id")
            product = next((p for p in products if p["id"] == pid), None)
            if product:
                break
        product = product or next((p for p in products if p.get("available_space") == space["available"]), None) \
            or next((p for p in products if p.get("free")), None)
        if product is None:
            raise RemoteError("files.ir did not list a plan for this account")
        limits = {"name": product.get("name") or f"plan {product['id']}", "space": int(product["available_space"]),
                  "files": int(product["max_file_count"]), "file": int(product["max_upload_size"])}
        for key, field in (("space", "available_space"), ("files", "max_file_count"), ("file", "max_upload_size")):
            if user.get(field):
                limits[key] = int(user[field])
        if space.get("available"):
            limits["space"] = int(space["available"])
        return limits

    def move(self, entry_id, folder_id):
        self.call("POST", "/file-entries/move", {"entryIds": [entry_id], "destinationId": folder_id})

    def trash(self, entry_id):
        # a JSON boolean - the string "true" the API docs show is refused (422)
        self.call("POST", "/file-entries/delete", {"entryIds": [entry_id], "deleteForever": False})

    def delete(self, entry_id):
        self.call("POST", "/file-entries/delete", {"entryIds": [entry_id], "deleteForever": True})
