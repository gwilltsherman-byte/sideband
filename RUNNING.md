# Run musicfinder on Mac and iPhone

## Mac

Install Python 3.10 or later. Apple's bundled Python may be older, so check
`python3 --version` first. Use the installed Python 3.10+ executable below.

```sh
git clone https://github.com/gwilltsherman-byte/music.git
cd music
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/musicfinder serve
```

Open `http://127.0.0.1:8765` if the browser does not open automatically.
Keep Terminal open. Control-C stops the server. Next time, return to the
repository folder and run `.venv/bin/musicfinder serve`.

In Setup, pick artists you like and choose Find my music. A Spotify export is
optional. To try a simulated listener without network lookups:

```sh
.venv/bin/musicfinder serve --demo
```

## iPhone over your home Wi-Fi

Stop the Mac server, then run:

```sh
.venv/bin/musicfinder serve --phone
```

Keep the Mac awake and connect your iPhone to the same Wi-Fi. Open the full
phone link printed in Terminal in Safari, including its `?key=` value. That
key gives access to your listening data, so keep the link private. The phone
remembers it after the first visit.

You can bookmark the link or choose Share, Add to Home Screen. This copy
still runs on the Mac; the icon does not make it independent of the Mac.
Allow Python through the Mac's firewall if the phone cannot connect.

## GitHub hosting

The source is on GitHub, but GitHub Pages cannot run the Python web server
or the lookup relay. The browser build runs Python through Pyodide, but its
live music lookups currently depend on `/api/proxy`, served by a host-specific
relay function. Publishing
those files to Pages alone leaves that relay missing.

Use the Mac server and phone mode for the current app. A standalone Pages
version needs a replacement lookup service or compatible data sources before
its live recommendations will work. The offline demo can test the engine,
but it is not a replacement for live lookups.

The default branch is `main`. If you cloned the old branch before it was
renamed, update your local checkout:

```sh
git branch -m main
git fetch origin
git branch -u origin/main main
git remote set-head origin -a
```
