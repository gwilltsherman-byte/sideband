// Count observed, audible playback rather than a seek position or time spent on a page.
import { artistIdentity } from "./artist-picker.js";

// Serialize saves and discard reads made obsolete by a new user choice.
export function feedbackIO({ read, write }) {
  let tail = Promise.resolve();
  let generation = 0;
  return {
    save(body) {
      generation += 1;
      const save = tail.catch(() => {}).then(() => write(body));
      tail = save;
      return save;
    },
    async read() {
      // Each retry requires a new user write; a stable request returns once.
      for (;;) {
        const pending = tail;
        await pending.catch(() => {});
        if (pending !== tail) continue;
        const version = generation;
        const stats = await read();
        if (version === generation) return stats;
      }
    },
  };
}

export function previewObservation({ minimumMs = 10000, maximumMs = 60000 } = {}) {
  let running = false;
  let lastTime = 0;
  let lastWall = 0;
  let heardMs = 0;
  let emitted = false;
  const baseline = (time, wall) => { lastTime = time; lastWall = wall; };
  return {
    start(time, wall) {
      running = Number.isFinite(time) && Number.isFinite(wall);
      baseline(time, wall);
    },
    sample(time, wall, { audible = true, rate = 1 } = {}) {
      const elapsed = wall - lastWall;
      const advance = (time - lastTime) * 1000;
      // Ignore seeks/jumps and stalled audio. Wall time also limits fast playback.
      if (running && audible && Number.isFinite(advance) && Number.isFinite(elapsed)
        && elapsed > 0 && advance > 0 && Number.isFinite(rate) && rate > 0
        && advance <= elapsed * rate + 350) {
        heardMs = Math.min(maximumMs, heardMs + Math.min(advance, elapsed));
      }
      baseline(time, wall);
      return heardMs;
    },
    suspend() { running = false; },
    take() {
      if (emitted || heardMs < minimumMs) return null;
      emitted = true;
      return Math.round(heardMs);
    },
  };
}

// Artist and song choices remain separate, including for identically named songs.
export function trackIdentity(title) {
  if (typeof title !== "string" || !title) return "";
  // Keep this in step with musicfinder.normalize.track_key across music providers.
  const fold = (value) => value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").normalize("NFC")
    .toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ");
  const cleaned = title.replace(/\s*[\(\[][^\)\]]*[\)\]]/g, "")
    .replace(/\s+-\s+.*\b(remaster(ed)?|version|edit|mix|live|mono|stereo|acoustic|demo|bonus|session|single|instrumental|deluxe|anniversary|recorded|take)\b.*$/i, "")
    .replace(/\s+(feat\.?|ft\.?|featuring)\s+.*$/i, "");
  const key = fold(cleaned).replace(/&/g, " and ").replace(/[^\p{L}\p{N}_\s]/gu, " ")
    .replace(/\s+/g, " ").trim();
  return key || fold(title).trim();
}
export function feedbackIdentity(artist, track = "") {
  return JSON.stringify([artistIdentity(artist), trackIdentity(track)]);
}
