"""Local web server (standard library only) exposing the app as a JSON API plus a single-page UI.

Binds to 127.0.0.1 by default. Requests whose Host header is not local are refused (defeats DNS
rebinding), and every state-changing request must carry an ``X-MusicFinder`` header, which browsers
will not let other websites add without a CORS preflight this server never approves.

Phone mode (``serve --phone``) also listens on the home network. Devices other than this computer
must then present a secret key: the link printed at startup carries it once, after which it lives in
an HttpOnly cookie.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
import socket
import threading
from http.cookies import CookieError, SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from musicfinder.api import dispatch_steps, parse_query
from musicfinder.app import MusicFinder
from musicfinder.steps import run

MAX_UPLOAD = 1024 * 1024 * 1024  # 1 GiB
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
COOKIE = "mf_key"
FORBIDDEN_PAGE = (
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>musicfinder</title><body style='font:18px/1.5 sans-serif;padding:24px;max-width:36em'>"
    "<h1>musicfinder</h1><p>This copy of musicfinder is private. Open it with the full link that was "
    "printed when it started on your computer. That link includes <code>?key=</code>.</p>"
).encode("utf-8")


def _web_file(name: str) -> bytes | None:
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    try:
        return resources.files("musicfinder").joinpath("web", name).read_bytes()
    except (FileNotFoundError, OSError):
        return None


class Handler(BaseHTTPRequestHandler):
    app: MusicFinder
    server_version = "musicfinder"

    def log_message(self, fmt: str, *args: Any) -> None:  # keep the console quiet
        pass

    # ---- plumbing -------------------------------------------------------------------------------
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip().lower()
        return host in LOCAL_HOSTS

    def _key_from_url(self) -> str:
        return parse_qs(urlsplit(self.path).query).get("key", [""])[0]

    def _key_ok(self, candidate: str) -> bool:
        token = getattr(self.server, "token", None)
        return bool(token and candidate) and hmac.compare_digest(candidate.encode(), token.encode())

    def _authorized(self) -> bool:
        """Local browser (by Host header), or any device holding the phone-mode key."""
        if self._host_ok():
            return True
        try:
            morsel = SimpleCookie(self.headers.get("Cookie") or "").get(COOKIE)
        except CookieError:
            morsel = None
        return self._key_ok(morsel.value if morsel else "") or self._key_ok(self._key_from_url())

    def _deny(self) -> None:
        if urlsplit(self.path).path.startswith("/api/"):
            return self._error(HTTPStatus.FORBIDDEN, "Open musicfinder with the link shown when it started.")
        self._send(HTTPStatus.FORBIDDEN, FORBIDDEN_PAGE, "text/html; charset=utf-8")

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ValueError("Upload too large")
        return self.rfile.read(n) if n > 0 else b""

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._deny()
        url = urlsplit(self.path)
        path = url.path
        if path == "/" and self._key_ok(self._key_from_url()):
            # Remember the key in a cookie and drop it from the address bar / history.
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{COOKIE}={self.server.token}; Path=/; HttpOnly; SameSite=Strict; "
                                           "Max-Age=31536000")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in ("/", "/index.html"):
            body = _web_file("index.html")
            return self._send(200, body or b"missing UI", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            body = _web_file(name)
            if body is None:
                return self._error(404, "Not found")
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            return self._send(200, body, ctype)
        status, payload = run(dispatch_steps(self.app, "GET", path, parse_query(url.query)))
        return self._json(payload, status)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._deny()
        if self.headers.get("X-MusicFinder") != "1":
            return self._error(HTTPStatus.FORBIDDEN, "Missing X-MusicFinder header")
        url = urlsplit(self.path)
        try:
            body = self._body()
        except ValueError as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e))
        name = unquote(self.headers.get("X-Filename") or "upload.json")
        status, payload = run(dispatch_steps(self.app, "POST", url.path, parse_query(url.query), body, name))
        return self._json(payload, status)


def lan_address() -> str | None:
    """This computer's address on the home network (no packets are sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        ip = sock.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        sock.close()


def phone_key(app: MusicFinder) -> str:
    """A persistent secret, so a phone that opened the link once stays signed in across restarts."""
    key = app.store.get_setting("phone_key")
    if not key:
        key = secrets.token_urlsafe(6)
        app.store.set_setting("phone_key", key)
    return key


def make_server(app: MusicFinder, host: str = "127.0.0.1", port: int = 8765,
                token: str | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.token = token  # type: ignore[attr-defined]
    return server


def serve(app: MusicFinder, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    on_network = host not in ("127.0.0.1", "localhost", "::1")
    token = phone_key(app) if on_network else None
    server = make_server(app, host, port, token)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"musicfinder is running at {url}  (Ctrl+C to stop)")
    if on_network:
        ip = lan_address() if host in ("0.0.0.0", "") else host
        if ip:
            print("\nOn your phone (connected to the same Wi-Fi as this computer), open:\n")
            print(f"    http://{ip}:{port}/?key={token}\n")
            print("Keep that link private: anyone on your network who has it can see your listening data.")
            print("If the phone can't connect, allow Python through this computer's firewall.")
        else:
            print("Couldn't work out this computer's network address. On your phone, open "
                  f"http://<this computer's IP>:{port}/?key={token}")
    if open_browser:
        try:
            import webbrowser

            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
