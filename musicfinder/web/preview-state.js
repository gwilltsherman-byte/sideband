// Public preview availability only: never a record of listening or a taste signal.
import { feedbackIdentity } from "./listening-signals.js";

export function previewResult(info) {
  if (!info?.preview_url) return { status: "unavailable" };
  let url;
  try { url = new URL(info.preview_url); } catch { throw new Error("Invalid preview address"); }
  if (url.protocol !== "https:" || url.username || url.password) throw new Error("Invalid preview address");
  return { status: "ready", info: { ...info, preview_url: url.href } };
}

// A small shared cache and queue prevent duplicated rows or rapid scrolling from
// flooding the music service. Failed checks remain retryable rather than absent.
export function previewAvailability({ lookup, concurrency = 2, capacity = 128, now = Date.now, readyTtl = 15 * 60_000, unavailableTtl = 5 * 60_000 }) {
  const cache = new Map();
  const pending = new Map();
  const queue = [];
  let active = 0;
  const keyFor = (artist, track = "") => feedbackIdentity(artist, track);
  function remember(key, result) {
    cache.delete(key);
    cache.set(key, { result, until: now() + (result.status === "ready" ? readyTtl : unavailableTtl) });
    while (cache.size > capacity) cache.delete(cache.keys().next().value);
  }
  function drain() {
    while (active < concurrency && queue.length) {
      const job = queue.shift();
      active += 1;
      Promise.resolve().then(() => lookup(job.artist, job.track, { retry: job.retry })).then(previewResult).catch((error) => ({ status: "error", error })).then((result) => {
        if (result.status !== "error") remember(job.key, result);
        job.resolve(result);
      }).finally(() => {
        if (pending.get(job.key) === job) pending.delete(job.key);
        active -= 1;
        drain();
      });
    }
  }
  function request(artist, track = "", { retry = false } = {}) {
    const key = keyFor(artist, track);
    if (retry) cache.delete(key);
    const saved = cache.get(key);
    if (saved && saved.until > now()) return Promise.resolve(saved.result);
    if (saved) cache.delete(key);
    if (pending.has(key)) return pending.get(key).promise;
    const job = { key, artist, track, retry };
    job.promise = new Promise((resolve) => { job.resolve = resolve; });
    pending.set(key, job);
    queue.push(job);
    drain();
    return job.promise;
  }
  function cancelPending() {
    // Active reads can safely finish and populate the public metadata cache.
    // Queued work for rows removed by navigation must never start.
    for (const job of queue.splice(0)) {
      if (pending.get(job.key) === job) pending.delete(job.key);
      job.resolve({ status: "cancelled" });
    }
  }
  return { request, cancelPending, forget: (artist, track = "") => cache.delete(keyFor(artist, track)) };
}

export function previewInViewport(rect, height, width) {
  return rect.bottom > 0 && rect.top < height && rect.right > 0 && rect.left < width;
}
