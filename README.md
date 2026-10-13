# Sideband

I want Sideband to help you find artists and songs from music you already enjoy. Pick a few artists or import your Spotify listening history. Sideband learns from plays and skips, explains each match, suggests unfamiliar genres, and checks its predictions against your history.

[Try the browser demo](https://gwilltsherman-byte.github.io/sideband/?demo=1) or follow the [Mac and iPhone guide](RUNNING.md) for live recommendations. You can start without an account or API key.

If you have already installed Sideband, start it from the repository folder:

```sh
.venv/bin/sideband serve
```

The app opens in your browser. First installation and troubleshooting are in [RUNNING.md](RUNNING.md). The demo uses simulated listening data; live recommendations use the music services listed below.

## On your phone

### Use GitHub Codespaces

Open [Sideband in Codespaces](https://codespaces.new/gwilltsherman-byte/sideband).
Create the codespace, wait for setup, then open port 8765 from the Ports panel.
The app starts automatically. Keep that port private and sign in to GitHub on
your iPhone to use the forwarded address. Your listening history stays in your
browser. The codespace must be running for live lookups.

### Hosting your own copy

Pages serves the browser app and its Python engine. Live lookups also need a
server because Deezer does not allow direct browser requests. The Pages workflow
builds and deploys the frontend. Set the repository Actions variable
`SIDEBAND_RELAY_URL` to the full lookup endpoint, for example
`https://your-server.example/api/proxy`, then rerun that workflow.

`server/serve.mjs` serves the whole app, or just the lookup endpoint with
`--relay-only`. The optional `render.yaml` describes a lookup service.
Hosting it there requires your own hosting account; free services can sleep
between visits. Set `FRONTEND_ORIGIN` to your Pages origin and optionally
`LASTFM_API_KEY` to add Last.fm data. The key stays on the server.

The [published browser demo](https://gwilltsherman-byte.github.io/sideband/?demo=1) uses simulated data. For live recommendations, run Sideband on your computer or in Codespaces. If you host a copy on Pages, connect a lookup server before using live recommendations.

### Open your computer's copy on your phone

sideband runs on a computer (Mac, Windows or Linux) and your phone opens it over your home Wi-Fi:

```
sideband serve --phone
```

It prints a private link such as `http://192.168.1.23:8765/?key=Ab3dE9fG`. Open that link in your phone's browser while the phone is on the same Wi-Fi as the computer. After the first visit the phone remembers the key, so you can bookmark the plain address or add it to your home screen. The computer has to stay on with sideband running.

* Anyone on your network who has the link can see your listening data, so don't share it.
* If the phone can't connect, allow Python through the computer's firewall. Windows usually asks the first time.
* To try it straight away, run `sideband serve --demo --phone`.
* **Android without a computer:** install [Termux](https://termux.dev), then run `pkg install python git`. Clone this repository, run `pip install -e .`, then `sideband serve --no-browser`, and open `http://127.0.0.1:8765` in Chrome.

## Prediction limits

Predictions depend on the available listening and similarity data. Mood, context and artists outside that data can affect what you enjoy. sideband checks its predictions in several ways:

1. It uses plays and skips to distinguish music you heard from music you enjoyed.
2. It fits its settings to **your** history.
3. It tests itself on data it has never seen: it hides your most recent months, predicts from everything before, and reports how many of the artists you actually went on to love it found. Results come with 95% confidence intervals and are compared against baselines.
4. It tracks your *Like* / *Not for me* ratings as a live hit rate, with an error bar.

## Getting started

**Right away:** name a few artists you love (Setup tab, or `sideband pick "Artist" "Another artist"`). sideband maps the music around them in a minute or two. Marking artists you can't stand helps too. On the simulated listener, eight picked artists already get within about 10% of what two years of listening history achieves (see [Validation](#validation-against-known-ground-truth)).

**Later, for sharper predictions:** add your Spotify history. You don't have to wait for it before using the app.

### Getting your data

1. Go to **Spotify → Account → [Privacy settings](https://www.spotify.com/account/privacy/)**.
2. Tick **Extended streaming history** and request it. This export lists every play since you joined, including how long you listened and whether you skipped. Spotify can take a few days, and up to 30, to send it.
   *Account data* is faster (about 5 days) and also works, but it only covers the last year and has no skip flags. You can import both.
3. Drop the `.zip` Spotify emails you into the app (Setup tab), or run `sideband import my_spotify_data.zip`.

The history adds what picks can't: skips, how your taste changes over time, and the accuracy test, which replays your history to measure how well sideband predicts *you*. Until then, your *Like* / *Not for me* ratings measure accuracy.

**Data sources:** Deezer, ListenBrainz and MusicBrainz, which need no keys. On a computer, if you have a free [Last.fm API key](https://www.last.fm/api/account/create), set the `LASTFM_API_KEY` environment variable (or run `sideband config --lastfm-key KEY`) to add Last.fm's similarity data too.

### Why not just log in with Spotify?
Spotify no longer gives new third-party apps its recommendation, related-artist or audio-feature endpoints ([Nov 2024](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api)). Since [February 2026](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide), development-mode apps also require a Premium owner and are capped at five users. Spotify's [Developer Policy](https://developer.spotify.com/policy) also forbids feeding data from its API into machine-learning models, which is what sideband's ranking is. Your data export is different: it's your own data, sent to you. It's also more informative: the API exposes your last 50 plays, while the export has your whole history *with skips*.

## How it works

| Step | What happens | Why |
|---|---|---|
| **1. Implicit feedback** (`taste.py`) | Each play is scored by the share of the song you heard, whether you chose it (clicked it or went back to it), and whether you skipped it in the first 30 s. The score fades with age (tunable half-life). Liked songs, follows and playlist adds add to it; hidden songs and artists count against. | Implicit-feedback recommender systems ([Hu, Koren & Volinsky 2008](http://yifanhu.net/PUB/cf.pdf)); 30 s is Spotify's own "stream" threshold, and early skips are the clearest dislike signal. |
| **2. Satisfaction** | For each artist, the probability that a play is not an early skip. It is estimated with a Beta prior fitted to your whole history (empirical Bayes). | An artist you heard twice shouldn't be judged as confidently as one you heard 200 times. |
| **3. Similarity graph** (`graph.py`) | Starting from your favourites (all-time, recent, and the artists you picked), sideband crawls similar-artist lists from ListenBrainz, Deezer and, if configured, Last.fm, and merges them into one weighted graph. Edges that several sources agree on count more. Genres come from MusicBrainz (looked up ten artists per request) or Last.fm. | Using several independent sources makes the similarity estimates more robust. |
| **4. Scoring** (`recommender.py`) | Every unfamiliar artist gets 8 interpretable features: item-based CF, recent-taste CF, Personalized PageRank ([Haveliwala 2002](https://doi.org/10.1145/511446.511513)), how many of your artists point to it, TF-IDF genre-profile cosine, popularity, similarity to artists you skip, and source agreement. A linear model combines them. | Every prediction can be explained. That's the bar under each artist in the app. |
| **5. Personal fit** (`evaluation.py`) | A time-based backtest picks the memory half-life, seed weighting and walk-restart probability on a *validation* window. It then re-fits the feature weights to you with logistic regression, using a prior centred on the defaults. | Different listeners behave differently. The prior keeps a small history from overfitting. |
| **6. Re-ranking** | Maximal Marginal Relevance ([Carbonell & Goldstein 1998](https://doi.org/10.1145/290941.291025)), so a list isn't ten copies of one band. The **adventurous** dial trades predicted accuracy for novelty: less famous artists, further from your genres, a longer random walk. | The backtest reports how many hits you give up at each dial setting. |
| **7. Exploration** (`explore.py`) | Each unfamiliar genre near your taste is a bandit arm with a Beta posterior over "will you like it?". Genres are ordered by Thompson sampling, and each one shows its *gateway artists*: the members closest to what you already love. Your ratings update the posteriors. | A principled explore/exploit trade-off ([Chapelle & Li 2011](https://papers.nips.cc/paper/4321-an-empirical-evaluation-of-thompson-sampling)). |
| **8. Songs** (`tracks.py`) | Three clearly separated lists: songs that go with your most-loved songs (Last.fm's track-to-track similarity, or Deezer's artist radio without it), the best-known song of each recommended artist, and popular songs by your favourite artists that you've never played. | |

### How accuracy is measured

```
|------------- train ------------|-- validation --|----- test -----|
                                t_val           t_test            now
```

* **Ground truth:** an artist you'd never played counts as *adopted* if you streamed them at least 3 times on at least 2 different days in the window. It counts as *rejected* if every play was skipped within 30 s.
* **Recall@K / Precision@K / NDCG@K:** of the artists you went on to adopt, how many were in the top K?
* **Mean percentile rank** ([Hu et al. 2008](http://yifanhu.net/PUB/cf.pdf)): where those artists landed in the full ranking. 0% is the top; 50% is what random guessing would score.
* **Preference AUC:** take one artist you heard and loved and one you heard and skipped. How often does sideband rank the loved one higher? Because you actually heard both, this is the cleanest test of "predicting what you'd like".
* Every metric is compared with three baselines: *most popular first*, *similar-artists only* and *random*. It is reported with bootstrap 95% intervals. Settings are chosen on the validation window only, and the test window is never used to choose anything.

### Validation against known ground truth

Real listening logs can't tell you what someone *would* have liked, so the test suite also includes a simulator (`synthetic.py`). It builds 8,000 artists in a latent style space, noisy and popularity-biased similarity lists like real collaborative-filtering data, and a listener whose taste drifts over time and who discovers music mainly through similarity-driven radio. That listener produces a realistic Extended Streaming History, skips included. On this simulated listener:

| | Recall@50 | Preference AUC |
|---|---|---|
| sideband | **77%** (95% CI 60-90%) | **0.94** (95% CI 0.87-1.00) |
| similar-artists only | 70% | 0.95 |
| most popular first | 0% | 0.28 |
| random | 11% | 0.50 |

The top 10 recommendations have an average *true* like-probability of 0.90. The best possible from the same candidates is 0.95, and a random unfamiliar artist scores 0.23. Across three differently seeded worlds and listeners, the top 30 average 0.86, against 0.18 for random. Changing the default weights moves that by about ±0.01, so the result doesn't depend on hand-tuning.

With no history at all, only the listener's eight favourite artists picked by name (mixing styles), the top 20 recommendations average 3.6× the like-probability of a random unfamiliar artist, against 3.9× from the full two-year history. The same holds without Last.fm (3.8× using only the free sources). The simulated similarity lists never cross genres, so these figures don't test how well picks alone suggest *new* genres; the history helps most there.

These numbers describe the simulation, not you. Run the accuracy test on your own data to get your numbers.

## Command line

```
sideband serve [--demo] [--phone] [--port 8765] [--no-browser]
sideband pick ARTIST... [--dislike | --remove]   # start without any export
sideband import PATH...                 # folder, .zip or .json from the Spotify export
sideband config --lastfm-key KEY [--no-listenbrainz]   # optional; or set LASTFM_API_KEY
sideband profile
sideband recommend [-n 30] [--explore 0.3]
sideband songs
sideband explore [--tag "bossa nova"]
sideband evaluate [--json]
```

Data is stored in the `~/.musicfinder/` folder (`musicfinder.db` with settings and ratings, `musicfinder-data.db` with your listening history, `musicfinder-cache.db` with cached lookups). To use a different folder, pass `--home DIR` or set `MUSICFINDER_HOME`.

## Privacy

Everything runs on your computer. Your picks and listening history stay in the local SQLite database and are never uploaded. The only things sent out are artist and song names, which go to Deezer, ListenBrainz, MusicBrainz and (if configured) Last.fm to look up similarity, genres and previews. Responses are cached locally for 30 days. The web server listens on 127.0.0.1 only, refuses requests whose Host header isn't local, and requires a custom header on any request that changes data. With `--phone` it also listens on your home network, and any device other than the computer must present the secret key from the printed link.

In the browser version, everything runs in your browser, and your picks and history are stored in that browser's storage on your device. Artist and song names pass through your site's relay function on their way to the music services; if you set `LASTFM_API_KEY`, the relay adds it there, so the key never leaves the lookup server. The relay stores nothing. It only forwards GET requests to those services' specific API addresses, and browsers won't let other websites' pages use it. (A program outside a browser could still use it for those same public addresses.)

## Development

```
pip install -e '.[dev]'
pytest                     # ~80 s; includes the simulated-listener validation and fake-API runs
npm install && npm run build && npm run test:js   # hosted build and its relay function
MUSICFINDER_E2E=1 pytest tests/test_site.py      # ~12 min: the hosted site in an emulated phone (Playwright)
```

The engine is pure Python standard library. numpy is used only if it's installed, and only to speed up building the demo world. The hosted build adds Pyodide (an npm dependency) and plain JavaScript; there is no front-end build step.

`tests/fake_upstream.py` imitates Last.fm, Deezer, MusicBrainz and ListenBrainz using the simulated world. Tests use it to exercise the real API clients, and to check that the browser's parallel prefetch plan covers every request (`tests/test_live_path.py`).

