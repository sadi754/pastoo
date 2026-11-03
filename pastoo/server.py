"""Local web server: serves the UI and streams the backup's progress over a WebSocket.

Like NetMon's: it listens on 127.0.0.1 only, and every request must carry a
random token made at startup, so web pages in your browser can't use it.

Window -> app:  {"type": "backup" | "check" | "preview", "job": id}, {"type": "stop"}
                {"type": "history", "job": id, "before": run id?}, {"type": "run_detail", "job": id, "id": run id}
App -> window:  {"type": "hello", "version", "jobs": [status], "run": run | null}
                {"type": "job", "job": status}
                {"type": "run", "run": run (without its lines), "line": str}
                {"type": "preview", "job": id, ...runner.changes()}       only to the window that asked,
                {"type": "history", "job": id, "runs": [...], "append", "more"}  like the next two
                {"type": "run_detail", "job": id, "run": run with "changes" or "report_text"}
                {"type": "browse", "job": id, ...service.browse()}
                {"type": "version_files", "job": id, "id": version id, "files": [[path, size, mtime]]}
                {"type": "task", "task": restore/verify info (without its lines), "line": str}
                {"type": "error", "message": str}
Window -> app, Restore page:
                {"type": "browse", "job": id}, {"type": "version_files", "job": id, "id": version id}
                {"type": "restore", "job": id, "source": "latest" | version id, "files": [path],
                 "to": folder ("" = the job's own folder), "overwrite": bool}
                {"type": "verify", "job": id, "sample": n (omitted = every bundle)}
Window -> app, Settings page (see _handle_settings):
                {"type": "settings"}, {"type": "measure", "job": form, "ref"}, {"type": "save_job", "job": form},
                {"type": "remove_job", "id"}, {"type": "save_app", "app": {...}}, {"type": "set_key", "key"},
                {"type": "test_key"}
"""
import asyncio
import contextlib
import json
import logging
import secrets
import socket
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import VERSION, i18n, jobs as jobs_mod, paths, settings as settings_mod

log = logging.getLogger(__name__)


class _RevalidatingStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"     # an updated UI shows up without clearing caches
        return response


def _ignore_dropped_connections(loop, context):
    # A closing window drops its connection abruptly ("WinError 10054") - normal here
    if isinstance(context.get("exception"), (ConnectionResetError, ConnectionAbortedError)):
        return
    loop.default_exception_handler(context)


class WebServer:
    def __init__(self, service, on_show):
        self.service = service
        self.on_show = on_show
        self.token = secrets.token_urlsafe(24)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))      # 0 = let Windows pick a free port
        self.port = self._sock.getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self._clients = {}                      # open windows -> their outbox
        self._loop = None
        app = Starlette(routes=[
            WebSocketRoute("/ws", self._websocket),
            Route("/api/show", self._show, methods=["POST"]),
            Mount("/", _RevalidatingStaticFiles(directory=paths.WEB_DIR, html=True)),
        ], lifespan=self._lifespan)
        config = uvicorn.Config(app, log_config=None, log_level="warning", access_log=False,
                                timeout_graceful_shutdown=2)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._run, name="web", daemon=True)
        service.listeners.append(self._on_service)

    @property
    def url(self):
        return f"{self.origin}/?token={self.token}"

    def start(self, timeout=10.0):
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("The local web server failed to start - see app.log")
            time.sleep(0.02)

    def stop(self):
        if self._loop and self._clients:
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(self._close_clients(), self._loop).result(timeout=3)
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def _run(self):
        try:
            self._server.run(sockets=[self._sock])
        except Exception:
            if not self._server.should_exit:
                raise

    async def _close_clients(self):
        for ws in list(self._clients):
            with contextlib.suppress(Exception):
                await ws.close(code=1001)
        for _ in range(40):
            if not self._clients:
                return
            await asyncio.sleep(0.05)

    @contextlib.asynccontextmanager
    async def _lifespan(self, app):
        self._loop = asyncio.get_running_loop()
        self._loop.set_exception_handler(_ignore_dropped_connections)
        yield

    def _authorized(self, conn):
        return secrets.compare_digest(conn.query_params.get("token", ""), self.token)

    async def _show(self, request: Request):
        if not self._authorized(request):
            return Response(status_code=403)
        await asyncio.to_thread(self.on_show)
        return Response(status_code=204)

    async def _websocket(self, ws: WebSocket):
        # A browser always sends the page's origin; a foreign website would show its own
        if not self._authorized(ws) or ws.headers.get("origin") != self.origin:
            await ws.close(code=1008)
            return
        await ws.accept()
        queue = asyncio.Queue(maxsize=200)
        self._clients[ws] = queue
        pump = None
        try:
            hello = await asyncio.to_thread(self._hello)
            await ws.send_text(json.dumps(hello))
            pump = asyncio.create_task(self._pump(ws, queue))
            while True:
                try:
                    message = json.loads(await ws.receive_text())
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                try:
                    await self._handle(queue, message)
                except Exception as e:      # one bad message must not drop the window's connection
                    log.exception("Handling %r failed", message.get("type"))
                    self._send(queue, {"type": "error", "message": f"Something went wrong: {e}"})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self._clients.pop(ws, None)
            if pump:
                pump.cancel()

    @staticmethod
    async def _pump(ws, queue):
        with contextlib.suppress(Exception):
            while True:
                await ws.send_text(await queue.get())

    async def _handle(self, queue, message):
        kind, job_id = message.get("type"), message.get("job")
        if kind in self._SETTINGS:
            await self._handle_settings(queue, kind, message)
            return
        if kind != "stop" and (not isinstance(job_id, str) or job_id not in {j.id for j in jobs_mod.JOBS}):
            return
        if kind == "fold":              # a dashboard card folded / opened - remembered in settings.json
            await asyncio.to_thread(self.service.save_fold, job_id, bool(message.get("folded")))
        elif kind == "backup":
            if not self.service.start(job_id):
                self._send(queue, {"type": "error", "message": "A backup is already running."})
        elif kind == "check":
            self.service.check(job_id)
        elif kind == "stop":
            self.service.stop()
        elif kind == "preview":         # the answers below go only to the window that asked
            try:
                data = await asyncio.to_thread(self.service.preview, job_id)
                self._send(queue, {"type": "preview", "job": job_id, **data})
            except Exception as e:
                log.exception("Preview failed")
                self._send(queue, {"type": "error", "message": f"Could not look for changes: {e}"})
        elif kind == "history":
            before = message.get("before")
            runs = await asyncio.to_thread(self.service.history, job_id,
                                           before if isinstance(before, int) else None, 50)
            self._send(queue, {"type": "history", "job": job_id, "runs": runs, "append": bool(before),
                               "more": len(runs) == 50})
        elif kind == "run_detail" and isinstance(message.get("id"), int):
            run = await asyncio.to_thread(self.service.run_detail, job_id, message["id"])
            if run:
                self._send(queue, {"type": "run_detail", "job": job_id, "run": run})
        elif kind == "browse":
            data = await asyncio.to_thread(self.service.browse, job_id)
            self._send(queue, {"type": "browse", "job": job_id, **data})
        elif kind == "version_files" and isinstance(message.get("id"), int):
            try:
                files = await asyncio.to_thread(self.service.version_files, job_id, message["id"])
                self._send(queue, {"type": "version_files", "job": job_id, "id": message["id"], "files": files})
            except Exception as e:
                log.exception("Opening an old version failed")
                self._send(queue, {"type": "error", "message": f"Could not open that old version: {e}"})
        elif kind == "restore":
            source, rels, to = message.get("source"), message.get("files"), message.get("to")
            if (source == "latest" or isinstance(source, int)) and isinstance(rels, list) and rels \
                    and all(isinstance(r, str) for r in rels) and isinstance(to, str):
                why = self.service.start_restore(job_id, source, rels, to.strip(), bool(message.get("overwrite")))
                if why:
                    self._send(queue, {"type": "error", "message": why})
        elif kind == "verify":
            sample = message.get("sample")
            why = self.service.start_verify(job_id, sample if isinstance(sample, int) and sample > 0 else None)
            if why:
                self._send(queue, {"type": "error", "message": why})

    _SETTINGS = ("settings", "measure", "save_job", "remove_job", "save_app", "set_key", "test_key", "usage")

    async def _handle_settings(self, queue, kind, message):
        """The Settings page. Changes answer with {"type": "saved", "what"} or an error, then
        everyone gets a fresh "settings" (and a "hello" when the jobs changed)."""
        form = message.get("job") if isinstance(message.get("job"), dict) else {}
        try:
            if kind == "measure":
                result = await asyncio.to_thread(self.service.measure, form)
                self._send(queue, {"type": "measure", "ref": message.get("ref"), **result})
                return
            if kind == "usage":
                await asyncio.to_thread(self.service.refresh_usage)     # answers everyone with "usage"
                return
            if kind == "test_key":
                problem = await asyncio.to_thread(self.service.test_key)
                self._send(queue, {"type": "key_test", "ok": problem is None, "message": problem or ""})
                return
            if kind == "save_job":
                saved = await asyncio.to_thread(self.service.save_job, form)
                self._send(queue, {"type": "saved", "what": "job", "job": saved})
            elif kind == "remove_job" and isinstance(message.get("id"), str):
                await asyncio.to_thread(self.service.remove_job, message["id"])
                self._send(queue, {"type": "saved", "what": "removed"})
            elif kind == "save_app" and isinstance(message.get("app"), dict):
                await asyncio.to_thread(self.service.save_app, message["app"])
                self._send(queue, {"type": "saved", "what": "app"})
            elif kind == "set_key" and isinstance(message.get("key"), str):
                await asyncio.to_thread(self.service.set_key, message["key"])
                self._send(queue, {"type": "saved", "what": "key"})
        except (ValueError, OSError) as e:
            self._send(queue, {"type": "error", "message": str(e), "where": kind, "ref": message.get("ref")})
            return
        view = await asyncio.to_thread(self.service.settings_view)
        self._broadcast(json.dumps({"type": "settings", **view}))
        if kind in ("save_job", "remove_job"):
            self._broadcast(json.dumps(await asyncio.to_thread(self._hello)))

    def _hello(self):
        data = settings_mod.load()
        return {"type": "hello", "version": VERSION, "jobs": self.service.statuses(), "run": self.service.run,
                "task": self.service.task, "reminder_days": data["reminder_days"], "folded": data.get("folded", {}),
                "usage": self.service.last_usage, "lang": i18n.language(data)}

    # ---- from the service's threads

    def _on_service(self, message):
        if message["type"] in ("run", "task"):
            kind = message["type"]
            message = {"type": kind, "line": message["line"],
                       kind: {k: v for k, v in message[kind].items() if k != "lines"}}
        text = json.dumps(message)
        if self._loop and self._clients:
            with contextlib.suppress(RuntimeError):     # the loop is closed when exiting
                self._loop.call_soon_threadsafe(self._broadcast, text)

    # ---- on the server's event loop

    def _broadcast(self, text):
        for queue in self._clients.values():
            self._send(queue, text)

    @staticmethod
    def _send(queue, message):
        if queue.full():        # a slow window drops its oldest message rather than piling up
            queue.get_nowait()
        queue.put_nowait(message if isinstance(message, str) else json.dumps(message))
