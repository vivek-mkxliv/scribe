"""Minimal, stdlib-only local HTTP server for the browser GUI (`scribe gui`).

No third-party dependency (no Flask/FastAPI/etc.) -- just `http.server` + `webbrowser`, both in
the standard library, so the GUI adds zero new pip installs. Bound to `127.0.0.1` only: this is
a single-local-user control surface, never meant to be reachable over the network.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from scribe.gui.app import RunState, resolve_form_defaults, run_generation
from scribe.project.presets import PresetError, delete_preset, load_presets, save_preset

HOST = "127.0.0.1"


def _load_static_html() -> bytes:
    return resources.files("scribe.gui").joinpath("static/index.html").read_bytes()


class GuiRequestHandler(BaseHTTPRequestHandler):
    """Routes requests to `gui/app.py` functions; one `RunState` shared across all requests."""

    repo_path: Path
    run_state: RunState

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 -- matches base signature
        pass  # keep the terminal quiet; the browser's own log pane shows progress

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def _query(self) -> dict[str, str]:
        parsed = parse_qs(urlparse(self.path).query)
        return {k: v[0] for k, v in parsed.items()}

    def _path(self) -> str:
        return urlparse(self.path).path

    def do_GET(self) -> None:  # noqa: N802 -- required name by BaseHTTPRequestHandler
        path = self._path()
        if path == "/":
            body = _load_static_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/form-defaults":
            query = self._query()
            defaults = resolve_form_defaults(self.repo_path, query.get("preset") or None)
            self._send_json(defaults)
            return
        if path == "/api/presets":
            self._send_json({"presets": load_presets(self.repo_path)})
            return
        if path == "/api/status":
            self._send_json(self.run_state.snapshot())
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self._path()
        if path == "/api/generate":
            if self.run_state.running:
                self._send_json({"error": "A generation run is already in progress."}, status=409)
                return
            body = self._read_json_body()
            form = body.get("form", {})
            confirmed = bool(body.get("confirmed", False))
            self.run_state.mark_starting()
            thread = threading.Thread(
                target=run_generation,
                args=(self.repo_path, form, self.run_state),
                kwargs={"confirmed": confirmed},
                daemon=True,
            )
            thread.start()
            self._send_json({"started": True})
            return
        if path.startswith("/api/presets/"):
            name = path.removeprefix("/api/presets/")
            values = self._read_json_body()
            try:
                save_preset(self.repo_path, name, values)
            except PresetError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json({"saved": name})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_DELETE(self) -> None:  # noqa: N802
        path = self._path()
        if path.startswith("/api/presets/"):
            name = path.removeprefix("/api/presets/")
            existed = delete_preset(self.repo_path, name)
            self._send_json({"deleted": existed})
            return
        self._send_json({"error": "not found"}, status=404)


def build_server(repo_path: Path, port: int = 0) -> ThreadingHTTPServer:
    """Construct (but don't start) the server, bound to `127.0.0.1` on `port` (0 = OS-assigned)."""

    class _Handler(GuiRequestHandler):
        pass

    _Handler.repo_path = repo_path
    _Handler.run_state = RunState()
    return ThreadingHTTPServer((HOST, port), _Handler)


def run_gui(repo_path: Path, *, port: int = 0, open_browser: bool = True) -> None:
    """Start the GUI server and block until interrupted (Ctrl+C)."""
    server = build_server(repo_path, port=port)
    actual_port = server.server_address[1]
    url = f"http://{HOST}:{actual_port}/?repo={repo_path}"
    print(f"S.C.R.I.B.E. GUI running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
