"""The hosted (Netlify) build: the relay function's tests, and an opt-in end-to-end run in a browser."""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_relay_function():
    res = subprocess.run([NODE, "--test", "tests/js/proxy.test.mjs"], cwd=ROOT, capture_output=True, text=True,
                         timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.skipif(not os.environ.get("MUSICFINDER_E2E"), reason="set MUSICFINDER_E2E=1 (needs npm, Playwright; ~12 min)")
def test_hosted_site_end_to_end(tmp_path, world, history_rows):
    import json
    import zipfile

    from test_picks import favourites

    subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=ROOT, check=True)
    subprocess.run(["npm", "run", "build"], cwd=ROOT, check=True)
    export = tmp_path / "my_spotify_data.zip"
    with zipfile.ZipFile(export, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Spotify Extended Streaming History/Streaming_History_Audio_0.json", json.dumps(history_rows))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen([sys.executable, "tests/serve_site.py", "--port", str(port), "--latency", "0.05"],
                              cwd=ROOT, stdout=subprocess.PIPE, text=True)
    try:
        assert "serving" in server.stdout.readline()
        time.sleep(0.5)
        picks = json.dumps(favourites(world, history_rows, n=6))
        res = subprocess.run([NODE, "tests/e2e_site.mjs", f"http://127.0.0.1:{port}", str(export), str(tmp_path), picks],
                             cwd=ROOT, capture_output=True, text=True, timeout=2400)
        assert res.returncode == 0 and "ALL PASSED" in res.stdout, res.stdout[-3000:] + res.stderr[-3000:]
        small = tmp_path / "Streaming_History_Audio_small.json"
        small.write_text(json.dumps(history_rows[:2000]))
        res = subprocess.run([NODE, "tests/e2e_tabs.mjs", f"http://127.0.0.1:{port}", str(small)],
                             cwd=ROOT, capture_output=True, text=True, timeout=900)
        assert res.returncode == 0 and "ALL PASSED" in res.stdout, res.stdout[-3000:] + res.stderr[-3000:]
    finally:
        server.terminate()
