// Sideband single-page UI. Plain ES module, no build step.
import { explorationChoice, batchChoice, nextRecommendationAction, latestRequest } from "./ui-state.js";

const $ = (sel, root = document) => root.querySelector(sel);
const main = $("#main");
// The hosted  build runs the engine inside the browser instead of talking to a local server.
const BROWSER = window.MUSICFINDER_MODE === "browser";
const engine = BROWSER ? await import("./browser-api.js") : null;
const WHERE = BROWSER ? "in this browser on this device" : "on this computer";
// iPhone/iPad: a Home Screen web app keeps its own storage, separate from Safari's.
const IOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const STANDALONE = (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
const player = $("#player");
let state = null;
let importing = false;

const FEATURE_NAMES = {
  cf: "Similar to artists you play a lot",
  cf_recent: "Similar to what you play lately",
  ppr: "Central to your taste network",
  support: "Linked from many of your artists",
  tag: "Matches your genre profile",
  pop: "Popularity",
  neg: "Similar to artists you skip",
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
  const canOpen = () => path === "/api/prepare" && state.graph_ready && ["current", "history", "more_history"].includes(nextRecommendationAction(state));
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

async function route() {
  const mine = ++routeSeq;
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
  if (!canBuild() && !state.graph_exists && name !== "setup") name = "setup";
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

function basisText() {
  const n = state.picks ? state.picks.loved : 0;
  const parts = [];
  if (state.plays) parts.push(`${fmt(state.plays)} plays analysed`);
  if (n) parts.push(`${n} artist${n === 1 ? "" : "s"} you picked`);
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
  const because = r.because?.length ? `Because you play ${listJoin(r.because.slice(0, 3).map((n) => `<b>${esc(n)}</b>`))}` : "Reached through your wider taste network";
  const shared = r.shared_tags?.length ? `; shares ${listJoin(r.shared_tags.map(esc))} with your listening.` : ".";
  const prob = r.like_probability != null
    ? `<div class="prob" title="An estimate fitted to your own ratings; not independently validated">≈${Math.round(r.like_probability * 100)}% provisional like estimate</div>` : "";
  const truth = r.true_like_probability != null
    ? `<span class="truth-chip">Simulation’s true like-probability: ${Math.round(r.true_like_probability * 100)}%</span>` : "";
  const ctx = { ...(r.context || {}), ...extraCtx };
  const listeners = r.popularity ? ` · ${compact(r.popularity)} listeners` : "";
  return `<li class="rec" data-artist="${esc(r.name)}" data-ctx="${esc(JSON.stringify(ctx))}">
    <div class="rec-rank">${String(i + 1).padStart(2, "0")}</div>
    <div>
      <h3 class="rec-name">${esc(r.name)}</h3>
      <div class="rec-tags">${tags || "no genre tags"}${listeners}</div>
      <p class="rec-why">${because}${shared}</p>
      ${meter(r, scale)}
      ${truth}
      <div class="rec-actions">
        <button data-act="play" data-label="Play a preview" aria-label="Play a preview of ${esc(r.name)}">Play a preview</button>
        <a class="button" href="${spotifyUrl(r.name)}" target="_blank" rel="noopener">Open in Spotify ↗</a>
        <button data-act="like" aria-label="Like ${esc(r.name)}" aria-pressed="false">Like</button>
        <button data-act="dislike" aria-label="Not for me: ${esc(r.name)}" aria-pressed="false">Not for me</button>
        <button data-act="known" class="quiet" aria-label="Already know ${esc(r.name)}" aria-pressed="false">Already know them</button>
      </div>
      <div class="rec-state" role="status"><span></span> <button data-act="undo" class="quiet" hidden aria-label="Undo rating for ${esc(r.name)}">Undo</button></div>
    </div>
    <div class="rec-side">
      <div class="sticker" title="Scores higher than ${Math.floor(r.match)}% of the unfamiliar artists considered; this is not a probability" data-tip="Scores higher than ${Math.floor(r.match)}% of the unfamiliar artists considered; this is not a probability"><b>${Math.floor(r.match)}</b><span>percentile</span></div>
      ${prob}
    </div>
  </li>`;
}

// ---------------------------------------------------------------- shared actions
main.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const row = btn.closest("[data-artist]");
  const act = btn.dataset.act;
  if (act === "play") return playPreview(btn, row.dataset.artist, row.dataset.track);
  if (act === "tag") return exploreTag(btn.dataset.tag);
  if (!["like", "dislike", "known", "undo"].includes(act) || !row || row.dataset.saving) return;
  const ctx = JSON.parse(row.dataset.ctx || "{}");
  const buttons = row.querySelectorAll("button[data-act=like],button[data-act=dislike],button[data-act=known],button[data-act=undo]");
  const message = row.querySelector(".rec-state span");
  const previousMessage = message.textContent;
  message.textContent = act === "undo" ? "Removing your rating…" : "Saving your rating…";
  row.dataset.saving = "1";
  buttons.forEach((b) => { b.disabled = true; });
  try {
    const stats = await api("/api/feedback", { method: "POST", body: { artist: row.dataset.artist, verdict: act === "undo" ? "clear" : act, context: ctx } });
    row.querySelectorAll("button[data-act=like],button[data-act=dislike],button[data-act=known]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    const msg = {
      like: "Saved. This artist now counts as part of your taste and pulls similar music up.",
      dislike: "Saved. Similar artists will be pushed down; this one won’t be shown again.",
      known: "Noted. It won’t be recommended again (no effect on your taste).",
      undo: "Rating removed. This artist can appear in your recommendations again.",
    }[act];
    const o = stats.overall;
    row.querySelector(".rec-state span").textContent = `${msg} You’ve liked ${o.likes} of ${o.rated} rated picks so far.`;
    row.querySelector("button[data-act=undo]").hidden = act === "undo";
    row.classList.toggle("rated", act !== "undo");
    const refresh = $("#refresh-recs");
    if (refresh) refresh.textContent = act === "undo" ? "Refresh my list" : "Apply ratings to my list";
  } catch (err) {
    message.textContent = previousMessage;
    toast(`Couldn’t save that: ${err.message}`);
  } finally {
    delete row.dataset.saving;
    buttons.forEach((b) => { b.disabled = false; });
  }
});

let playingBtn = null;
function resetPlayButton() {
  if (!playingBtn) return;
  playingBtn.textContent = playingBtn.dataset.label || "Play";
  playingBtn.removeAttribute("aria-pressed");
  playingBtn = null;
}
player.addEventListener("ended", resetPlayButton);
player.addEventListener("pause", resetPlayButton);

async function playPreview(btn, artist, track) {
  if (playingBtn === btn && !player.paused) { player.pause(); return; }
  player.pause();
  btn.disabled = true;
  btn.textContent = "Finding a preview…";
  try {
    let info = null;
    const titles = track ? [track] : (await api(`/api/artist/tracks?name=${enc(artist)}&n=4`)).items.map((t) => t.title);
    for (const t of titles) {
      info = await api(`/api/preview?artist=${enc(artist)}&track=${enc(t)}`);
      if (info && info.preview_url) break;
    }
    if (!info || !info.preview_url) {
      btn.textContent = "No preview — try Spotify";
      return;
    }
    player.src = info.preview_url;
    await player.play();
    playingBtn = btn;
    btn.textContent = `Pause · “${info.title}”`;
    btn.setAttribute("aria-pressed", "true");
  } catch (err) {
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
    more_history: "More history can sharpen personal settings",
    prepare: state.plays ? "Get more from your listening history" : "Update your music map",
    current: p.model_current ? "Your history is shaping these picks" : "Your history has been checked",
  }[next];
  const reason = p.reason || (state.plays
    ? "Check which settings predict your later listening best, then use a fitted model when the evidence supports it."
    : "Import a Spotify export to learn from your plays, listening dates and any recorded skips. Your favourite picks are kept.");
  const range = p.first && p.last ? ` · ${esc(p.first)} to ${esc(p.last)}` : "";
  const details = state.plays ? `${fmt(state.plays)} plays${range}${p.has_skip_data === false ? " · no skip information" : ""}` : basisText();
  const action = next === "prepare" ? `<button id="prepare-for-you" class="primary">${state.plays ? "Improve from my history" : "Update my recommendations"}</button>`
    : next === "history" ? `<a class="button" href="#setup">Add my history</a>`
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
      <p class="small muted" id="list-status" role="status">Rate a few after listening, then refresh. Ratings change the ranking immediately.</p>
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
    refresh.disabled = true;
    box.setAttribute("aria-busy", "true");
    status.textContent = "Updating your list…";
    try {
      const data = await api(`/api/recommendations?n=${batchSize}&exploration=${exploration}`);
      if (mine !== routeSeq || !requests.current(token) || !box.isConnected) return;
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
  return `<li class="song" data-artist="${esc(s.artist)}" data-track="${esc(s.title)}">
    <div><div class="song-title">${esc(s.title)} <span class="muted">— ${esc(s.artist)}</span></div>
    <div class="song-why">${esc(s.because)}</div></div>
    <div class="row"><button data-act="play" data-label="Play">Play</button>
    <a class="button" href="${spotifyUrl(s.artist, s.title)}" target="_blank" rel="noopener">Spotify ↗</a></div>
  </li>`;
}

async function viewSongs() {
  if (needsGraph()) return;
  const mine = routeSeq;
  main.innerHTML = `
    <div class="view-head"><div><h1>Songs to try</h1>
    <p>Three kinds of picks, kept apart so you always know why a song is here.</p></div></div>
    <p class="loading" id="songs-loading">Looking up songs… the first time this needs a few dozen lookups (about 20 seconds).</p>
    <div id="songs"></div>`;
  const data = await api(`/api/songs?exploration=${exploration}`);
  if (mine !== routeSeq) return;
  const block = (title, lede, items) => `<section class="section"><h2>${title}</h2><p class="lede">${lede}</p>
    ${items.length ? `<ol class="songs">${items.map(songRow).join("")}</ol>` : `<p class="muted">Nothing found for this list yet.</p>`}</section>`;
  $("#songs-loading").remove();
  $("#songs").innerHTML =
    block("Songs like your favourites", "Songs that go with the ones you love most, from listening data and artist radio, weighted by how much you love each.", data.similar_song)
    + block("From new artists", "The most-played song of each of your top new-artist matches — the usual way in.", data.new_artist)
    + block("Unheard songs by artists you love", "Popular songs by your favourite artists that you have never played.", data.deep_cut);
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
async function viewTaste() {
  const mine = routeSeq;
  const p = await api("/api/profile");
  if (mine !== routeSeq) return;
  const genres = p.genres ? `<section><h2>Genres</h2>${bars(p.genres.slice(0, 12).map((g) => ({ label: g.tag, value: g.share, text: pct(g.share) })))}</section>` : "";
  if (!p.plays) {
    // Only picked artists so far: nothing to measure yet.
    main.innerHTML = `
      <div class="view-head"><div><h1>Your taste so far</h1>
      <p>Based on the ${fmt(p.picks.loved.length)} artists you picked. Import your Spotify history in <a href="#setup">Setup</a> to see how you actually listen: hours, skips, what’s rising and fading.</p></div></div>
      <div class="split section">
        <section><h2>Artists you love</h2><ol class="songs">${p.picks.loved.map((n) => `<li class="song"><div class="song-title">${esc(n)}</div></li>`).join("")}</ol>
          ${p.picks.disliked.length ? `<p class="small muted">Not for you: ${esc(p.picks.disliked.join(", "))}</p>` : ""}</section>
        <aside class="stack">${genres || `<p class="muted small">Genres appear once your music map is built.</p>`}</aside>
      </div>`;
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
    </div>`;
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
  const [rep, fb] = await Promise.all([api("/api/evaluation"), api("/api/feedback")]);
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
  const rows = Object.entries(fb.by_exploration || {});
  const cal = fb.calibration;
  return `<section class="section"><h2>Live accuracy: your ratings</h2>
    ${o.rated ? `<p>You liked <b>${o.likes} of ${o.rated}</b> rated recommendations (${pct(o.like_rate)}; 95% interval ${pct(o.ci95[0])}–${pct(o.ci95[1])}).</p>`
      : `<p class="muted">Rate recommendations with Like / Not for me to see your like rate among the artists you rated, with an error bar.</p>`}
    ${rows.length ? `<table><thead><tr><th>Dial setting</th><th class="num">Liked</th><th class="num">Rated</th><th class="num">Like rate (95% interval)</th></tr></thead><tbody>
      ${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v.likes}</td><td class="num">${v.rated}</td><td class="num">${pct(v.like_rate)} (${pct(v.ci95[0])}–${pct(v.ci95[1])})</td></tr>`).join("")}</tbody></table>` : ""}
    <p class="small muted">${cal ? `Score-based “chance you’ll like it” estimates use your ${cal.n} ratings and remain uncertain.` : "With enough varied ratings, Sideband can estimate a chance you’ll like a recommendation. Percentile scores alone are not probabilities."}</p>
    <p class="small muted">You choose which artists to rate, so these results describe those artists. They are not an unbiased measure of every recommendation or a guarantee about the next one.</p>
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

function updateBuildControls() {
  const btn = $("#build");
  if (!btn) return;
  const ready = canBuild();
  const onlyOpen = state.graph_ready && ["current", "history", "more_history"].includes(nextRecommendationAction(state));
  btn.disabled = !ready || state.job.running || importing || (state.lookup_available === false && !onlyOpen);
  btn.textContent = buildLabel();
  const historyButton = $("#prepare-history");
  if (historyButton) {
    historyButton.hidden = !state.plays;
    historyButton.disabled = state.job.running || importing || (state.lookup_available === false && !onlyOpen);
    historyButton.textContent = buildLabel();
  }
  [$("#clear-data"), $("#clear-fb")].forEach((b) => { if (b) b.disabled = importing; });
  const files = $("#files");
  if (files) files.disabled = importing;
  const drop = $("#drop");
  if (drop) drop.setAttribute("aria-disabled", String(importing));
  const hint = $("#build-hint");
  if (!hint) return;
  if (state.lookup_available === false) hint.textContent = "History imports are available. Connect the lookup service to find new music.";
  else if (importing) hint.textContent = "Finish importing first. Your favourite picks are kept.";
  else if (state.job.running) hint.textContent = "Working on it (see the progress bar). Picks you add meanwhile are used when you update next.";
  else if (!ready) hint.textContent = "Pick at least one artist first.";
  else if (!state.plays && state.picks.loved < 3) hint.textContent = "A few more picks will sharpen it, but you can start now.";
  else hint.textContent = state.plays
    ? `Maps your taste and checks the best settings from your history in one step${BROWSER ? "; keep this page open" : ""}. The first run can take several minutes.`
    : `Takes a minute or two${BROWSER ? "; keep this page open" : ""}.`;
}

function buildLabel() {
  if (state.plays && nextRecommendationAction(state) === "prepare") return "Improve from my history";
  if (state.graph_exists && !state.graph_ready) return "Update my recommendations";
  if (state.graph_exists) return "Open my recommendations";
  return "Find my music";
}

async function viewSetup() {
  const mine = routeSeq;
  const picks = await api("/api/picks");
  if (mine !== routeSeq) return;
  main.innerHTML = `
    <div class="view-head"><div><h1>Find the music you’ll love — and see why.</h1>
      <p>Use your Spotify history for recommendations that reflect how you actually listen. One button maps your taste, tests it against later listening and fits settings when the evidence is reliable. You can also start with favourite artists while you wait for an export.</p></div></div>
    ${BROWSER && IOS && !STANDALONE && !state.demo ? `<div class="note"><p><b>On an iPhone, do this first:</b> tap Share → <b>Add to Home Screen</b>, then open Sideband from the new icon and do the steps below there. The Home Screen app keeps its own copy of your data, separate from Safari, and Safari may delete website data after about a week without a visit.</p></div>` : ""}
    <ol class="steps">
      <li><div><h2>Add your listening history</h2>
        <p>Already have a Spotify export? Choose the ZIP or all its JSON files together. Importing it again adds only new plays, and keeps your picks and ratings.</p>
        <label class="drop" id="drop" for="files"><strong>Drop my_spotify_data.zip, or the JSON files inside it</strong>
          <span class="muted">or ${BROWSER ? "tap" : "click"} to choose files. Everything stays ${WHERE}.</span></label>
        <input id="files" type="file" multiple accept=".zip,.json,application/json,application/zip" hidden>
        <ul class="file-log" id="file-log"></ul>
        <p class="small" id="data-status" role="status">${state.plays ? `${fmt(state.plays)} plays imported.` : "No history imported yet."}</p>
        <div class="row"><button class="primary" id="prepare-history" ${state.plays ? "" : "hidden"}>Improve from my history</button><a href="#accuracy" ${state.plays ? "" : "hidden"} id="history-accuracy">See my accuracy</a></div>
        <details class="export-help"><summary>How to get a Spotify export</summary><p>Request <b>Extended streaming history</b> in Spotify’s <a href="https://www.spotify.com/account/privacy/" target="_blank" rel="noopener">privacy settings</a>. It includes listening dates and recorded skips. The faster <b>Account data</b> package works too; it has no skip information. You can import both, including saved songs, followed artists, playlists and hidden songs. While you wait for it, start with favourites below.</p></details></div></li>
      <li><div><h2>Pick artists you love</h2>
        <p>No export yet? Pick a few favourites across the kinds of music you like and start now. With history, use picks to highlight favourites it missed. Mark artists you don’t enjoy to steer away from their sound.</p>
        <form id="pick-form" class="picker" role="search" autocomplete="off"><label for="pick-q" class="small">Artist</label>
          <input id="pick-q" type="search" placeholder="Start typing an artist’s name" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false"></form>
        <ul class="pick-results" id="pick-results"></ul>
        <p class="small muted" id="pick-status" role="status"></p>
        <div id="pick-chips" tabindex="-1">${pickChips(picks)}</div>
        <div class="row build-row"><button class="primary" id="build"></button>
          <span class="small muted" id="build-hint"></span></div></div></li>
    </ol>
    ${BROWSER ? `<section class="section note"><h2>Where your data lives</h2>
      <p>Your picks, listening history and ratings are saved ${WHERE}, not on a server. Other devices start empty${IOS ? ", and on an iPhone the Home Screen app and Safari each keep their own copy" : ""}. Clearing this site’s data in the browser settings deletes it.</p>
      ${state.demo ? `<p><a href="./">Leave the demo</a></p>` : `<p>Curious first? <a href="?demo=1">Try it with a simulated listener</a> (nothing is saved).</p>`}</section>` : ""}
    <details class="section"><summary>Manage or delete my data</summary>
      <div class="row"><button id="clear-data">Delete my picks and listening data</button><button id="clear-fb">Delete my ratings</button></div></details>`;

  updateBuildControls();

  // --- picking
  const results = $("#pick-results");
  const pickStatus = $("#pick-status");
  const chipsBox = $("#pick-chips");
  const say = (text) => { if (pickStatus.isConnected) pickStatus.textContent = text; };
  let seq = 0;
  let timer;
  const search = async (q) => {
    const mine = ++seq;
    if (!results.isConnected) return;
    if (!q) { results.innerHTML = ""; say(""); return; }
    if (state.lookup_available === false) {
      results.innerHTML = `<li class="muted">Artist search needs a connected lookup service. You can import history above and view your saved taste now.</li>`;
      say("Artist search is unavailable until the lookup service connects.");
      return;
    }
    results.innerHTML = `<li class="loading">Searching…</li>`;
    try {
      const res = await api(`/api/search/artists?q=${enc(q)}`);
      if (mine !== seq || !results.isConnected) return; // a newer search or view is on its way
      results.innerHTML = res.items.length ? res.items.map(pickRow).join("")
        : `<li class="muted">No artist called “${esc(q)}” found. Check the spelling?</li>`;
      say(res.items.length ? `${res.items.length} artist${res.items.length === 1 ? "" : "s"} found.` : "No artist found.");
    } catch (err) {
      if (mine !== seq || !results.isConnected) return;
      results.innerHTML = `<li class="error">${esc(err.message)}</li>`;
      say(err.message);
    }
  };
  const input = $("#pick-q");
  input.addEventListener("input", () => { seq++; clearTimeout(timer); timer = setTimeout(() => search(input.value.trim()), 350); });
  $("#pick-form").addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(timer); search(input.value.trim()); });

  const afterPick = async (now) => {
    if (chipsBox.isConnected) chipsBox.innerHTML = pickChips(now);
    await refreshState();
    if (chipsBox.isConnected) updateBuildControls();
  };
  results.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-pick]");
    if (!btn) return;
    const li = btn.closest("li[data-name]");
    if (li.dataset.saving) return;
    li.dataset.saving = "1";
    const buttons = li.querySelectorAll("button[data-pick]");
    buttons.forEach((b) => { b.disabled = true; });
    const name = li.dataset.name;
    const verdict = btn.getAttribute("aria-pressed") === "true" ? "remove" : btn.dataset.pick;
    try {
      const now = await api("/api/picks", { method: "POST", body: { artist: name, verdict } });
      li.querySelectorAll("button[data-pick]").forEach((b) => b.setAttribute("aria-pressed", String(verdict !== "remove" && b === btn)));
      await afterPick(now);
      say(verdict === "love" ? `${name} added to your favourites.` : verdict === "dislike" ? `${name} marked as not for you.` : `${name} removed.`);
    } catch (err) { toast(err.message); }
    finally { delete li.dataset.saving; buttons.forEach((b) => { b.disabled = false; }); }
  });
  $("#pick-chips").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-unpick]");
    if (!btn) return;
    const name = btn.dataset.unpick;
    const index = [...chipsBox.querySelectorAll(".pick-chip")].indexOf(btn);
    try {
      const now = await api("/api/picks", { method: "POST", body: { artist: name, verdict: "remove" } });
      results.querySelectorAll("li[data-name]").forEach((li) => {
        if (li.dataset.name === name) li.querySelectorAll("button[data-pick]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      });
      await afterPick(now);
      if (!chipsBox.isConnected) return;
      // keep keyboard focus nearby rather than losing it with the removed chip
      const chips = chipsBox.querySelectorAll(".pick-chip");
      (chips[Math.min(index, chips.length - 1)] || chipsBox).focus();
      say(`${name} removed.`);
    } catch (err) { toast(err.message); }
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
    if (importing) { toast("An import is already running. Choose these files again when it finishes."); return; }
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
    if (!confirm("Delete your picked artists and all imported listening data from Sideband? (Your Spotify account is not affected.)")) return;
    await api("/api/clear", { method: "POST", body: { what: "data" } });
    toast("Picks and listening data deleted.");
    route();
  });
  $("#clear-fb").addEventListener("click", async () => {
    if (!confirm("Delete all your Like / Not for me ratings?")) return;
    await api("/api/clear", { method: "POST", body: { what: "feedback" } });
    toast("Ratings deleted.");
    await refreshState();
    updateBuildControls();
  });
}

if (BROWSER) {
  const footer = document.querySelector("footer");
  if (footer) footer.textContent = "Sideband runs inside your browser. Your picks and listening data stay on this device; only artist and song names pass through this site’s relay to public music services (Deezer, ListenBrainz, MusicBrainz, and Last.fm if this site has it set up).";
}
route();
