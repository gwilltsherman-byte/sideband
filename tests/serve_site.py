"""Serve ./site the way Netlify does, with /api/proxy answered by the fake music services.

    python tests/serve_site.py --port 8888 [--latency 0.08] [--lastfm-key KEY]

Like the real relay, it adds the site's Last.fm key (``--lastfm-key``), tells the page whether it
has one (``/api/proxy?config=1``), and refuses Last.fm requests when there is none.

Used by the browser end-to-end test; also handy for trying the hosted build locally without network.
"""

from __future__ import annotations

import argparse
import mimetypes
import random
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_upstream import FakeUpstream  # noqa: E402
from musicfinder.synthetic import make_world  # noqa: E402

mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/manifest+json", ".webmanifest")

ALLOWED_HOSTS = {"ws.audioscrobbler.com", "api.deezer.com", "musicbrainz.org", "labs.api.listenbrainz.org"}


class Handler(SimpleHTTPRequestHandler):
    fake: FakeUpstream
    latency: float = 0.0
    lastfm_key = ""
    proxied = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/api/proxy":
            if parse_qs(parts.query).get("config") == ["1"]:
                return self._reply(200, b'{"lastfm": true}' if self.lastfm_key else b'{"lastfm": false}')
            url = parse_qs(parts.query).get("url", [""])[0]
            host = urlsplit(url).hostname
            if host not in ALLOWED_HOSTS or not url.startswith("https://"):
                return self._reply(400, b'{"relay_error": "not allowed"}', relay_error=True)
            if host == "ws.audioscrobbler.com":
                if not self.lastfm_key:
                    return self._reply(503, b'{"relay_error": "Last.fm is not set up on this site"}', relay_error=True)
                p = urlsplit(url)
                q = {k: v[0] for k, v in parse_qs(p.query).items()}
                q["api_key"] = self.lastfm_key
                url = urlunsplit(p._replace(query=urlencode(q)))
            if self.latency:
                time.sleep(self.latency * random.uniform(0.5, 1.5))
            type(self).proxied += 1
            status, body = self.fake(url)
            return self._reply(status, body)
        return super().do_GET()

    def _reply(self, status: int, body: bytes, relay_error: bool = False):
        self.send_response(status)
        if relay_error:
            self.send_header("X-Relay-Error", "1")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--latency", type=float, default=0.0, help="simulated relay round-trip in seconds")
    ap.add_argument("--artists", type=int, default=8000)
    ap.add_argument("--lastfm-key", default="", help="the site's Last.fm key (the fake Last.fm accepts KEY)")
    args = ap.parse_args()
    Handler.fake = FakeUpstream(make_world(n_artists=args.artists))
    Handler.latency = args.latency
    Handler.lastfm_key = args.lastfm_key
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(ROOT / "site")))
    print(f"serving site on http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
