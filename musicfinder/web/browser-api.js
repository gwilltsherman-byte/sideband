// Page side of the browser build: forwards API requests to the engine running in worker.js.

const version = window.MUSICFINDER_VERSION || "dev";
const demo = new URLSearchParams(location.search).get("demo") === "1";
const workerURL = new URL("./worker.js", import.meta.url);
workerURL.searchParams.set("v", version);
if (demo) workerURL.searchParams.set("demo", "1");
workerURL.searchParams.set("pyodide", window.MUSICFINDER_PYODIDE || new URL("../pyodide/", import.meta.url).href);
if (window.MUSICFINDER_RELAY) workerURL.searchParams.set("relay", window.MUSICFINDER_RELAY);
const worker = new Worker(workerURL, { type: "module" });

let nextId = 1;
const pending = new Map();
let fatal = null;

function showBoot(text) {
  const el = document.querySelector("#main .loading");
  if (el) el.textContent = text;
}

worker.onmessage = (event) => {
  const msg = event.data || {};
  if (msg.type === "response") {
    const p = pending.get(msg.id);
    if (p) { pending.delete(msg.id); p.resolve({ status: msg.status, payload: msg.payload }); }
  } else if (msg.type === "boot") {
    showBoot(msg.stage);
  } else if (msg.type === "fatal") {
    fatal = msg.error;
    showBoot(`Sideband couldn't start in this browser: ${msg.error}`);
    for (const p of pending.values()) p.resolve({ status: 500, payload: { error: msg.error } });
    pending.clear();
  } else if (msg.type === "job-done") {
    keepAwake(false);
  } else if (msg.type === "lost") {
    showElsewhere();
  }
};
worker.onerror = (event) => {
  fatal = event.message || "the engine stopped";
  showBoot(`Sideband couldn't start in this browser: ${fatal}`);
};

// Another tab or window opened Sideband and took over the saved data (see worker.js).
function showElsewhere() {
  if (document.getElementById("elsewhere")) return;
  const strip = document.createElement("div");
  strip.id = "elsewhere";
  strip.className = "strip demo";
  strip.setAttribute("role", "alert");
  strip.innerHTML = "Sideband was opened in another tab or window, which now has your data. "
    + '<button type="button" class="quiet">Use it here instead</button>';
  strip.querySelector("button").addEventListener("click", () => location.reload());
  document.querySelector(".masthead").after(strip);
}

export async function request(method, pathWithQuery, body, headers = {}) {
  if (fatal) return { status: 500, payload: { error: fatal } };
  const [path, query = ""] = pathWithQuery.split("?");
  let buffer = null;
  if (body instanceof Blob) buffer = await body.arrayBuffer();
  else if (body !== undefined && body !== null) buffer = new TextEncoder().encode(JSON.stringify(body)).buffer;
  const id = nextId++;
  const filename = headers["X-Filename"] ? decodeURIComponent(headers["X-Filename"]) : "upload.json";
  return new Promise((resolve) => {
    pending.set(id, { resolve });
    worker.postMessage({ type: "request", id, method, path, query, body: buffer, filename }, buffer ? [buffer] : []);
  });
}

// Keep the phone awake while the map builds (the engine pauses when the screen locks).
let lock = null;
export async function keepAwake(on) {
  try {
    if (on && !lock && navigator.wakeLock) {
      lock = await navigator.wakeLock.request("screen");
      lock.addEventListener("release", () => { lock = null; });
    } else if (!on && lock) {
      await lock.release();
      lock = null;
    }
  } catch { /* not supported or not allowed: harmless */ }
}

// Save to the device whenever the page is hidden (switching apps, locking the phone).
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") worker.postMessage({ type: "save" });
  else if (lock === null && document.querySelector("#job-strip:not([hidden])")) keepAwake(true);
});

export const isDemo = demo;
