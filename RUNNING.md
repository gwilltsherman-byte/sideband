# Using Sideband

[Open Sideband](https://sideband.netlify.app) in Safari. Sideband works with
cellular data or any internet connection; no home Wi-Fi, running Mac or Terminal
is needed.

## Install the hosted app

1. Open [sideband.netlify.app](https://sideband.netlify.app) in Safari.
2. **iPhone:** tap **Share > Add to Home Screen**, then **Add**.
   If **Open as Web App** appears, leave it on.
3. **Mac with macOS Sonoma 14 or later:** choose **File > Add to Dock**, then **Add**.
4. Open the new Sideband icon before picking favourites or importing history.

The installed app keeps its own data, which stays saved after you close it.
Once the first download finishes, saved data can open offline; new music
lookups need an internet connection.

## Save a backup or move to another device

In **Setup > Backup and restore**, save a backup before changing devices or
clearing app data. Restore that file in the installed app on the other device.
The backup contains your picks, ratings, listening history and music map, but
not credentials. Each device keeps its own data; it does not sync automatically.

## Get your first recommendations

In Setup, tap artists you love, then **Find my music**. Tap a style to narrow
the choices or **Show more** for another set. Taps save immediately; tap a
selected artist again to remove it. There is no typing or export to wait for.
A few artists from different parts of your taste help, and you can start with one.

Your existing picks and ratings are kept, and duplicate uploads do not count
twice. The input is saved locally as your declared favourites, not invented
listening history. The artist picker works even when the music lookup service
is disconnected; finding new recommendations still needs that service.

If you already have a list or playlist file, the additional input section lets
you paste artists, paste `Artist — Song` lines, or choose a CSV, TSV or TXT file.
Review the preview and choose **Use this taste** to save those names.

If you already have a Spotify export, add its ZIP or JSON files in the optional
history section. **Improve from my history** then updates your map and checks
personal settings using real listening dates and outcomes.

You can also pick artists you like and choose **Find my music** before an export
arrives. On For You, start with ten artists, listen, rate them, then choose
**Apply ratings to my list**. You can undo a rating and choose 20 or 30 artists
at a time; Sideband remembers your list size and adventurous setting.

## Optional local development on Mac

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

To try a simulated listener without network lookups:

```sh
.venv/bin/sideband serve --demo
```

## Optional testing over home Wi-Fi

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

## Optional development in GitHub Codespaces

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

If the lookup service is absent or temporarily unavailable, Sideband still
opens for local imports, your taste profile and a previously saved music map.
It shows a connection notice and disables new lookups. Reload after the service
returns; your history is preserved.


## Permanent hosting with Netlify

This repository includes `netlify.toml`. Connect it to Netlify and use its build
configuration. The published `site` folder and `/api/proxy` function run together.
Listening data stays on each user's device; the function only looks up public
music information. If you keep the frontend on GitHub Pages, set the Netlify
`FRONTEND_ORIGIN` environment variable to your Pages origin, then set
`SIDEBAND_RELAY_URL` in the Pages workflow to the Netlify `/api/proxy` URL.
