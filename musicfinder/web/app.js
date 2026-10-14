// Sideband single-page UI. Plain ES module, no build step.
import { explorationChoice, batchChoice, nextRecommendationAction, latestRequest, quickReviewCurrent, quickInputKind } from "./ui-state.js";
import { ARTIST_STYLES, artistChoices, artistIdentity } from "./artist-picker.js";
import { previewObservation, feedbackIdentity, feedbackIO } from "./listening-signals.js";

const $ = (sel, root = document) => root.querySelector(sel);
const main = $("#main");
// The hosted  build runs the engine inside the browser instead of talking to a local server.
const BROWSER = window.MUSICFINDER_MODE === "browser";
const engine = BROWSER ? await import("./browser-api.js") : null;
window.addEventListener("sideband-status", event => toast(event.detail, 12000));
const WHERE = BROWSER ? "in this browser on this device" : "on this computer";
// iPhone/iPad: a Home Screen web app keeps its own storage, separate from Safari's.
const IOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const STANDALONE = (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
const player = $("#player");
let state = null;
let importing = false;
let quickSaving = false;
// Serialize explicit picks so fast taps cannot overwrite a later choice.
let pickQueue = Promise.resolve();
let pickSaving = 0;
let savedPicks = null;
let pickIntents = [];
let pickIntentSeq = 0;

const FEATURE_NAMES = {
  cf: "Similar to artists you play a lot",
  cf_recent: "Similar to what you play lately",
  ppr: "Central to your taste network",
  support: "Linked from many of your artists",
  tag: "Matches your genre profile",
  pop: "Popularity",
  neg: "Similar to music you dislike or skip",
  agree: "Sources agree",
};

// ---------------------------------------------------------------- utilities
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const enc = encodeURIComponent;
const pct = (x, digits = 0) => (x == null ? "n/a" : `${(x * 100).toFixed(digits)}%`);
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
const compact = (n) => (n == null ? "—" : Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n));
const listJoin = (items) => (items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`);
const spotifyUrl = (artist, title = "") => `https://open.spotify.com/search/${enc((title ? `${title} ` : "") + artist)}`;
const spotifyLink = (artist, track = "", label = "Spotify ↗") => `<a class="button" href="${spotifyUrl(artist, track)}" target="_blank" rel="noopener" data-listen-open data-artist="${esc(artist)}" data-track="${esc(track)}">${label}</a>`;
const feedbackChoices = new Map();
const feedbackSaving = new Set();
const feedbackAccess = feedbackIO({
  read: () => api("/api/feedback"),
  write: (body) => api("/api/feedback", { method: "POST", body }),
});
let feedbackRevision = 0;
function rememberFeedback(stats) {
  if (!Array.isArray(stats.saved_items)) return;
  feedbackChoices.clear();
  for (const item of stats.saved_items) feedbackChoices.set(feedbackIdentity(item.artist, item.track), item.verdict);
}
function saveFeedback(body) {
  return feedbackAccess.save(body);
}
async function loadFeedbackChoices() {
  try { rememberFeedback(await feedbackAccess.read()); } catch { /* a later rating can retry */ }
}
function savedVerdict(item, artist, track = "") {
  const verdict = typeof item?.feedback === "string" ? item.feedback : item?.feedback?.verdict;
  return verdict || feedbackChoices.get(feedbackIdentity(artist, track)) || "";
}
function ratingMessage(verdict, song = false) {
  return (song ? {
    like: "Liked this song. It now helps shape your taste and related recommendations.",
    dislike: "Disliked this song. It won’t appear again and similar music moves down. Other songs by this artist can still appear.",
    known: "Already know this song. It won’t appear again; this doesn’t count as a like or dislike.",
    clear: "Song choice removed. It can appear again.",
  } : {
    like: "Liked this artist. Similar music moves up in your recommendations.",
    dislike: "Disliked this artist. They won’t appear again and similar artists move down.",
    known: "Already know this artist. They won’t appear again; this doesn’t count as a like or dislike.",
    clear: "Artist choice removed. They can appear again.",
  })[verdict] || "";
}
function ratingButtons(artist, track = "", verdict = "") {
  const song = Boolean(track);
  const label = song ? `“${track}” by ${artist}` : artist;
  return `<button data-act="like" aria-label="Like ${song ? "this song: " : ""}${esc(label)}" aria-pressed="${verdict === "like"}">Like</button>
    <button data-act="dislike" aria-label="Dislike ${song ? "this song: " : "this artist: "}${esc(label)}" aria-pressed="${verdict === "dislike"}">${song ? "Dislike" : "Not for me"}</button>
    <button data-act="known" class="quiet" aria-label="Already know ${esc(label)}" aria-pressed="${verdict === "known"}">Already know${song ? "" : " them"}</button>`;
}
function ratingStatus(artist, track = "", verdict = "") {
  return `<div class="rec-state" role="status"><span>${esc(ratingMessage(verdict, Boolean(track)))}</span> <button data-act="undo" class="quiet" ${verdict ? "" : "hidden"} aria-label="Undo ${track ? "song" : "artist"} choice for ${esc(track || artist)}">Undo</button></div>`;
}
const learningCopy = "Ratings shape your taste; preview listening and music links add weaker interest signals.";

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private mode */ }
  return null;
}

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body, headers = {} } = {}) {
  if (engine) {
    const { status, payload } = await engine.request(method, path, body, headers);
    if (status >= 400) throw new ApiError(status, (payload && payload.error) || `Error ${status}`);
    return payload;
  }
  const opts = { method, headers: { ...headers } };
  if (method !== "GET") opts.headers["X-MusicFinder"] = "1";
  if (body !== undefined) {
    if (body instanceof Blob) opts.body = body;
    else { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new ApiError(res.status, (data && data.error) || res.statusText);
  return data;
}

let toastTimer;
function toast(msg, ms = 4000) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

// tooltip for any element with data-tip (chart marks, meter segments)
const tip = $("#tooltip");
document.addEventListener("pointerover", (e) => {
  const el = e.target.closest("[data-tip]");
  if (!el) return;
  tip.textContent = el.getAttribute("data-tip");
  tip.hidden = false;
});
document.addEventListener("pointermove", (e) => {
  if (tip.hidden) return;
  const x = Math.min(window.innerWidth - tip.offsetWidth - 8, e.clientX + 14);
  tip.style.left = `${x}px`;
  tip.style.top = `${e.clientY + 16}px`;
});
document.addEventListener("pointerout", (e) => { if (e.target.closest("[data-tip]")) tip.hidden = true; });

// ---------------------------------------------------------------- state & jobs
async function refreshState() {
  state = await api("/api/state");
  $("#demo-strip").hidden = !state.demo;
  $("#service-strip").hidden = state.lookup_available !== false;
  if (state.job.running) watchJob();
  return state;
}

const JOB_LABEL = { build: "Building your music map", evaluate: "Testing accuracy on your own history", prepare: "Improving your recommendations" };
let polling = false;
async function watchJob() {
  if (polling) return;
  polling = true;
  const strip = $("#job-strip");
  let failed = false;
  try {
    for (;;) {
      const job = await api("/api/job");
      strip.hidden = !job.running;
      if (job.running) {
        $("#job-step").textContent = `${JOB_LABEL[job.name] || "Working"} — ${job.step}`;
        $("#job-bar").style.width = job.total ? `${Math.round((100 * job.done) / job.total)}%` : "3%";
        $("#job-count").textContent = job.total ? `${job.done}/${job.total}` : "";
        await new Promise((r) => setTimeout(r, 700));
        continue;
      }
      if (job.error) toast(`${JOB_LABEL[job.name] || "Job"} failed: ${job.error}`, 9000);
      else if (job.name) toast(job.name === "evaluate" ? "Accuracy test finished." : "Your recommendations are ready.");
      break;
    }
  } catch (err) {
    failed = true;
    toast(`Couldn’t check progress: ${err.message}. Your work may still be running.`, 9000);
  } finally {
    polling = false;
    strip.hidden = true;
    if (engine) engine.keepAwake(false);
  }
  if (failed) return; // a later navigation can retry; do not loop on a broken progress endpoint
  if ($("#pick-q")) {
    // On Setup someone may be typing: refresh only the build button, not the whole view.
    await refreshState().catch(() => {});
    updateBuildControls();
  } else {
    route();
  }
}

// Start a background job; returns whether it started (errors are shown, not thrown).
async function startJob(path) {
  if (state.lookup_available === false) {
    toast("New music lookups need a connected service. Your imports and saved taste still work here.", 7000);
    return false;
  }
  if (engine) engine.keepAwake(true);
  let res;
  try {
    res = await api(path, { method: "POST", body: {} });
  } catch (err) {
    if (engine) engine.keepAwake(false);
    toast(err.message, 9000);
    return false;
  }
  if (!res.started) toast("Another task is already running. Try again when it finishes.");
  watchJob();
  return res.started;
}

// A button that starts a job: disabled while starting, then onStarted() (by default, redraw the view).
function jobButton(btn, path, onStarted = () => route()) {
  if (!btn) return;
  const canOpen = () => path === "/api/prepare" && state.graph_ready && ["current", "history", "more_history", "taste"].includes(nextRecommendationAction(state));
  if (state.lookup_available === false && !canOpen()) btn.disabled = true;
  btn.addEventListener("click", async () => {
    if (canOpen()) {
      onStarted();
      return;
    }
    const mine = routeSeq;
    btn.disabled = true;
    if (await startJob(path)) { if (mine === routeSeq && btn.isConnected) onStarted(); }
    else btn.disabled = false;
  });
}

// Something to build from: picked favourites or an imported history.
const canBuild = () => Boolean(state.has_data || state.plays || (state.picks && state.picks.loved));

// ---------------------------------------------------------------- routing
const views = { "for-you": viewForYou, songs: viewSongs, explore: viewExplore, taste: viewTaste, accuracy: viewAccuracy, setup: viewSetup };

let routeSeq = 0; // each navigation's number: a slower, older one never overwrites a newer one
let setupPickListener = null;

async function route() {
  const mine = ++routeSeq;
  if (setupPickListener) {
    document.removeEventListener("sideband-picks", setupPickListener);
    setupPickListener = null;
  }
  let name = location.hash.slice(1) || "for-you";
  if (!views[name]) name = "for-you";
  try {
    await refreshState();
  } catch (err) {
    if (mine !== routeSeq) return;
    main.innerHTML = BROWSER
      ? `<div class="empty"><h2>Sideband couldn’t start</h2><p>Reload the page to try again. If it keeps happening, this browser may be too old to run it. (${esc(err.message)})</p></div>`
      : `<div class="empty"><h2>Can’t reach Sideband</h2><p>Is <code>Sideband serve</code> still running? (${esc(err.message)})</p></div>`;
    return;
  }
  if (mine !== routeSeq) return;
  if (!canBuild() && !state.graph_exists && !["setup", "taste", "accuracy"].includes(name)) name = "setup";
  document.querySelectorAll(".tabs a").forEach((a) => {
    if (a.getAttribute("href") === `#${name}`) {
      a.setAttribute("aria-current", "page");
      a.scrollIntoView({ block: "nearest", inline: "nearest" }); // the tab bar scrolls sideways on phones
    }
    else a.removeAttribute("aria-current");
  });
  try {
    await views[name]();
    if (mine === routeSeq && ["for-you", "songs", "explore"].includes(name) && state.graph_exists) staleStrip();
  } catch (err) {
    if (mine !== routeSeq) return; // the person has already moved on to another view
    if (err instanceof ApiError && err.status === 409) return renderBuildPrompt(err.message);
    main.innerHTML = `<div class="empty"><h2>Something went wrong</h2><p class="error">${esc(err.message)}</p></div>`;
  }
}
window.addEventListener("hashchange", () => { route(); main.focus({ preventScroll: true }); });

function renderBuildPrompt(reason) {
  const running = state.job.running && ["build", "prepare"].includes(state.job.name);
  main.innerHTML = `
    <div class="empty">
      <h2>${running ? "Building your music map…" : "One more step: build your music map"}</h2>
      <p>${running ? "This reads similar-artist data around your favourites. The first run takes a few minutes; later runs come from the cache." : esc(reason || "")}</p>
      ${running ? "" : `<p>Sideband will look up artists similar to your favourites in public music data (${sourceNames()}), then rank every unfamiliar artist it finds.</p>
      <button class="primary" id="build-now">${state.plays ? "Use my history to find music" : "Build my music map"}</button>`}
    </div>`;
  jobButton($("#build-now"), "/api/prepare");
}

function needsGraph() {
  if (state.graph_exists) return false;
  renderBuildPrompt("Next, Sideband maps the artists around your taste.");
  return true;
}

const sourceNames = () => listJoin([...(state.settings.lastfm ? ["Last.fm"] : []), "Deezer", "ListenBrainz", "MusicBrainz"]);

// Picks or history changed since the map was built: offer to bring the recommendations up to date.
function staleStrip() {
  if (state.graph_ready || state.job.running) return;
  if ($("#prepare-for-you")) return; // the readiness card already supplies this action
  const note = document.createElement("div");
  note.className = "note stale";
  note.innerHTML = `<p>Your picks or listening data changed since these were worked out. <button type="button" class="primary">Update my recommendations</button></p>`;
  jobButton(note.querySelector("button"), "/api/prepare", () => note.remove());
  main.prepend(note);
}

function basisText(source = state) {
  const summary = source.input_summary || {};
  const loved = source.picks?.loved;
  const n = summary.picked_artists ?? (Array.isArray(loved) ? loved.length : loved || 0);
  const parts = [];
  if (source.plays) parts.push(`${fmt(source.plays)} plays analysed`);
  if (n) parts.push(`${n} artist${n === 1 ? "" : "s"} you picked`);
  if (summary.saved_tracks) parts.push(`${fmt(summary.saved_tracks)} saved song${summary.saved_tracks === 1 ? "" : "s"}`);
  if (summary.playlist_tracks) parts.push(`${fmt(summary.playlist_tracks)} playlist song${summary.playlist_tracks === 1 ? "" : "s"}`);
  if (summary.followed_artists) parts.push(`${fmt(summary.followed_artists)} followed artist${summary.followed_artists === 1 ? "" : "s"}`);
  return parts.join(" + ") || "your picks";
}

// ---------------------------------------------------------------- recommendation evidence meter
function meterScale(items) {
  let m = 0.5;
  for (const it of items) {
    let p = 0; let n = 0;
    for (const v of Object.values(it.contributions || {})) { if (v > 0) p += v; else n -= v; }
    const bonus = it.score - Object.values(it.contributions || {}).reduce((a, b) => a + b, 0);
    if (bonus > 0) p += bonus; else n -= bonus;
    m = Math.max(m, p, n);
  }
  return 112 / m;
}

function segPath(x, w, h, y, roundEnd) {
  const r = Math.min(4, w / 2, h / 2);
  if (roundEnd === "right") return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 -${r},${r}h-${w - r}z`;
  if (roundEnd === "left") return `M${x + w},${y}h-${w - r}a${r},${r} 0 0 0 -${r},${r}v${h - 2 * r}a${r},${r} 0 0 0 ${r},${r}h${w - r}z`;
  return `M${x},${y}h${w}v${h}h-${w}z`;
}

function meter(item, scale) {
  const entries = Object.entries(item.contributions || {});
  const bonus = item.score - entries.reduce((a, [, v]) => a + v, 0);
  if (Math.abs(bonus) > 0.01) entries.push(["Novelty bonus (adventurous setting)", bonus]);
  const W = 240; const H = 18; const mid = W / 2; const y = 3; const h = 12; const gap = 2;
  const pos = entries.filter(([, v]) => v > 0.005).sort((a, b) => b[1] - a[1]);
  const neg = entries.filter(([, v]) => v < -0.005).sort((a, b) => a[1] - b[1]);
  let out = "";
  let x = mid + 1;
  pos.forEach(([k, v], i) => {
    const w = Math.max(1.5, Math.min(W - x, v * scale) - gap);
    if (w <= 0) return;
    out += `<path class="pos" d="${segPath(x, w, h, y, i === pos.length - 1 ? "right" : "")}" data-tip="${esc(k)}: +${v.toFixed(2)}"></path>`;
    x += w + gap;
  });
  x = mid - 1;
  neg.forEach(([k, v], i) => {
    const w = Math.max(1.5, Math.min(x, -v * scale) - gap);
    if (w <= 0) return;
    x -= w;
    out += `<path class="neg" d="${segPath(x, w, h, y, i === neg.length - 1 ? "left" : "")}" data-tip="${esc(k)}: ${v.toFixed(2)}"></path>`;
    x -= gap;
  });
  const net = entries.reduce((a, [, v]) => a + v, 0);
  const nx = Math.max(1, Math.min(W - 1, mid + net * scale));
  const rows = [...entries].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).map(([k, v]) =>
    `<tr><td><span class="key-swatch" style="background:var(${v >= 0 ? "--pos" : "--neg"})"></span>${esc(k)}</td><td class="num">${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}</td></tr>`).join("");
  const label = `Evidence: ${pos.length} signals for, ${neg.length} against, net ${net.toFixed(2)}`;
  return `<div class="meter">
      <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">
        <rect class="track" x="0" y="${y}" width="${W}" height="${h}" rx="4"></rect>
        ${out}<line class="axis" x1="${mid}" x2="${mid}" y1="0" y2="${H}"></line>
        <line class="net" x1="${nx}" x2="${nx}" y1="0" y2="${H}" data-tip="Net score ${net.toFixed(2)}"></line>
      </svg>
      <details class="why"><summary>Why this match</summary>
        <table><thead><tr><th>Signal (standardised)</th><th class="num">Effect</th></tr></thead><tbody>${rows}
        <tr><td><b>Net score</b></td><td class="num"><b>${net.toFixed(2)}</b></td></tr></tbody></table>
      </details>
    </div>`;
}

const meterKey = `<div class="meter-key small" aria-hidden="true">
  <span><span class="key-swatch" style="background:var(--pos)"></span>evidence for</span>
  <span><span class="key-swatch" style="background:var(--neg)"></span>evidence against</span>
  <span><span class="key-swatch" style="background:var(--ink);width:3px"></span>net score</span>
</div>`;

function recRow(r, i, scale, extraCtx = {}) {
  const tags = (r.tags || []).slice(0, 4).map(esc).join(" · ");
  const because = r.because?.length ? `Because of ${listJoin(r.because.slice(0, 3).map((n) => `<b>${esc(n)}</b>`))} in your taste` : "Reached through your wider taste network";
  const shared = r.shared_tags?.length ? `; shares ${listJoin(r.shared_tags.map(esc))} with your taste.` : ".";
  const prob = r.like_probability != null
    ? `<div class="prob" title="An estimate fitted to your own ratings; not independently validated">≈${Math.round(r.like_probability * 100)}% provisional like estimate</div>` : "";
  const truth = r.true_like_probability != null
    ? `<span class="truth-chip">Simulation’s true like-probability: ${Math.round(r.true_like_probability * 100)}%</span>` : "";
  const ctx = { ...(r.context || {}), ...extraCtx };
  const listeners = r.popularity ? ` · ${compact(r.popularity)} listeners` : "";
  const verdict = savedVerdict(r, r.name);
  return `<li class="rec${verdict ? " rated" : ""}" data-artist="${esc(r.name)}" data-feedback="${esc(verdict)}" data-ctx="${esc(JSON.stringify(ctx))}">
    <div class="rec-rank">${String(i + 1).padStart(2, "0")}</div>
    <div>
      <h3 class="rec-name">${esc(r.name)}</h3>
      <div class="rec-tags">${tags || "no genre tags"}${listeners}</div>
      <p class="rec-why">${because}${shared}</p>
      ${meter(r, scale)}
      ${truth}
      <div class="rec-actions">
        <button data-act="play" data-label="Play a preview" aria-label="Play a preview of ${esc(r.name)}">Play a preview</button>
        ${spotifyLink(r.name, "", "Open in Spotify ↗")}
        ${ratingButtons(r.name, "", verdict)}
      </div>
      ${ratingStatus(r.name, "", verdict)}
    </div>
    <div class="rec-side">
      <div class="sticker" title="Scores higher than ${Math.floor(r.match)}% of the unfamiliar artists considered; this is not a probability" data-tip="Scores higher than ${Math.floor(r.match)}% of the unfamiliar artists considered; this is not a probability"><b>${Math.floor(r.match)}</b><span>percentile</span></div>
      ${prob}
    </div>
  </li>`;
}

// ---------------------------------------------------------------- shared actions
main.addEventListener("click", async (e) => {
  const link = e.target.closest("a[data-listen-open]");
  if (link) {
    // Opening another app expresses interest, not an observed Spotify play.
    recordInteraction({ artist: link.dataset.artist, track: link.dataset.track || "", kind: "external_open", event_id: interactionId() });
    return;
  }
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const row = btn.closest("[data-artist]");
  const act = btn.dataset.act;
  if (act === "play" && row) return playPreview(btn, row.dataset.artist, row.dataset.track);
  if (act === "tag") return exploreTag(btn.dataset.tag);
  if (!["like", "dislike", "known", "undo"].includes(act) || !row || row.dataset.saving) return;
  const ctx = JSON.parse(row.dataset.ctx || "{}");
  const track = row.dataset.track || "";
  const identity = feedbackIdentity(row.dataset.artist, track);
  if (feedbackSaving.has(identity)) return;
  const verdict = act === "undo" ? "clear" : act;
  if (verdict === row.dataset.feedback) return;
  const buttons = row.querySelectorAll("button[data-act=like],button[data-act=dislike],button[data-act=known],button[data-act=undo]");
  const message = row.querySelector(".rec-state span");
  const previousMessage = message.textContent;
  message.textContent = act === "undo" ? "Removing your rating…" : "Saving your rating…";
  row.dataset.saving = "1";
  feedbackSaving.add(identity);
  buttons.forEach((b) => { b.disabled = true; });
  try {
    const stats = await saveFeedback({ artist: row.dataset.artist, track, verdict, context: ctx });
    feedbackRevision += 1;
    rememberFeedback(stats);
    if (verdict === "clear") feedbackChoices.delete(identity);
    else feedbackChoices.set(identity, verdict);
    // A song can occur in several sections. Keep every visible copy consistent.
    for (const item of main.querySelectorAll("li[data-artist]")) {
      if (feedbackIdentity(item.dataset.artist, item.dataset.track || "") !== identity || !item.querySelector(".rec-state")) continue;
      item.dataset.feedback = verdict === "clear" ? "" : verdict;
      item.querySelectorAll("button[data-act=like],button[data-act=dislike],button[data-act=known]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.act === verdict)));
      item.querySelector(".rec-state span").textContent = ratingMessage(verdict, Boolean(track));
      item.querySelector("button[data-act=undo]").hidden = verdict === "clear";
      item.classList.toggle("rated", verdict !== "clear");
    }
    const refresh = $(track ? "#refresh-songs" : "#refresh-recs");
    if (refresh) refresh.textContent = act === "undo" ? "Refresh my list" : "Apply ratings to my list";
    const status = $(track ? "#songs-status" : "#list-status");
    if (status) status.textContent = "Saved. Refresh to use your updated taste. Your choice stays here until then so you can undo it.";
  } catch (err) {
    message.textContent = previousMessage;
    toast(`Couldn’t save that: ${err.message}`);
  } finally {
    delete row.dataset.saving;
    feedbackSaving.delete(identity);
    buttons.forEach((b) => { b.disabled = false; });
  }
});
main.addEventListener("auxclick", (event) => {
  const link = event.button === 1 && event.target.closest("a[data-listen-open]");
  if (link) recordInteraction({ artist: link.dataset.artist, track: link.dataset.track || "", kind: "external_open", event_id: interactionId() });
});

function interactionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else bytes.forEach((_, i) => { bytes[i] = Math.floor(Math.random() * 256); });
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function recordInteraction(body) {
  // Learning failures must never interrupt playback or external navigation.
  api("/api/interactions", { method: "POST", body }).catch(() => {});
}

let playingBtn = null;
let previewSession = null;
let playbackSeq = 0;
function samplePreview() {
  if (!previewSession) return;
  const heard = previewSession.observation.sample(player.currentTime, performance.now(), { audible: previewSession.audible, rate: player.playbackRate });
  previewSession.audible = !player.muted && player.volume > 0;
  return heard;
}
function finishPreview() {
  if (!previewSession) return;
  samplePreview();
  previewSession.observation.suspend();
  const duration = previewSession.observation.take();
  if (duration != null) recordInteraction({ artist: previewSession.artist, track: previewSession.track, kind: "preview_listen", duration_ms: duration, event_id: previewSession.id });
}
function resetPlayButton() {
  if (!playingBtn) return;
  playingBtn.textContent = playingBtn.dataset.label || "Play";
  playingBtn.removeAttribute("aria-pressed");
  playingBtn = null;
}
player.addEventListener("playing", () => {
  if (!previewSession) return;
  previewSession.audible = !player.muted && player.volume > 0;
  previewSession.observation.start(player.currentTime, performance.now());
});
player.addEventListener("timeupdate", samplePreview);
player.addEventListener("waiting", () => { samplePreview(); previewSession?.observation.suspend(); });
player.addEventListener("seeking", () => previewSession?.observation.suspend());
player.addEventListener("seeked", () => { if (!player.paused) previewSession?.observation.start(player.currentTime, performance.now()); });
player.addEventListener("volumechange", () => { samplePreview(); });
player.addEventListener("ended", () => { finishPreview(); resetPlayButton(); });
player.addEventListener("pause", () => { finishPreview(); resetPlayButton(); });
window.addEventListener("pagehide", finishPreview);

async function playPreview(btn, artist, track) {
  if (playingBtn === btn && !player.paused) { player.pause(); return; }
  player.pause();
  finishPreview();
  previewSession = null;
  const mine = ++playbackSeq;
  btn.disabled = true;
  btn.textContent = "Finding a preview…";
  try {
    let info = null;
    const titles = track ? [track] : (await api(`/api/artist/tracks?name=${enc(artist)}&n=4`)).items.map((t) => t.title);
    for (const t of titles) {
      info = await api(`/api/preview?artist=${enc(artist)}&track=${enc(t)}`);
      if (info && info.preview_url) break;
    }
    if (mine !== playbackSeq) { btn.textContent = btn.dataset.label || "Play"; return; }
    if (!info || !info.preview_url) {
      btn.textContent = "No preview — try Spotify";
      return;
    }
    previewSession = { artist: info.artist || artist, track: info.title || track, id: interactionId(), audible: !player.muted && player.volume > 0, observation: previewObservation() };
    player.src = info.preview_url;
    await player.play();
    if (mine !== playbackSeq) { btn.textContent = btn.dataset.label || "Play"; return; }
    playingBtn = btn;
    btn.textContent = `Pause · “${info.title}”`;
    btn.setAttribute("aria-pressed", "true");
  } catch (err) {
    if (mine === playbackSeq) previewSession = null;
    btn.textContent = "Preview unavailable";
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- For you
let exploration = explorationChoice(store("mf.exploration"));
let batchSize = batchChoice(store("mf.batchSize"));

function dialText(e) {
  if (e < 0.2) return "Close matches: prioritise artists near the ones you already love.";
  if (e < 0.45) return "Mostly close matches, with a few less obvious names mixed in.";
  if (e < 0.7) return "Balanced: lesser-known artists and neighbouring genres. Expect a few more misses.";
  return "Adventurous: less famous artists further from your usual genres. Lower hit rate, more discoveries.";
}

function personalizationPanel() {
  const p = state.personalization || {};
  const next = nextRecommendationAction(state);
  const title = {
    working: "Your recommendations are being updated",
    history: "Make this more personal with your history",
    taste: "Your favourites shape these picks",
    more_history: "More history can sharpen personal settings",
    prepare: state.plays ? "Get more from your listening history" : "Update your music map",
    current: !state.plays ? "Your choices shape these picks"
      : p.model_current ? "Your history is shaping these picks" : "Your history has been checked",
  }[next];
  const reason = p.reason || (state.plays
    ? "Check which settings predict your later listening best, then use a fitted model when the evidence supports it."
    : "Import a Spotify export to learn from your plays, listening dates and any recorded skips. Your favourite picks are kept.");
  const range = p.first && p.last ? ` · ${esc(p.first)} to ${esc(p.last)}` : "";
  const details = state.plays ? `${fmt(state.plays)} plays${range}${p.has_skip_data === false ? " · no skip information" : ""}` : basisText();
  const action = next === "prepare" ? `<button id="prepare-for-you" class="primary">${state.plays ? "Improve from my history" : "Update my recommendations"}</button>`
    : next === "history" ? `<a class="button" href="#setup">Add my history</a>`
    : next === "taste" ? `<a class="button" href="#setup">Refine my taste</a>`
    : next === "more_history" ? `<a class="button" href="#setup">Add more history</a>`
    : `<a class="button" href="#accuracy">See accuracy and evidence</a>`;
  return `<section class="personalization" aria-label="Recommendation status"><div><h2>${title}</h2><p>${esc(reason)}</p><p class="small muted">${details}</p></div><div class="row">${action}</div></section>`;
}

async function viewForYou() {
  if (needsGraph()) return;
  const mine = routeSeq;
  const fitted = state.personalization?.model_current ?? state.personalised_model;
  const sub = `Based on ${basisText()} · ranking model: ${fitted
    ? "fitted to your history by the accuracy test"
    : state.personalised_model ? "fitted to earlier history; new history needs a fresh check"
    : state.plays ? (state.personalization?.tested_current
      ? "default settings; this history did not support a reliable change"
      : state.personalization?.can_evaluate === false ? "default settings; more history needed for personal settings"
      : 'default settings; <a href="#accuracy">check personal settings</a>') : "default settings"}`;
  main.innerHTML = `
    <div class="view-head">
      <div><h1>New artists for you</h1><p>${sub}</p></div>
      <div class="dial">
        <label for="dial">How adventurous?</label>
        <input id="dial" type="range" min="0" max="1" step="0.05" value="${exploration}">
        <div class="dial-ends"><span>Safe bets</span><span>Adventurous</span></div>
        <output id="dial-say" for="dial">${dialText(exploration)}</output>
      </div>
    </div>
    ${personalizationPanel()}
    <div class="recommendation-controls"><div class="row"><label for="batch-size">Artists at a time</label>
      <select id="batch-size">${[10, 20, 30].map((n) => `<option value="${n}" ${n === batchSize ? "selected" : ""}>${n}</option>`).join("")}</select>
      <button id="refresh-recs">Refresh my list</button></div>
      <p class="small muted">${learningCopy}</p>
      <p class="small muted" id="list-status" role="status">Rate a few after listening, then refresh to see your updated taste.</p>
    </div>
    ${meterKey}
    <ol class="recs" id="recs"><li class="loading">Ranking every candidate…</li></ol>`;
  jobButton($("#prepare-for-you"), "/api/prepare");
  const box = $("#recs");
  const refresh = $("#refresh-recs");
  const status = $("#list-status");
  const requests = latestRequest();
  const load = async () => {
    const token = requests.start();
    const revision = feedbackRevision;
    refresh.disabled = true;
    box.setAttribute("aria-busy", "true");
    status.textContent = "Updating your list…";
    try {
      const [data] = await Promise.all([api(`/api/recommendations?n=${batchSize}&exploration=${exploration}`), loadFeedbackChoices()]);
      if (mine !== routeSeq || !requests.current(token) || !box.isConnected || revision !== feedbackRevision) return;
      const items = data.items;
      const scale = meterScale(items);
      box.innerHTML = items.length
        ? items.map((r, i) => recRow(r, i, scale)).join("")
        : `<li class="empty">No unfamiliar artists found near your taste yet. Pick a few more artists you love in <a href="#setup">Setup</a>, or add more Spotify history.</li>`;
      status.textContent = `${items.length} artists ready. The percentile compares candidates; it is not the chance you’ll like them.`;
      refresh.textContent = "Refresh my list";
    } finally {
      if (requests.current(token) && box.isConnected) {
        refresh.disabled = false;
        box.setAttribute("aria-busy", "false");
      }
    }
  };
  let t;
  $("#dial").addEventListener("input", (e) => {
    requests.start(); // invalidate older results as soon as the listener changes the dial
    exploration = Number(e.target.value);
    store("mf.exploration", String(exploration));
    $("#dial-say").textContent = dialText(exploration);
    clearTimeout(t);
    t = setTimeout(() => load().catch((err) => toast(err.message)), 300);
  });
  $("#batch-size").addEventListener("change", (e) => {
    batchSize = batchChoice(e.target.value);
    store("mf.batchSize", String(batchSize));
    clearTimeout(t);
    load().catch((err) => toast(err.message));
  });
  refresh.addEventListener("click", () => { clearTimeout(t); load().catch((err) => toast(err.message)); });
  await load();
}

// ---------------------------------------------------------------- Songs
function songRow(s) {
  const verdict = savedVerdict(s, s.artist, s.title);
  const ctx = { ...(s.context || {}), source: "songs", kind: s.kind || "song", exploration };
  return `<li class="song song-rec${verdict ? " rated" : ""}" data-artist="${esc(s.artist)}" data-track="${esc(s.title)}" data-feedback="${esc(verdict)}" data-ctx="${esc(JSON.stringify(ctx))}">
    <div class="song-details"><div class="song-title">${esc(s.title)} <span class="muted">— ${esc(s.artist)}</span></div>
    <div class="song-why">${esc(s.because)}</div>
    ${ratingStatus(s.artist, s.title, verdict)}</div>
    <div class="song-actions"><div class="row"><button data-act="play" data-label="Play a preview" aria-label="Play a preview of ${esc(s.title)} by ${esc(s.artist)}">Play a preview</button>
    ${spotifyLink(s.artist, s.title)}</div>
    <div class="row song-ratings" role="group" aria-label="Your opinion of ${esc(s.title)}">${ratingButtons(s.artist, s.title, verdict)}</div></div>
  </li>`;
}

async function viewSongs() {
  if (needsGraph()) return;
  const mine = routeSeq;
  main.innerHTML = `
    <div class="view-head"><div><h1>Songs to try</h1>
    <p>Three kinds of picks, kept apart so you always know why a song is here.</p></div></div>
    <div class="recommendation-controls"><button id="refresh-songs">Refresh my list</button>
    <p class="small muted">${learningCopy} Dislike applies to this song; it doesn’t exclude its whole artist. <a href="#taste">Review your saved choices</a>.</p>
    <p class="small muted" id="songs-status" role="status">Looking up songs…</p></div>
    <div id="songs"></div>`;
  const refresh = $("#refresh-songs");
  const status = $("#songs-status");
  const box = $("#songs");
  const requests = latestRequest();
  const load = async () => {
    const token = requests.start();
    const revision = feedbackRevision;
    refresh.disabled = true;
    box.setAttribute("aria-busy", "true");
    status.textContent = "Looking up songs using your current taste…";
    try {
      const [data] = await Promise.all([api(`/api/songs?exploration=${exploration}`), loadFeedbackChoices()]);
      if (mine !== routeSeq || !requests.current(token) || !box.isConnected || revision !== feedbackRevision) return;
      const block = (title, lede, items) => `<section class="section"><h2>${title}</h2><p class="lede">${lede}</p>
        ${items.length ? `<ol class="songs">${items.map(songRow).join("")}</ol>` : `<p class="muted">Nothing new found for this list yet.</p>`}</section>`;
      box.innerHTML =
        block("Songs like your favourites", "Songs connected to your favourites, ordered using your choices and music similarity.", data.similar_song)
        + block("From new artists", "Songs from new artists matched to your current taste.", data.new_artist)
        + block("Unheard songs by artists you love", "Songs from your favourite artists that aren’t in your saved listening history or choices.", data.deep_cut);
      status.textContent = "Your song choices are saved across visits. Rate what you try, then refresh for new picks.";
      refresh.textContent = "Refresh my list";
    } finally {
      if (requests.current(token) && box.isConnected) {
        refresh.disabled = false;
        box.setAttribute("aria-busy", "false");
      }
    }
  };
  refresh.addEventListener("click", () => load().catch((err) => toast(err.message)));
  await load();
}

// ---------------------------------------------------------------- Explore
function bars(rows, { max } = {}) {
  const m = max ?? Math.max(...rows.map((r) => r.value), 1e-9);
  return `<ul class="bars">${rows.map((r) => `<li><span class="lbl" title="${esc(r.label)}">${esc(r.label)}</span>
    <span class="bar" style="width:${Math.max(0.5, (100 * r.value) / m)}%" data-tip="${esc(r.label)}: ${esc(r.text)}"></span>
    <span class="val">${esc(r.text)}</span></li>`).join("")}</ul>`;
}

const tagRequests = latestRequest();
async function exploreTag(tag) {
  const box = $("#tag-result");
  if (!box || !tag) return;
  const mine = routeSeq;
  const token = tagRequests.start();
  $("#tag-input").value = tag;
  box.innerHTML = `<p class="loading">Finding your best way into “${esc(tag)}”…</p>`;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const res = await api(`/api/explore/tag?tag=${enc(tag)}`);
    if (mine !== routeSeq || !tagRequests.current(token) || !box.isConnected) return;
    const scale = meterScale(res.gateways);
    box.innerHTML = `<section class="territory"><div class="territory-head"><h2>Your way into ${esc(res.tag)}</h2>
      <span class="meta">${res.found} artists checked; ranked by how close each sits to what you already love</span></div>
      ${res.you_already_know.length ? `<p class="meta">You already know ${esc(res.you_already_know.join(", "))}.</p>` : ""}
      ${res.gateways.length ? `<ol class="recs">${res.gateways.map((r, i) => recRow(r, i, scale, { territory: res.tag })).join("")}</ol>`
        : `<p class="muted">No artists found for that genre. Try a broader word, like jazz, metal or folk.</p>`}</section>`;
  } catch (err) {
    if (mine !== routeSeq || !tagRequests.current(token) || !box.isConnected) return;
    box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

async function viewExplore() {
  if (needsGraph()) return;
  const mine = routeSeq;
  main.innerHTML = `
    <div class="view-head"><div><h1>Explore beyond your usual</h1>
    <p>Discover genres connected to your listening. Similarity and your ratings guide the order, with room for genres you have not tried yet. This exploration order is a guide, not a measured chance you will like a genre.</p></div>
    <div><button id="shuffle">Shuffle the genres</button></div></div>
    <div class="split"><div id="terrs"><p class="loading">Mapping genres around your taste…</p></div>
    <aside class="stack" id="explore-side"></aside></div>
    <div id="tag-result"></div>`;
  const requests = latestRequest();
  const load = async (seed) => {
    const token = requests.start();
    const data = await api(`/api/explore${seed != null ? `?seed=${seed}` : ""}`);
    if (mine !== routeSeq || !requests.current(token)) return;
    $("#terrs").innerHTML = data.territories.length ? data.territories.map((t) => {
      const scale = meterScale(t.gateways);
      const next = t.related_genres_you_know.length ? `Next door to ${esc(listJoin(t.related_genres_you_know))}` : "Reached through your taste network";
      const rated = t.likes + t.dislikes ? `You liked ${t.likes} of ${t.likes + t.dislikes} rated artists here` : "You have not rated artists in this genre yet";
      return `<section class="territory"><div class="territory-head"><h2>${esc(t.tag)}</h2>
        <span class="meta">${rated}</span></div>
        <p class="meta">${next}. Best ways in:</p>
        <ol class="recs">${t.gateways.map((r, i) => recRow(r, i, scale, { territory: t.tag })).join("")}</ol></section>`;
    }).join("") : `<div class="empty"><h2>No unfamiliar genres nearby yet</h2><p>Use the genre search to jump anywhere.</p></div>`;
    const yours = data.your_genres.slice(0, 10).map((g) => ({ label: g.tag, value: g.share, text: pct(g.share) }));
    $("#explore-side").innerHTML = `
      <section><h2>Your genres now</h2><p class="small muted">Share of your weighted listening, from genre tags.</p>${bars(yours)}</section>
      <section><h2>Jump anywhere</h2>
        <form id="tag-form" class="row" role="search"><label for="tag-input" class="small">Genre or style</label>
          <input id="tag-input" type="search" placeholder="e.g. bossa nova" autocomplete="off">
          <button class="primary" type="submit">Find my way in</button></form>
        <p class="small muted">Further from your taste:</p>
        <div class="chips">${data.far_genres.map((g) => `<button data-act="tag" data-tag="${esc(g)}">${esc(g)}</button>`).join("")}</div>
      </section>`;
    $("#tag-form").addEventListener("submit", (e) => { e.preventDefault(); exploreTag($("#tag-input").value.trim()); });
  };
  $("#shuffle").addEventListener("click", () => load(Math.floor(Math.random() * 1e6)).catch((err) => toast(err.message)));
  await load();
}

// ---------------------------------------------------------------- Your taste
function savedChoiceRow(item) {
  const track = item.track || "";
  const ctx = item.context || (track ? { source: "songs", kind: item.kind || "song" } : {});
  return `<li class="song song-rec rated" data-artist="${esc(item.artist)}" data-track="${esc(track)}" data-feedback="${esc(item.verdict)}" data-ctx="${esc(JSON.stringify(ctx))}">
    <div class="song-details"><div class="song-title">${esc(track || item.artist)}${track ? ` <span class="muted">— ${esc(item.artist)}</span>` : ""}</div>
    <div class="song-why">${track ? "Song choice" : "Artist choice"}</div>${ratingStatus(item.artist, track, item.verdict)}</div>
    <div class="song-actions"><div class="row">${ratingButtons(item.artist, track, item.verdict)}</div>${spotifyLink(item.artist, track)}</div></li>`;
}
function savedChoices(fb) {
  const items = fb.saved_items || [];
  return `<section class="section" id="saved-choices"><h2>Your saved choices</h2>
    <p>Change a choice or Undo it here, including songs that disappeared after you refreshed. Song and artist choices stay separate.</p>
    ${items.length ? `<ol class="songs" id="saved-choices-list">${items.slice(0, 30).map(savedChoiceRow).join("")}</ol>
      ${items.length > 30 ? `<button id="more-saved-choices">Show all ${fmt(items.length)} saved choices</button>` : ""}` : `<p class="muted">Your song and artist ratings will appear here.</p>`}</section>`;
}
function bindSavedChoices() {
  const button = $("#more-saved-choices");
  if (!button) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const fb = await feedbackAccess.read();
      if (!button.isConnected) return;
      rememberFeedback(fb);
      $("#saved-choices-list").innerHTML = (fb.saved_items || []).map(savedChoiceRow).join("");
      button.remove();
    } catch (err) { toast(err.message); button.disabled = false; }
  });
}
async function viewTaste() {
  const mine = routeSeq;
  main.innerHTML = `<p class="loading">Loading your saved taste…</p>`;
  const [p, fb] = await Promise.all([
    api("/api/profile").catch((error) => { if (error instanceof ApiError && error.status === 409) return null; throw error; }),
    feedbackAccess.read(),
  ]);
  if (mine !== routeSeq) return;
  rememberFeedback(fb);
  if (!p) {
    main.innerHTML = `<div class="view-head"><div><h1>Your taste so far</h1><p>Add artists you love in <a href="#setup">Setup</a> to find new music. Your saved choices are available below.</p></div></div>${savedChoices(fb)}`;
    bindSavedChoices();
    return;
  }
  const genres = p.genres ? `<section><h2>Genres</h2>${bars(p.genres.slice(0, 12).map((g) => ({ label: g.tag, value: g.share, text: pct(g.share) })))}</section>` : "";
  if (!p.plays) {
    const inputs = p.input_summary || {};
    const artists = inputs.artists?.length ? inputs.artists : p.picks.loved;
    const songs = inputs.songs || [];
    main.innerHTML = `
      <div class="view-head"><div><h1>Your taste so far</h1>
      <p>Based on ${esc(basisText(p))}. Your chosen artists and songs guide recommendations now; these are favourites, not a record of plays or skips.</p></div></div>
      <div class="split section">
        <section class="stack"><div><h2>Artists from your favourites</h2><ol class="songs">${artists.map((n) => `<li class="song"><div class="song-title">${esc(n)}</div></li>`).join("")}</ol>
          ${p.picks.disliked.length ? `<p class="small muted">Not for you: ${esc(p.picks.disliked.join(", "))}</p>` : ""}</div>
          ${songs.length ? `<div><h2>Songs you saved</h2><ol class="songs">${songs.map((s) => `<li class="song"><div><div class="song-title">${esc(s.track)}</div><div class="song-why">${esc(s.artist)}</div></div>${spotifyLink(s.artist, s.track)}</li>`).join("")}</ol></div>` : ""}
          <p class="small muted">Showing a sample of your saved input. <a href="#setup">Add or refine your favourites</a>.</p></section>
        <aside class="stack">${genres || `<p class="muted small">Genres appear once your music map is built.</p>`}</aside>
      </div>${savedChoices(fb)}`;
    bindSavedChoices();
    return;
  }
  const fmts = Object.entries(p.formats).map(([k, v]) => `${fmt(v)} ${k === "extended" ? "extended-history" : "account-data"} plays`).join(", ");
  const trendWord = { rising: "Rising", steady: "Steady", fading: "Fading" };
  const picked = p.picks.loved.length ? ` · ${fmt(p.picks.loved.length)} picked artists` : "";
  main.innerHTML = `
    <div class="view-head"><div><h1>Your taste, measured</h1>
    <p>${esc(p.first)} to ${esc(p.last)} · ${esc(fmts)}${p.library_items ? ` · ${fmt(p.library_items)} saved/followed/hidden items` : ""}${picked}</p></div></div>
    <div class="tiles">
      <div class="tile"><div class="label">Hours listened</div><div class="value">${fmt(Math.round(p.hours))}</div></div>
      <div class="tile"><div class="label">Streams (30 s or more)</div><div class="value">${fmt(p.streams)}</div></div>
      <div class="tile"><div class="label">Artists heard</div><div class="value">${fmt(p.artists_heard)}</div></div>
      <div class="tile" data-tip="exp(entropy) of your listening across artists: how many artists you effectively split your time between"><div class="label">Effective artists</div><div class="value">${fmt(Math.round(p.effective_artists))}</div></div>
      <div class="tile"><div class="label">Skipped in first 30 s</div><div class="value">${pct(p.skip_rate)}</div></div>
      ${p.median_listeners_of_top_artists ? `<div class="tile"><div class="label">Typical favourite’s audience</div><div class="value">${compact(p.median_listeners_of_top_artists)}</div></div>` : ""}
    </div>
    ${p.has_skip_data ? "" : `<div class="note"><p>Your data has no skip information (the “Account data” export). The <b>Extended streaming history</b> export adds recorded skip signals — request it in Setup.</p></div>`}
    <div class="split section">
      <section><h2>Artists, by modelled affinity</h2>
        <p class="lede small">Affinity weighs how much of each song you play, whether you chose it, and skips, with older listening fading (half-life ${p.model.memory_half_life_days ? `${Math.round(p.model.memory_half_life_days)} days` : "none"}). Artists you picked count as firm favourites. “Keeps you listening” is the estimated chance a play is not skipped, shrunk toward your average when there is little data.</p>
        <div class="table-wrap"><table><thead><tr><th>#</th><th>Artist</th><th class="num">Streams</th><th class="num">Early-skip rate</th><th class="num">Keeps you listening</th><th>Trend</th></tr></thead>
        <tbody>${p.top_artists.map((a, i) => `<tr><td class="num">${i + 1}</td><td>${esc(a.name)}${a.picked ? " · picked" : ""}${a.liked_in_app ? " · liked here" : ""}</td>
          <td class="num">${fmt(a.streams)}</td><td class="num">${a.streams + a.early_skips ? pct(a.skip_rate) : "—"}</td><td class="num">${a.streams + a.early_skips ? pct(a.satisfaction) : "—"}</td><td>${trendWord[a.trend] || "—"}</td></tr>`).join("")}</tbody></table></div>
      </section>
      <aside class="stack">
        ${genres}
        ${p.top_tracks.length ? `<section><h2>Most-loved songs</h2><ol class="songs">${p.top_tracks.slice(0, 15).map((t) => `<li class="song" data-artist="${esc(t.artist)}" data-track="${esc(t.title)}">
          <div><div class="song-title">${esc(t.title)}</div><div class="song-why">${esc(t.artist)} · ${fmt(t.streams)} streams</div></div></li>`).join("")}</ol></section>` : ""}
      </aside>
    </div>${savedChoices(fb)}`;
  bindSavedChoices();
}

// ---------------------------------------------------------------- Accuracy
function dotWhisker(rows, { chance = null, label = "" } = {}) {
  const W = 640; const left = 190; const right = 64; const rowH = 36; const top = 8;
  const H = top + rows.length * rowH + 26;
  const x = (v) => left + v * (W - left - right);
  let g = "";
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    g += `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${H - 22}"></line><text class="tick" x="${x(t)}" y="${H - 6}" text-anchor="middle">${t * 100}%</text>`;
  }
  if (chance != null) g += `<line class="chance" x1="${x(chance)}" x2="${x(chance)}" y1="${top}" y2="${H - 22}" stroke-width="2"></line>`;
  rows.forEach((r, i) => {
    const cy = top + i * rowH + rowH / 2;
    g += `<text class="label${r.me ? " me" : ""}" x="${left - 12}" y="${cy + 4}" text-anchor="end">${esc(r.name)}</text>`;
    if (r.value == null) return;
    if (r.ci) g += `<line class="whisker" x1="${x(r.ci[0])}" x2="${x(r.ci[1])}" y1="${cy}" y2="${cy}"></line>`;
    const tipText = `${r.name}: ${pct(r.value)}${r.ci ? ` (95% CI ${pct(r.ci[0])}–${pct(r.ci[1])})` : ""}`;
    g += `<circle class="dot${r.me ? "" : " base"}" cx="${x(r.value)}" cy="${cy}" r="${r.me ? 6 : 5}"></circle>`;
    g += `<circle class="hit" cx="${x(r.value)}" cy="${cy}" r="14" data-tip="${esc(tipText)}"></circle>`;
    g += `<text class="tick" x="${W - right + 10}" y="${cy + 4}">${pct(r.value)}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${g}</svg>`;
}

function metricsTable(rep) {
  const rows = [
    ["Sideband (as chosen)", rep.model, true],
    ["Same, default weights", rep.default_model],
    ["Similar-artists only", rep.baselines.similar_artists_only],
    ["Most popular first", rep.baselines.popularity],
    ["Random", rep.baselines.random],
  ];
  const cell = (v, f = pct) => `<td class="num">${v == null ? "—" : f(v)}</td>`;
  return `<div class="table-wrap"><table><thead><tr><th>Method</th><th class="num">Recall@10</th><th class="num">Recall@50</th><th class="num">Recall@100</th>
    <th class="num">Precision@10</th><th class="num">NDCG@50</th><th class="num">Percentile rank</th><th class="num">Preference AUC</th></tr></thead><tbody>
    ${rows.map(([n, m, me]) => `<tr${me ? ' class="highlight"' : ""}><td>${n}</td>${cell(m["recall@10"])}${cell(m["recall@50"])}${cell(m["recall@100"])}
      ${cell(m["precision@10"])}${cell(m["ndcg@50"], (v) => v.toFixed(2))}${cell(m.mean_percentile_rank, (v) => `${v.toFixed(0)}%`)}${cell(m.auc, (v) => v.toFixed(2))}</tr>`).join("")}
    </tbody></table></div>
    <p class="small muted">Recall@K: share of the new artists you returned to that were in the top K. Percentile rank: where they sat in the full ranking (0% = top); missing artists count as worst rank, including in the random baseline. Preference AUC: how often a repeated artist outranks a consistently skipped one among the covered artists (0.5 = guessing).</p>`;
}

async function viewAccuracy() {
  const mine = routeSeq;
  const [rep, fb] = await Promise.all([api("/api/evaluation"), feedbackAccess.read()]);
  if (mine !== routeSeq) return;
  const eligible = state.personalization?.can_evaluate ?? Boolean(state.plays);
  const intro = `<p>Sideband hides your most recent listening, predicts from everything before it, then checks the predictions against the new artists you actually went on to love or skip. Settings are chosen on an earlier window and graded on a later one they never saw.</p>`;
  const runBtn = `<button class="primary" id="run-eval" ${state.job.running || !eligible || state.lookup_available === false ? "disabled" : ""}>${rep && rep.ok ? "Re-run the accuracy test" : "Run the accuracy test"}</button>`;
  const live = liveAccuracy(fb);
  if (!rep || !rep.ok) {
    main.innerHTML = `<div class="view-head"><div><h1>How accurate is it — for you?</h1>${intro}</div>
      <div>${runBtn}<p class="small muted">Takes a few minutes the first time: it maps two past versions of your taste.</p></div></div>
      ${!state.plays ? `<div class="note"><p>The accuracy test replays your listening history, so it needs your Spotify export (see <a href="#setup">Setup</a>). Until that arrives, your Like / Not for me ratings below measure how accurate Sideband is for you.</p></div>`
        : !eligible ? `<div class="note"><p>${esc(state.personalization?.reason || rep?.reason || "More listening history is needed for this test.")} <a href="#setup">Add more history</a></p></div>`
        : rep && rep.reason ? `<div class="note"><p>${esc(rep.reason)}</p></div>` : ""}${live}`;
    jobButton($("#run-eval"), "/api/evaluate");
    return;
  }
  const b = rep.baselines;
  const recallRows = [
    { name: "Sideband", value: rep.model["recall@50"], ci: rep.model["recall@50_ci"], me: true },
    { name: "Similar-artists only", value: b.similar_artists_only["recall@50"] },
    { name: "Most popular first", value: b.popularity["recall@50"] },
    { name: "Random", value: b.random["recall@50"] },
  ];
  const aucRows = [
    { name: "Sideband", value: rep.model.auc, ci: rep.model.auc_ci, me: true },
    { name: "Similar-artists only", value: b.similar_artists_only.auc },
    { name: "Most popular first", value: b.popularity.auc },
    { name: "Random guess", value: 0.5 },
  ];
  const trade = b.exploration_tradeoff || [];
  const gt = rep.ground_truth;
  const w = rep.chosen.weights;
  main.innerHTML = `
    <div class="view-head"><div><h1>How accurate is it — for you?</h1>${intro}</div>
      <div>${runBtn}<p class="small muted">Last run ${esc(new Date(rep.generated).toLocaleString())}. Test window ${esc(rep.windows.test[0])} to ${esc(rep.windows.test[1])}.</p></div></div>
    ${rep.demo ? `<div class="note"><p>These numbers come from the simulated demo listener, not from you.</p></div>` : ""}
    ${rep.enough_data ? "" : `<div class="note"><p>Only ${gt.test_adopted} new artists were adopted in the test window, so these numbers are very uncertain. More history (the Extended streaming history export) helps.</p></div>`}
    ${rep.selection ? `<div class="note"><p><b>${rep.selection.personalised ? "This test accepted personalized settings." : "This test kept default settings."}</b> ${esc(rep.selection.reason || "Settings change only when validation supports an improvement.")}</p></div>` : ""}
    ${state.personalised_model && state.personalization?.model_current === false ? `<div class="note"><p>Your recommendations still use the earlier fitted settings. The results below describe this history test.</p></div>` : ""}
    ${state.personalization?.tested_current === false ? `<div class="note"><p>This report is from earlier listening data. Adding enough new history and using “Improve from my history” checks it again.</p></div>` : ""}
    <div class="summary section">${rep.summary.map((s) => `<p>${esc(s)}</p>`).join("")}</div>
    <div class="section stack">
      <section><h2>Did the top 50 contain them?</h2><p class="lede small">Recall@50 on the held-out window, ${gt.test_adopted} newly loved artists. Line: 95% bootstrap interval.</p>
        ${dotWhisker(recallRows, { label: "Recall at 50 by method" })}</section>
      <section><h2>Loved vs. skipped</h2><p class="lede small">Preference AUC over ${(rep.model.auc_n || [gt.test_adopted, gt.test_rejected])[0]} loved and ${(rep.model.auc_n || [gt.test_adopted, gt.test_rejected])[1]} skipped new artists available to the model. Grey line: guessing.</p>
        ${rep.model.preference_available ? `<p class="small muted">${fmt(rep.model.preference_available[0])} of ${fmt(rep.model.preference_available[1])} heard artists could be graded for preference. Missing discoveries still count as misses in the top-50 test.</p>` : ""}
        ${dotWhisker(aucRows, { chance: 0.5, label: "Preference AUC by method" })}</section>
    </div>
    <section class="section"><h2>All metrics</h2>${metricsTable(rep)}</section>
    <div class="split-even section">
      <section><h2>What changes when you explore</h2><p class="lede small">The same held-out test at different dial settings. Compare measured recall with audience size and genre range.</p>
        <table><thead><tr><th>Dial</th><th class="num">Hits in top 50</th><th class="num">Recall@50</th><th class="num">Typical audience</th><th class="num">Genres</th></tr></thead><tbody>
        ${trade.map((t) => `<tr><td>${t.exploration === 0 ? "Safe bets" : t.exploration === 1 ? "Adventurous" : "Balanced"}</td><td class="num">${t["hits@50"]}</td><td class="num">${pct(t["recall@50"])}</td><td class="num">${compact(t.median_listeners)}</td><td class="num">${t.distinct_genres}</td></tr>`).join("")}
        </tbody></table></section>
      <section><h2>What it learned about you</h2><p class="lede small">Chosen on the validation window (${esc(rep.windows.validation[0])} to ${esc(rep.windows.validation[1])}), then frozen.</p>
        <table><tbody>
          <tr><td>Taste memory half-life</td><td class="num">${rep.chosen.memory_half_life_days ? `${Math.round(rep.chosen.memory_half_life_days)} days` : "no decay"}</td></tr>
          <tr><td>Seed weighting</td><td class="num">affinity<sup>${rep.chosen.seed_power}</sup></td></tr>
          <tr><td>Random-walk restart</td><td class="num">${rep.chosen.restart_probability}</td></tr>
          ${Object.entries(w).map(([k, v]) => `<tr><td>Weight: ${esc(FEATURE_NAMES[k] || k)}</td><td class="num">${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}</td></tr>`).join("")}
        </tbody></table></section>
    </div>
    ${live}
    <section class="section note">
      <h2>Limits worth knowing</h2>
      <p>No recommender can be perfectly accurate: taste depends on mood and context, and these tests can only grade artists you happened to hear. Artists you found through friends, films or radio may not be reachable from similarity data at all (${pct(1 - (rep.model.coverage ?? 1))} of yours weren’t). Similarity data is today’s, so the test window is graded with slightly newer data than you had then. Your own ratings are the real-world check.</p>
      ${rep.limitations?.length ? `<ul>${rep.limitations.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}
    </section>`;
  jobButton($("#run-eval"), "/api/evaluate");
}

function liveAccuracy(fb) {
  const o = fb.overall;
  const songs = fb.song_overall || { rated: 0 };
  const rows = Object.entries(fb.by_exploration || {});
  const songKinds = { similar_song: "Songs like your favourites", new_artist: "From new artists", deep_cut: "Unheard songs by artists you love", song: "Other songs" };
  const songRows = Object.entries(fb.songs_by_kind || {});
  const cal = fb.calibration;
  return `<section class="section"><h2>Live accuracy: your ratings</h2>
    <h3>Artists</h3>
    ${o.rated ? `<p>You liked <b>${o.likes} of ${o.rated}</b> rated artists (${pct(o.like_rate)}; 95% interval ${pct(o.ci95[0])}–${pct(o.ci95[1])}).</p>`
      : `<p class="muted">Rate artists with Like / Not for me to see your artist like rate, with an error bar.</p>`}
    ${rows.length ? `<table><thead><tr><th>Dial setting</th><th class="num">Liked</th><th class="num">Rated</th><th class="num">Like rate (95% interval)</th></tr></thead><tbody>
      ${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v.likes}</td><td class="num">${v.rated}</td><td class="num">${pct(v.like_rate)} (${pct(v.ci95[0])}–${pct(v.ci95[1])})</td></tr>`).join("")}</tbody></table>` : ""}
    <p class="small muted">${cal ? `Score-based “chance you’ll like it” estimates use your ${cal.n} ratings and remain uncertain.` : "With enough varied ratings, Sideband can estimate a chance you’ll like a recommendation. Percentile scores alone are not probabilities."}</p>
    <h3>Songs</h3>
    ${songs.rated ? `<p>You liked <b>${songs.likes} of ${songs.rated}</b> rated songs (${pct(songs.like_rate)}; 95% interval ${pct(songs.ci95[0])}–${pct(songs.ci95[1])}). Song ratings are counted separately from artist ratings.</p>`
      : `<p class="muted">Use Like / Dislike on Songs to see your song like rate separately.</p>`}
    ${songRows.length ? `<table><thead><tr><th>Song list</th><th class="num">Liked</th><th class="num">Rated</th><th class="num">Like rate (95% interval)</th></tr></thead><tbody>
      ${songRows.map(([kind, v]) => `<tr><td>${esc(songKinds[kind] || kind)}</td><td class="num">${v.likes}</td><td class="num">${v.rated}</td><td class="num">${pct(v.like_rate)} (${pct(v.ci95[0])}–${pct(v.ci95[1])})</td></tr>`).join("")}</tbody></table>` : ""}
    <p class="small muted">Already know choices and preview or music-link interest shape recommendations but aren’t counted as likes or dislikes. You choose which music to rate, so these results describe those choices, not every recommendation or a guarantee about the next one. <a href="#taste">Review or undo your saved choices</a>.</p>
  </section>`;
}

// ---------------------------------------------------------------- Setup
const pickRow = (a) => `<li data-name="${esc(a.name)}">
    ${a.image ? `<img src="${esc(a.image)}" alt="" width="44" height="44" loading="lazy">` : `<span class="avatar" aria-hidden="true">${esc(a.name.slice(0, 1))}</span>`}
    <div><div class="pick-name">${esc(a.name)}</div>${a.fans ? `<div class="small muted">${compact(a.fans)} fans</div>` : ""}</div>
    <div class="row"><button data-pick="love" aria-pressed="${a.picked === "love"}" aria-label="Love ${esc(a.name)}">Love</button>
    <button data-pick="dislike" class="quiet" aria-pressed="${a.picked === "dislike"}" aria-label="Not for me: ${esc(a.name)}">Not for me</button></div></li>`;

function pickChips(picks) {
  const chip = (name, verdict) => `<button class="pick-chip ${verdict}" data-unpick="${esc(name)}" aria-label="Remove ${esc(name)}">${esc(name)} <span aria-hidden="true">×</span></button>`;
  return `${picks.loved.length ? `<div class="chips">${picks.loved.map((n) => chip(n, "love")).join("")}</div>` : `<p class="small muted">No favourites picked yet.</p>`}
    ${picks.disliked.length ? `<p class="small muted">Not for you:</p><div class="chips">${picks.disliked.map((n) => chip(n, "dislike")).join("")}</div>` : ""}`;
}

const artistKey = artistIdentity;
function pendingPicks(base = savedPicks || { loved: [], disliked: [] }) {
  const picks = { loved: [...base.loved], disliked: [...base.disliked] };
  for (const { artist, verdict } of pickIntents) {
    picks.loved = picks.loved.filter((name) => artistKey(name) !== artistKey(artist));
    picks.disliked = picks.disliked.filter((name) => artistKey(name) !== artistKey(artist));
    if (verdict === "love") picks.loved.push(artist);
    if (verdict === "dislike") picks.disliked.push(artist);
  }
  return picks;
}

function announcePicks() {
  document.dispatchEvent(new CustomEvent("sideband-picks", { detail: pendingPicks() }));
  updateBuildControls();
}

function saveArtistPick(artist, verdict) {
  const intent = { id: ++pickIntentSeq, artist, verdict };
  pickIntents.push(intent);
  pickSaving++;
  announcePicks();
  const work = async () => {
    try {
      savedPicks = await api("/api/picks", { method: "POST", body: { artist, verdict } });
      // Refresh counts/readiness after the write, without redrawing whichever view is open.
      await refreshState().catch(() => {});
      return savedPicks;
    } finally {
      pickIntents = pickIntents.filter((item) => item.id !== intent.id);
      pickSaving--;
      announcePicks();
    }
  };
  const result = pickQueue.then(work, work);
  pickQueue = result.catch(() => {});
  return result;
}

function artistPickerMarkup() {
  return `<section class="artist-starter" aria-labelledby="artist-heading">
    <div class="artist-picker-head"><div><h2 id="artist-heading">Find artists you love</h2><p class="muted">Search for any artist, or pick favourites below.</p></div><p id="artist-count" class="artist-count" role="status"></p></div>
    <form id="pick-form" class="picker artist-search" role="search" autocomplete="off"><label for="pick-q" class="small">Search artists</label>
      <input id="pick-q" type="search" placeholder="Search any artist" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false" aria-describedby="pick-status"><button type="submit">Search</button></form>
    <ul class="pick-results" id="pick-results"></ul>
    <p class="small muted" id="pick-status" role="status"></p>
    <div class="artist-styles" role="group" aria-label="Browse artists by style"><button type="button" data-style="" aria-pressed="true">All styles</button>${ARTIST_STYLES.map((style) => `<button type="button" data-style="${esc(style.id)}" aria-pressed="false">${esc(style.label)}</button>`).join("")}</div>
    <div id="artist-grid" class="artist-grid" role="group" aria-label="Artists to choose"></div>
    <div class="row artist-browse"><button id="artist-more" type="button">Show more artists</button><p class="small muted" id="artist-browse-hint"></p></div>
    <div class="artist-selected"><h3>Your favourites</h3><div id="pick-chips" tabindex="-1"></div></div>
    <p id="artist-save-status" class="small" role="status"></p>
    <div class="row build-row artist-build"><button class="primary" id="build"></button><a class="button" href="#taste" id="picker-taste" ${state.has_data ? "" : "hidden"}>View my taste</a><span class="small muted" id="build-hint"></span></div>
  </section>`;
}

function updateBuildControls() {
  const btn = $("#build");
  if (!btn) return;
  const ready = canBuild();
  const onlyOpen = state.graph_ready && ["current", "history", "more_history", "taste"].includes(nextRecommendationAction(state));
  btn.disabled = !ready || state.job.running || importing || quickSaving || pickSaving > 0 || (state.lookup_available === false && !onlyOpen);
  btn.textContent = buildLabel();
  const historyButton = $("#prepare-history");
  if (historyButton) {
    historyButton.hidden = !state.plays;
    historyButton.disabled = state.job.running || importing || quickSaving || pickSaving > 0 || (state.lookup_available === false && !onlyOpen);
    historyButton.textContent = buildLabel();
  }
  [$("#clear-data"), $("#clear-fb"), $("#backup-save"), $("#backup-file")].forEach((b) => { if (b) b.disabled = importing || quickSaving || pickSaving > 0; });
  const files = $("#files");
  if (files) files.disabled = importing || quickSaving || pickSaving > 0;
  const drop = $("#drop");
  if (drop) drop.setAttribute("aria-disabled", String(importing || quickSaving || pickSaving > 0));
  document.querySelectorAll("[data-artist-toggle], #pick-chips button, #pick-results button").forEach((button) => { button.disabled = importing || quickSaving; });
  const hint = $("#build-hint");
  if (!hint) return;
  if (state.lookup_available === false) hint.textContent = "Your favourites can be saved here now. Connect the lookup service to find new music.";
  else if (quickSaving || pickSaving) hint.textContent = "Saving your favourites…";
  else if (importing) hint.textContent = "Finish importing first. Your favourite picks are kept.";
  else if (state.job.running) hint.textContent = "Working on it (see the progress bar). Picks you add meanwhile are used when you update next.";
  else if (!ready) hint.textContent = "Tap a few artists you love to get started.";
  else if (!state.plays && (state.input_summary?.positive_artists ?? state.picks.loved) < 3) hint.textContent = "A few more different artists can broaden your taste map, but you can start now.";
  else hint.textContent = state.plays
    ? `Maps your taste and checks the best settings from your history in one step${BROWSER ? "; keep this page open" : ""}. The first run can take several minutes.`
    : `Takes a minute or two${BROWSER ? "; keep this page open" : ""}.`;
  const quickForm = $("#quick-form");
  if (quickForm) quickForm.dispatchEvent(new Event("input-state"));
}

function buildLabel() {
  if (state.plays && nextRecommendationAction(state) === "prepare") return "Improve from my history";
  if (state.graph_exists && !state.graph_ready) return "Update my recommendations";
  if (state.graph_exists) return "Open my recommendations";
  return "Find my music";
}

function quickStarterMarkup() {
  const kind = store("mf.quickKind") === "songs" ? "songs" : "artists";
  const draft = (store("mf.quickDraft") || "").slice(0, 200000);
  return `<section class="quick-starter" aria-labelledby="quick-heading"><h2 id="quick-heading">Add a music list or playlist file</h2>
    <p class="small muted">Already have a list? Paste or upload it here.</p>
    <form id="quick-form">
      <fieldset class="quick-kind"><legend>What are you adding?</legend><label><input type="radio" name="quick-kind" value="artists" ${kind === "artists" ? "checked" : ""}> Favourite artists</label><label><input type="radio" name="quick-kind" value="songs" ${kind === "songs" ? "checked" : ""}> Favourite songs or playlist</label></fieldset>
      <label for="quick-text" id="quick-text-label">${kind === "songs" ? "Artist — Song, one per line" : "Artist names, one per line"}</label>
      <textarea id="quick-text" rows="5" maxlength="200000" spellcheck="false" aria-describedby="quick-help" placeholder="${kind === "songs" ? "Radiohead — Weird Fishes/Arpeggi\nBjörk — Joga" : "Radiohead\nBjörk\nStevie Wonder"}">${esc(draft)}</textarea>
      <p class="small muted" id="quick-help">${kind === "songs" ? "Put the artist first, then a dash and the song title. A playlist CSV or TSV with artist and song columns works too." : "Keep each artist on its own line, including names with commas. Song or playlist files with artist columns work too."} Spotify links alone don’t include names; paste the names instead.</p>
      <div class="row"><button type="submit" class="primary" id="quick-preview">Review my taste</button><button type="button" id="quick-file-button">Choose CSV, TSV or text file</button></div>
      <input id="quick-files" type="file" accept=".csv,.tsv,.txt,text/plain,text/csv,text/tab-separated-values" hidden>
    </form>
    <p id="quick-status" class="small" role="status"></p>
    <div id="quick-review"></div>
    <div class="row" id="quick-save-controls" hidden><button id="quick-use" class="primary" disabled>Use this taste</button><button id="quick-edit" class="quiet">Edit my text</button></div>
    <p id="quick-saved" class="small muted">${state.has_data ? `Saved input: ${esc(basisText())}.` : "Names are added to your saved taste only after you choose “Use this taste”."}</p>
    <a href="#taste" id="quick-taste" ${state.has_data ? "" : "hidden"}>View my saved taste</a>
  </section>`;
}

function bindQuickStarter(chipsBox) {
  const form = $("#quick-form");
  const text = $("#quick-text");
  const status = $("#quick-status");
  const box = $("#quick-review");
  const previewButton = $("#quick-preview");
  const useButton = $("#quick-use");
  const saveControls = $("#quick-save-controls");
  const fileButton = $("#quick-file-button");
  const fileInput = $("#quick-files");
  const kindInputs = [...form.querySelectorAll("input[name=quick-kind]")];
  const kind = () => kindInputs.find((input) => input.checked).value;
  const requests = latestRequest();
  let review = null;
  let filename = "";
  const effectiveKind = () => quickInputKind(kind(), filename);
  let busy = false;
  const update = () => {
    previewButton.disabled = busy || quickSaving || !text.value.trim();
    useButton.disabled = busy || quickSaving || importing || pickSaving > 0 || !quickReviewCurrent(review, text.value, effectiveKind(), filename);
    fileButton.disabled = busy || quickSaving || importing || pickSaving > 0;
  };
  form.addEventListener("input-state", update);
  const invalidate = () => {
    requests.start();
    review = null;
    useButton.disabled = true;
    saveControls.hidden = true;
    box.innerHTML = "";
    status.textContent = "Review your changed text before saving it.";
    store("mf.quickDraft", text.value);
    store("mf.quickKind", kind());
    update();
  };
  text.addEventListener("input", () => { filename = ""; invalidate(); });
  kindInputs.forEach((input) => input.addEventListener("change", () => {
    filename = "";
    invalidate();
    $("#quick-text-label").textContent = kind() === "songs" ? "Artist — Song, one per line" : "Artist names, one per line";
    text.placeholder = kind() === "songs" ? "Radiohead — Weird Fishes/Arpeggi\nBjörk — Joga" : "Radiohead\nBjörk\nStevie Wonder";
    $("#quick-help").textContent = (kind() === "songs"
      ? "Put the artist first, then a dash and the song title. A playlist CSV or TSV with artist and song columns works too."
      : "Keep each artist on its own line, including names with commas. Song or playlist files with artist columns work too.")
      + " Spotify links alone don’t include names; paste the names instead.";
  }));
  const preview = async () => {
    const token = requests.start();
    const snapshot = { text: text.value, kind: effectiveKind(), name: filename };
    busy = true;
    review = null;
    saveControls.hidden = true;
    update();
    status.textContent = "Reading your music list…";
    try {
      const parsed = await api("/api/quick-input", { method: "POST", body: { ...snapshot, preview: true } });
      if (!requests.current(token) || !form.isConnected) return;
      review = { ...snapshot, preview: parsed };
      const items = parsed.items || [];
      const notices = [...(parsed.errors || []), ...(parsed.warnings || [])];
      box.innerHTML = `${notices.length ? `<ul class="quick-notices">${notices.map((note) => `<li>${esc(note)}</li>`).join("")}</ul>` : ""}
        ${items.length ? `<div class="quick-review-list"><table><thead><tr><th scope="col">Artist</th><th scope="col">Song, if provided</th></tr></thead><tbody>${items.map((item) => `<tr><td>${esc(item.artist)}</td><td>${esc(item.track || "—")}</td></tr>`).join("")}</tbody></table></div>` : ""}`;
      saveControls.hidden = !items.length;
      status.textContent = parsed.can_save
        ? `${fmt(items.length)} favourite${items.length === 1 ? "" : "s"} found. Check that artist and song names are in the right columns, then choose “Use this taste”. These names haven’t been added to your saved taste yet.`
        : "This list needs a change before it can be saved. Edit the text and review it again.";
      useButton.textContent = `Use these ${fmt(items.length)} favourite${items.length === 1 ? "" : "s"}`;
    } catch (err) {
      if (requests.current(token) && form.isConnected) {
        box.innerHTML = "";
        status.textContent = `Couldn’t read this list: ${err.message}. Edit it or try another file.`;
      }
    } finally {
      busy = false;
      if (form.isConnected) update();
    }
  };
  form.addEventListener("submit", (event) => { event.preventDefault(); preview(); });
  $("#quick-edit").addEventListener("click", () => { text.focus(); text.scrollIntoView({ block: "center" }); });
  fileButton.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    const readToken = requests.start();
    review = null;
    saveControls.hidden = true;
    box.innerHTML = "";
    update();
    if (file.size > 200000) { status.textContent = "Choose a text or playlist file smaller than 200 KB, or paste up to 500 favourites."; fileInput.value = ""; return; }
    busy = true;
    update();
    status.textContent = "Reading your file…";
    try {
      const contents = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (!requests.current(readToken) || !form.isConnected) return;
      text.value = contents;
      invalidate();
      filename = file.name;
      await preview();
    } catch (err) { if (requests.current(readToken) && form.isConnected) status.textContent = `Couldn’t read this file: ${err.message}. Save the file as UTF-8 text and try again.`; }
    finally { busy = false; fileInput.value = ""; if (form.isConnected) update(); }
  });
  useButton.addEventListener("click", async () => {
    if (quickSaving || importing || pickSaving > 0 || !quickReviewCurrent(review, text.value, effectiveKind(), filename)) return;
    const snapshot = { text: review.text, kind: review.kind, name: review.name };
    quickSaving = true;
    text.disabled = true;
    kindInputs.forEach((input) => { input.disabled = true; });
    update();
    updateBuildControls();
    status.textContent = "Saving your favourites…";
    try {
      const saved = await api("/api/quick-input", { method: "POST", body: { ...snapshot, preview: false } });
      await refreshState();
      if (saved.picks) { savedPicks = saved.picks; announcePicks(); }
      store("mf.quickDraft", "");
      if (!form.isConnected) return;
      const added = saved.added_library_items || 0;
      status.textContent = `${added ? `${fmt(added)} new favourite${added === 1 ? "" : "s"} saved.` : "These favourites are already saved."} ${state.lookup_available === false ? "Your saved taste is ready to view. New music discovery needs the lookup service." : "Choose “Find my music” or “Update my recommendations” to use them."}${saved.removed_disliked_picks ? ` ${fmt(saved.removed_disliked_picks)} previous “Not for me” choice${saved.removed_disliked_picks === 1 ? " was" : "s were"} replaced by these favourites.` : ""}`;
      $("#quick-saved").textContent = `Saved input: ${basisText()}. Your plays and ratings are kept.`;
      $("#quick-taste").hidden = false;
      saveControls.hidden = true;
      review = null;
      text.value = "";
      box.innerHTML = "";
    } catch (err) { if (form.isConnected) status.textContent = `Couldn’t save your list: ${err.message}. Your reviewed list is still here to retry.`; }
    finally {
      quickSaving = false;
      text.disabled = false;
      kindInputs.forEach((input) => { input.disabled = false; });
      if (form.isConnected) update();
      updateBuildControls();
    }
  });
  update();
}

async function viewSetup() {
  const mine = routeSeq;
  const intentAtStart = pickIntentSeq;
  const savedAtStart = savedPicks;
  const picks = await api("/api/picks");
  if (mine !== routeSeq) return;
  // An older read must not undo a save that finished while this view was opening.
  if (!savedPicks || (!pickSaving && intentAtStart === pickIntentSeq && savedAtStart === savedPicks)) savedPicks = picks;
  main.innerHTML = `
    <div class="view-head"><div><h1>Your next favourite starts here.</h1>
      <p>Pick music you know. Discover music you’ll love.</p></div></div>
    ${BROWSER && IOS && !STANDALONE && !state.demo ? `<div class="note"><p><b>On an iPhone, do this first:</b> tap Share → <b>Add to Home Screen</b>, then open Sideband from the new icon and do the steps below there. The Home Screen app keeps its own copy of your data, separate from Safari, and Safari may delete website data after about a week without a visit.</p></div>` : ""}
    ${artistPickerMarkup()}
    <details class="section"><summary>More ways to add music</summary><div class="stack">${quickStarterMarkup()}</div></details>
    <details id="history-details" class="section export-help"><summary>Optional: add existing listening history</summary><div class="stack">
      <div><h2>Add a Spotify export you already have</h2>
        <p>Already have a Spotify export? Choose the ZIP or all its JSON files together. Importing it again adds only new plays, and keeps your picks and ratings.</p>
        <label class="drop" id="drop" for="files"><strong>Drop my_spotify_data.zip, or the JSON files inside it</strong>
          <span class="muted">or ${BROWSER ? "tap" : "click"} to choose files. Everything stays ${WHERE}.</span></label>
        <input id="files" type="file" multiple accept=".zip,.json,application/json,application/zip" hidden>
        <ul class="file-log" id="file-log"></ul>
        <p class="small" id="data-status" role="status">${state.plays ? `${fmt(state.plays)} plays imported.` : "No history imported yet."}</p>
        <div class="row"><button class="primary" id="prepare-history" ${state.plays ? "" : "hidden"}>Improve from my history</button><a href="#accuracy" ${state.plays ? "" : "hidden"} id="history-accuracy">See my accuracy</a></div>
        <p class="small muted">History enables accuracy tests against later listening. Your picked favourites already work.</p></div>
    </div></details>
    ${BROWSER ? `<details class="section"><summary>Where your data lives</summary><div class="stack">
      <p>Your picks, listening history, ratings and learned interest are saved ${WHERE}, not on a server. Other devices start empty${IOS ? ", and on an iPhone the Home Screen app and Safari each keep their own copy" : ""}. Clearing this site’s data in the browser settings deletes it.</p>
      ${state.demo ? `<p><a href="./">Leave the demo</a></p>` : `<p>Curious first? <a href="?demo=1">Try it with a simulated listener</a> (nothing is saved).</p>`}</div></details>` : ""}
    ${!state.demo ? `<details class="section"><summary>Backup and restore</summary><div class="stack">
      <p>Your picks, ratings, preview and music-link interest, and imported listening history stay ${WHERE} when you close the app. Save a backup before changing devices or removing the app.</p>
      <div class="row"><button id="backup-save">Save a backup</button><label class="drop" for="backup-file">Restore a backup</label>
      <input id="backup-file" type="file" accept=".json,application/json" hidden></div></div></details>` : ""}
    <details class="section"><summary>Manage or delete my data</summary>
      <div class="row"><button id="clear-data">Delete my picks and listening data</button><button id="clear-fb">Delete my ratings and learned interest</button></div></details>`;

  const backup = $("#backup-save");
  if (backup) backup.addEventListener("click", async () => {
    try {
      const data = await api("/api/backup");
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
      link.download = 'sideband-backup-' + new Date().toISOString().slice(0, 10) + '.json';
      link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    } catch (error) { toast(error.message, 10000); }
  });
  $("#backup-file")?.addEventListener("change", async event => {
    const file = event.target.files[0]; if (!file) return;
    if (importing || quickSaving || pickSaving) { event.target.value = ""; toast("Finish saving your music before restoring a backup."); return; }
    if (file.size > 128 * 1024 * 1024) { toast('That backup is too large (maximum 128 MB).'); return; }
    if (!confirm('Replace the picks, ratings, learned interest and listening history on this device with this backup? Save a backup of your current data first.')) return;
    try { await api('/api/restore', { method: 'POST', body: file }); location.reload(); }
    catch (error) { toast(error.message, 10000); }
    event.target.value = '';
  });
  updateBuildControls();

  // --- picking
  const results = $("#pick-results");
  const pickStatus = $("#pick-status");
  const chipsBox = $("#pick-chips");
  bindQuickStarter(chipsBox);
  const grid = $("#artist-grid");
  const styleButtons = [...document.querySelectorAll("[data-style]")];
  const moreButton = $("#artist-more");
  const pickerStatus = $("#artist-save-status");
  let chosen = pendingPicks();
  let styles = [];
  let seenNames = [];
  const stillHere = () => mine === routeSeq && grid.isConnected;
  const syncPicks = (now) => {
    if (!stillHere()) return;
    chosen = now;
    const focused = document.activeElement;
    const focusedChip = focused?.closest("#pick-chips button[data-unpick]")?.dataset.unpick;
    const focusIndex = focusedChip ? [...chipsBox.querySelectorAll("button")].indexOf(focused) : -1;
    chipsBox.innerHTML = pickChips(now);
    if (focusedChip) {
      const chips = [...chipsBox.querySelectorAll("button")];
      (chips.find((button) => artistKey(button.dataset.unpick) === artistKey(focusedChip)) || chips[Math.min(focusIndex, chips.length - 1)] || chipsBox).focus();
    }
    const loved = new Set(now.loved.map(artistKey));
    const disliked = new Set(now.disliked.map(artistKey));
    grid.querySelectorAll("button[data-artist-toggle]").forEach((button) => {
      const selected = loved.has(artistKey(button.dataset.artistToggle));
      button.setAttribute("aria-pressed", String(selected));
      button.setAttribute("aria-label", `${selected ? "Remove" : "Pick"} ${button.dataset.artistToggle}${selected ? " from" : " as one of"} my favourites`);
      button.querySelector(".artist-choice-mark").textContent = selected ? "✓ Picked" : "+ Pick";
    });
    results.querySelectorAll("li[data-name]").forEach((item) => {
      item.querySelectorAll("button[data-pick]").forEach((button) => {
        button.setAttribute("aria-pressed", String((button.dataset.pick === "love" ? loved : disliked).has(artistKey(item.dataset.name))));
      });
    });
    $("#artist-count").textContent = `${fmt(now.loved.length)} favourite${now.loved.length === 1 ? "" : "s"} picked`;
    pickerStatus.textContent = pickSaving ? "Saving your choices…" : now.loved.length ? "Saved. You can change your picks anytime." : "";
    $("#picker-taste").hidden = !(now.loved.length || state.has_data);
    const next = artistChoices({ styles, selected: now.loved, excluded: [...now.disliked, ...seenNames], limit: 24 });
    moreButton.textContent = next.length ? "Show more artists" : "Back to first artists";
    moreButton.dataset.restart = String(!next.length);
  };
  const drawGrid = () => {
    // New selections can change the catalog order. Exclude boards already shown
    // rather than offsetting into a newly ranked list and skipping artists.
    const items = artistChoices({ styles, selected: chosen.loved, excluded: [...chosen.disliked, ...seenNames], limit: 24 });
    seenNames.push(...items.map((artist) => artist.name));
    grid.innerHTML = items.length ? items.map((artist) => `<button type="button" class="artist-choice" data-artist-toggle="${esc(artist.name)}" aria-pressed="false"><span class="artist-choice-name">${esc(artist.name)}</span><span class="artist-choice-mark" aria-hidden="true">+ Pick</span></button>`).join("") : `<p class="muted">You’ve reached the end of this selection. Try another style.</p>`;
    $("#artist-browse-hint").textContent = styles.length ? `Browsing ${ARTIST_STYLES.find((style) => style.id === styles[0]).label.toLowerCase()}.` : "Any style counts. Pick what you enjoy.";
    syncPicks(chosen);
    updateBuildControls();
  };
  setupPickListener = (event) => syncPicks(event.detail);
  document.addEventListener("sideband-picks", setupPickListener);
  drawGrid();
  styleButtons.forEach((button) => button.addEventListener("click", () => {
    styles = button.dataset.style ? [button.dataset.style] : [];
    seenNames = [];
    styleButtons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    drawGrid();
  }));
  moreButton.addEventListener("click", () => {
    if (moreButton.dataset.restart === "true") seenNames = [];
    drawGrid();
    grid.querySelector("button")?.focus();
  });
  grid.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-artist-toggle]");
    if (!button || importing || quickSaving) return;
    const name = button.dataset.artistToggle;
    const verdict = chosen.loved.some((artist) => artistKey(artist) === artistKey(name)) ? "remove" : "love";
    saveArtistPick(name, verdict).catch((error) => {
      if (stillHere()) pickerStatus.textContent = `Couldn’t save ${name}: ${error.message}. Tap again to retry.`;
    });
  });
  const say = (text) => { if (stillHere()) pickStatus.textContent = text; };
  let seq = 0;
  let timer;
  const search = async (q) => {
    const mine = ++seq;
    if (!stillHere()) return;
    if (!q) { results.innerHTML = ""; say(""); return; }
    if (state.lookup_available === false) {
      results.innerHTML = `<li class="muted">Artist search needs a connected lookup service. The artist buttons above work now.</li>`;
      say("Artist search is unavailable until the lookup service connects.");
      return;
    }
    results.innerHTML = `<li class="loading">Searching…</li>`;
    try {
      const res = await api(`/api/search/artists?q=${enc(q)}`);
      if (mine !== seq || !stillHere()) return; // a newer search or view is on its way
      results.innerHTML = res.items.length ? res.items.map(pickRow).join("")
        : `<li class="muted">No artist called “${esc(q)}” found. Check the spelling?</li>`;
      syncPicks(chosen);
      say(res.items.length ? `${res.items.length} artist${res.items.length === 1 ? "" : "s"} found.` : "No artist found.");
    } catch (err) {
      if (mine !== seq || !stillHere()) return;
      results.innerHTML = `<li class="error">${esc(err.message)}</li>`;
      say(err.message);
    }
  };
  const input = $("#pick-q");
  input.addEventListener("input", () => { seq++; clearTimeout(timer); timer = setTimeout(() => search(input.value.trim()), 350); });
  $("#pick-form").addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(timer); search(input.value.trim()); });

  results.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-pick]");
    if (!btn || importing || quickSaving) return;
    const li = btn.closest("li[data-name]");
    const name = li.dataset.name;
    const verdict = btn.getAttribute("aria-pressed") === "true" ? "remove" : btn.dataset.pick;
    try {
      await saveArtistPick(name, verdict);
      if (!stillHere()) return;
      say(verdict === "love" ? `${name} added to your favourites.` : verdict === "dislike" ? `${name} marked as not for you.` : `${name} removed.`);
    } catch (err) { if (stillHere()) say(err.message); }
  });
  $("#pick-chips").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-unpick]");
    if (!btn || importing || quickSaving) return;
    const name = btn.dataset.unpick;
    try {
      await saveArtistPick(name, "remove");
      if (!stillHere()) return;
      say(`${name} removed.`);
    } catch (err) { if (stillHere()) pickerStatus.textContent = `Couldn’t remove ${name}: ${err.message}. Try again.`; }
  });
  const openRecommendations = () => {
    if (location.hash === "#for-you") route();
    else location.hash = "#for-you";
  };
  jobButton($("#build"), "/api/prepare", openRecommendations);
  jobButton($("#prepare-history"), "/api/prepare", openRecommendations);

  // --- importing Spotify history
  const log = $("#file-log");
  const drop = $("#drop");
  const filesInput = $("#files");
  const dataStatus = $("#data-status");
  const upload = async (files) => {
    if (!files.length) return;
    if (importing || quickSaving || pickSaving) { toast("Music is already being saved. Choose these files again when it finishes."); return; }
    importing = true;
    filesInput.disabled = true;
    drop.setAttribute("aria-disabled", "true");
    updateBuildControls();
    let added = 0;
    let failures = 0;
    try {
      for (const [index, f] of files.entries()) {
        const li = document.createElement("li");
        li.textContent = `Importing ${index + 1} of ${files.length}: ${f.name}…`;
        log.append(li);
        if (dataStatus.isConnected) dataStatus.textContent = `Importing file ${index + 1} of ${files.length}. You can leave this view; keep Sideband open until it finishes.`;
        try {
          const r = await api("/api/import", { method: "POST", body: f, headers: { "X-Filename": enc(f.name) } });
          const lib = Object.values(r.library || {}).reduce((a, b) => a + b, 0);
          added += r.new_plays_added || 0;
          li.textContent = r.plays || lib
            ? `${f.name}: ${fmt(r.plays)} plays (${fmt(r.new_plays_added)} new)${lib ? `, ${fmt(lib)} library items` : ""}.`
            : `${f.name}: no listening data found (${(r.files_ignored || []).length} files ignored).`;
        } catch (err) {
          failures++;
          li.innerHTML = `<span class="error">${esc(f.name)}: ${esc(err.message)}. You can choose this file again to retry.</span>`;
        }
      }
      await refreshState();
      savedPicks = await api("/api/picks");
      announcePicks();
      const nextImportStep = state.lookup_available === false
        ? "Your taste profile is ready. Connect the lookup service to find new music."
        : state.personalization?.can_evaluate
          ? "Use “Improve from my history” to map and test your taste in one step."
          : "Find my music uses these plays now; more history is needed to test personal settings.";
      if (dataStatus.isConnected) dataStatus.textContent = state.plays
        ? `${fmt(state.plays)} plays saved (${fmt(added)} added now). ${failures ? `${failures} file${failures === 1 ? " needs" : "s need"} a retry. ` : ""}${nextImportStep}`
        : "No history imported yet. Choose a Spotify history ZIP or JSON file to try again.";
      const accuracy = $("#history-accuracy");
      if (accuracy) accuracy.hidden = !state.plays;
      toast(failures ? `Import finished with ${failures} file${failures === 1 ? "" : "s"} to retry.` : `${fmt(added)} new plays added. Your picks and ratings are kept.`);
    } finally {
      importing = false;
      filesInput.disabled = false;
      filesInput.value = ""; // selecting the same file again must fire change after an error
      drop.setAttribute("aria-disabled", "false");
      updateBuildControls();
    }
  };
  filesInput.addEventListener("change", (e) => upload([...e.target.files]).catch((err) => toast(`Couldn’t finish importing: ${err.message}`, 7000)));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); upload([...e.dataTransfer.files]).catch((err) => toast(err.message)); });
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#files").click(); } });
  drop.tabIndex = 0;
  $("#clear-data").addEventListener("click", async () => {
    if (!confirm("Delete your picked artists, imported listening data and learned interest from previews and music links? (Your Spotify account is not affected.)")) return;
    await api("/api/clear", { method: "POST", body: { what: "data" } });
    previewSession = null;
    store("mf.quickDraft", "");
    toast("Picks, listening data and learned interest deleted.");
    route();
  });
  $("#clear-fb").addEventListener("click", async () => {
    if (!confirm("Delete all your song and artist ratings, plus learned interest from previews and music links?")) return;
    await api("/api/clear", { method: "POST", body: { what: "feedback" } });
    previewSession = null;
    feedbackChoices.clear();
    toast("Ratings and learned interest deleted.");
    await refreshState();
    updateBuildControls();
  });
}

if (BROWSER) {
  const footer = document.querySelector("footer");
  if (footer) footer.textContent = "Sideband runs inside your browser. Your picks and listening data stay on this device; only artist and song names pass through this site’s relay to public music services (Deezer, ListenBrainz, MusicBrainz, and Last.fm if this site has it set up).";
}
route();
