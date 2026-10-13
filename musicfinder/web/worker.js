// musicfinder browser engine: runs the Python app under Pyodide inside this Web Worker.
// The page sends API requests here (see browser-api.js); answers come back as messages.

const params = new URL(self.location.href).searchParams;
const DEMO = params.get("demo") === "1";
const VERSION = params.get("v") || "dev";
const BASE = new URL("../", import.meta.url);
const RELAY = params.get("relay") || new URL("api/proxy", BASE).href;
const PYODIDE = params.get("pyodide") || new URL("../pyodide/", import.meta.url).href;

// Requests per second per service: the same limits the desktop version uses.
const RATES = {
  "ws.audioscrobbler.com": 5,
  "api.deezer.com": 8,
  "musicbrainz.org": 1,
  "labs.api.listenbrainz.org": 2,
  "api.listenbrainz.org": 2,
};
const MAX_PARALLEL = 6;

let py = null;
let backend = null;
const post = (msg) => self.postMessage(msg);

// ---------------------------------------------------------------- persistence (IndexedDB-backed folder)
// The SQLite files live in memory and are copied to IndexedDB by FS.syncfs, a whole file at a time. Two
// open copies of the app (two tabs, or an installed app plus a browser tab) would each overwrite the
// other's saves, so exactly one copy owns the data at a time: it holds a Web Lock, and a newly opened
// copy asks it (BroadcastChannel) to save and step aside before reading the data.
const LOCK = "musicfinder-data";
let dirty = false;
let saving = null;
let lastWrites = 0;
let owner = false; // holds the lock
let lost = false; // another copy took over: never save again
let releaseLock = null;

function syncfs(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (err) => (err ? reject(err) : resolve())));
}

function noteWrites() {
  if (!backend) return;
  const w = backend.writes();
  if (w !== lastWrites) { lastWrites = w; dirty = true; }
}

async function save() {
  if (DEMO || !py || lost) return;
  while (saving) await saving; // a save already running may have missed the latest changes: run again
  noteWrites();
  if (!dirty || lost) return;
  dirty = false;
  saving = syncfs(false)
    .catch((err) => { dirty = true; console.warn("musicfinder: could not save", err); })
    .finally(() => { saving = null; });
  return saving;
}
setInterval(save, 20_000);

function stepAside() {
  lost = true;
  owner = false;
  post({ type: "lost" });
}

const channel = DEMO || typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(LOCK);
if (channel) {
  channel.onmessage = async (event) => {
    if ((event.data || {}).type !== "handover" || !owner || lost) return;
    await save(); // write everything this copy has before the new one reads it
    const release = releaseLock;
    stepAside();
    if (release) release();
  };
}

async function becomeOwner() {
  if (DEMO || !(self.navigator && navigator.locks)) return; // no Web Locks (very old browser): best effort
  let granted;
  const got = new Promise((resolve) => { granted = resolve; });
  const hold = () => new Promise((release) => { owner = true; releaseLock = release; granted(); });
  const onRejected = () => { if (owner) stepAside(); }; // our lock was stolen by a newer copy
  const queued = new AbortController();
  navigator.locks.request(LOCK, { signal: queued.signal }, hold).catch(onRejected);
  if (channel) channel.postMessage({ type: "handover" });
  const outcome = await Promise.race([got.then(() => "ok"), new Promise((r) => setTimeout(r, 5000, "timeout"))]);
  if (outcome === "timeout") {
    // The other copy didn't answer (e.g. a phone tab frozen in the background): take over anyway.
    queued.abort();
    navigator.locks.request(LOCK, { steal: true }, hold).catch(onRejected);
    await got;
  }
}

// ---------------------------------------------------------------- start-up
async function boot() {
  post({ type: "boot", stage: "Starting Sideband. The first visit may take a little longer…" });

  // Does this site's relay hold a Last.fm key? (Asked at run time, so it always matches the relay.)
  // Local history and saved results remain usable if this copy has no live lookup service.
  const relayTimeout = new AbortController();
  const timer = setTimeout(() => relayTimeout.abort(), 10_000);
  const relayConfig = DEMO ? { available: true } : await fetch(`${RELAY}?config=1`, {
    signal: relayTimeout.signal,
  }).then(async r => {
    if (!r.ok) throw new Error("Music lookup service unavailable");
    return { ...(await r.json()), available: true };
  }).catch(() => ({ available: false, lastfm: false }));
  clearTimeout(timer);
  const ownership = becomeOwner();
  const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
  py = await loadPyodide({ indexURL: PYODIDE });

  post({ type: "boot", stage: "Opening your saved data…" });
  await ownership;
  py.FS.mkdirTree("/data");
  if (!DEMO) {
    py.FS.mount(py.FS.filesystems.IDBFS, {}, "/data");
    await syncfs(true);
  }

  const manifest = await (await fetch(new URL(`py/manifest.json?v=${VERSION}`, BASE))).json();
  await Promise.all(manifest.files.map(async (file) => {
    const res = await fetch(new URL(`py/${file}?v=${manifest.version}`, BASE));
    if (!res.ok) throw new Error(`Could not load ${file} (${res.status})`);
    const target = `/home/pyodide/${file}`;
    py.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
    py.FS.writeFile(target, await res.text());
  }));

  if (DEMO) post({ type: "boot", stage: "Simulating a listener and a music catalogue (about 30 seconds)…" });
  py.runPython("import sys\nif '/home/pyodide' not in sys.path: sys.path.insert(0, '/home/pyodide')");
  const lastfm = Boolean(relayConfig.lastfm);
  py.globals.set("sideband_relay_url", RELAY);
  backend = py.runPython("from musicfinder.browser import BrowserBackend\n"
    + `BrowserBackend(demo=${DEMO ? "True" : "False"}, lastfm=${lastfm ? "True" : "False"}, `
    + `lookup_available=${relayConfig.available ? "True" : "False"}, relay_url=sideband_relay_url)`);
  lastWrites = backend.writes(); // opening the database is not a change worth saving
  post({ type: "ready", demo: DEMO });
}

const ready = boot().catch((err) => {
  post({ type: "fatal", error: String((err && err.message) || err) });
  throw err;
});

// ---------------------------------------------------------------- parallel fetching through the relay
const nextSlot = {};

async function pace(host) {
  const interval = 1000 / (RATES[host] || 4);
  const now = performance.now();
  const slot = Math.max(now, nextSlot[host] || 0);
  nextSlot[host] = slot + interval;
  if (slot > now) await new Promise((r) => setTimeout(r, slot - now));
}

async function fetchAll(items, onResult, onProgress) {
  // Group by service so a slow one (MusicBrainz: 1 request/second) never blocks the others.
  const queues = {};
  for (const it of items) (queues[it.host] ||= []).push(it);
  let done = 0;
  const runQueue = async (queue, lanes) => {
    const lane = async () => {
      while (queue.length) {
        const item = queue.shift();
        await pace(item.host);
        let status = 0;
        let text = "";
        try {
          const res = await fetch(`${RELAY}?url=${encodeURIComponent(item.url)}`);
          text = await res.text();
          // The relay's own failures are not answers from the music service: leave status 0 (retry later).
          status = res.headers.get("X-Relay-Error") ? 0 : res.status;
        } catch { status = 0; }
        onResult(item, status, text);
        done += 1;
        if (onProgress) onProgress(done, items.length);
      }
    };
    await Promise.all(Array.from({ length: lanes }, lane));
  };
  const hosts = Object.keys(queues);
  const lanesEach = Math.max(1, Math.floor(MAX_PARALLEL / Math.max(1, hosts.length)));
  await Promise.all(hosts.map((h) => runQueue(queues[h], Math.min(lanesEach, queues[h].length))));
}

async function drive(task, onProgress) {
  while (!task.step()) {
    for (let round = 0; round < 8; round++) {
      const proxy = task.plan();
      const plan = proxy.toJs({ dict_converter: Object.fromEntries });
      proxy.destroy();
      if (!plan.length) break;
      const label = task.label;
      await fetchAll(plan, (item, status, text) => task.ingest(item.key, status, text),
        onProgress ? (d, t) => onProgress(label, d, t) : null);
      noteWrites();
    }
  }
}

async function runJob(task) {
  try {
    await drive(task, (label, done, total) => backend.report(label, done, total));
  } catch (err) {
    console.error("musicfinder job failed", err);
  } finally {
    task.destroy();
    await save();
    post({ type: "job-done" });
  }
}

// ---------------------------------------------------------------- messages from the page
self.onmessage = async (event) => {
  const msg = event.data || {};
  if (msg.type === "save") {
    await ready.catch(() => {});
    await save();
    return;
  }
  if (msg.type !== "request") return;
  try {
    await ready;
    if (lost) {
      post({ type: "response", id: msg.id, status: 409,
        payload: { error: "musicfinder is open in another tab or window. Reload this page to use it here." } });
      return;
    }
    const body = msg.body ? new Uint8Array(msg.body) : undefined; // undefined arrives in Python as None
    const task = backend.request(msg.method, msg.path, msg.query || "", body, msg.filename || "upload.json");
    let out;
    try {
      await drive(task, null);
      out = JSON.parse(task.result_json());
    } finally {
      task.destroy();
    }
    noteWrites();
    post({ type: "response", id: msg.id, status: out.status, payload: out.payload });
    if (msg.method === "POST") save();
    const job = backend.take_job();
    if (job) runJob(job);
  } catch (err) {
    post({ type: "response", id: msg.id, status: 500, payload: { error: String((err && err.message) || err) } });
  }
};
