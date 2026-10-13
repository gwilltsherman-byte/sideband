# Using Sideband

[Try the browser demo](https://gwilltsherman-byte.github.io/sideband/?demo=1)
on your phone or computer. It uses simulated listening data. For live music
recommendations, run Sideband on your Mac or in GitHub Codespaces.

## First installation on Mac

Install Python 3.10 or later. Apple's bundled Python may be older, so check
`python3 --version` first. Use the installed Python 3.10+ executable below.

```sh
git clone https://github.com/gwilltsherman-byte/sideband.git
cd sideband
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/sideband serve
```

If you already downloaded the repository, skip the clone and enter that folder.
Updating pip first avoids older versions that cannot install this project.

Open `http://127.0.0.1:8765` if the browser does not open automatically.
Keep Terminal open. Control-C stops the server. Next time, return to the
repository folder and run `.venv/bin/sideband serve`.

In Setup, pick artists you like and choose Find my music. A Spotify export is
optional. To try a simulated listener without network lookups:

```sh
.venv/bin/sideband serve --demo
```

## iPhone over your home Wi-Fi

Stop the Mac server, then run:

```sh
.venv/bin/sideband serve --phone
```

Keep the Mac awake and connect your iPhone to the same Wi-Fi. Open the full
phone link printed in Terminal in Safari, including its `?key=` value. That
key gives access to your listening data, so keep the link private. The phone
remembers it after the first visit.

You can bookmark the link or choose Share, Add to Home Screen. This copy
still runs on the Mac; the icon does not make it independent of the Mac.
Allow Python through the Mac's firewall if the phone cannot connect.

## Run in GitHub Codespaces

Open https://codespaces.new/gwilltsherman-byte/sideband, create a codespace, and
wait for setup. Open the forwarded port 8765. The app and music lookup service
start together; sign in with the same GitHub account on iPhone to open that link.
Keep the port private. The app is available while the codespace runs.

## Host your own copy

In your fork, use the Publish Sideband on Pages workflow. The browser
engine works on Pages, but live lookups require the accompanying lookup server.
Set `SIDEBAND_RELAY_URL` in your fork's Settings, Secrets and variables, Actions,
Variables to the server's `/api/proxy` URL, then rerun the Pages workflow.

The optional Render blueprint serves only public music lookups. It does not
store your listening history. A hosting account is required to deploy it.
Use `?demo=1` for the Pages demo until that service is connected.

