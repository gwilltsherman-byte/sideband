# Using Sideband

Sideband's simplest setup is a permanently hosted web app. Open its public
address in Safari and install it once. It can use cellular data or any internet
connection; no home Wi-Fi, running Mac or Terminal is needed.

The [current browser demo](https://gwilltsherman-byte.github.io/sideband/?demo=1)
uses simulated listening data. Full live music lookup is prepared for Netlify,
but is not deployed yet.

## Install the hosted app

Open the hosted app in Safari. On iPhone choose **Share > Add to Home Screen**.
On a Mac with Safari web apps, choose **File > Add to Dock**. Open that new icon
before importing your listening history. The installed app keeps its own data,
which stays saved after you close it. Once the first download finishes, saved
data can open offline; new music lookups need an internet connection.

In **Setup > Backup and restore**, save a backup before changing devices or
clearing app data. Restore that file in the installed app on the other device.
The backup contains your picks, ratings, listening history and music map, but
not credentials. Demo mode uses simulated data and does not save personal data.

The published GitHub Pages address currently provides a demo. Live hosted
lookups need the Netlify configuration described below; a running Mac or
codespace is not required by that hosted setup.

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

In Setup, start without waiting for Spotify: paste favourite artists (one per
line), switch to favourite songs (`Artist — Song`), or choose a playlist CSV/TSV
with named artist and track columns. Review the preview, choose **Use this
taste**, then **Find my music**. Plain TXT files work too. A list of links alone
does not contain the music names needed by Sideband.

Your existing picks and ratings are kept, and duplicate uploads do not count
twice. The input is saved locally as your declared favourites, not invented
listening history. Artist/song entry works even when the music lookup service
is disconnected; finding new recommendations still needs that service.

If you already have a Spotify export, add its ZIP or JSON files in the optional
history section. **Improve from my history** then updates your map and checks
personal settings using real listening dates and outcomes.

You can also pick artists you like and choose **Find my music** before an export
arrives. On For You, start with ten artists, listen, rate them, then choose
**Apply ratings to my list**. You can undo a rating and choose 20 or 30 artists
at a time; Sideband remembers your list size and adventurous setting.

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
