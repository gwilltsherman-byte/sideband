// Small, dependency-free decisions shared by the UI and its regression tests.
export function explorationChoice(value) {
  const n = value == null || value === "" ? NaN : Number(value);
  return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0.15;
}

export function batchChoice(value) {
  const n = Number(value);
  return [10, 20, 30].includes(n) ? n : 10;
}

export function nextRecommendationAction(state) {
  if (state.job?.running) return "working";
  const next = state.personalization?.next_action;
  if (next === "prepare") return "prepare";
  if (next === "import") return state.plays ? "more_history" : state.has_data ? "taste" : "history";
  if (next === "listen") return "current";
  if (!state.plays) return state.has_data ? "taste" : "history";
  if (!state.graph_ready || !state.personalization?.tested_current) return "prepare";
  // A fresh unsuccessful test is still a completed test. Do not keep asking the
  // listener to rerun an unchanged history just because fitting was inconclusive.
  return "current";
}

export function quickReviewCurrent(review, text, kind, name = "") {
  return Boolean(review && review.text === text && review.kind === kind && review.name === name
    && review.preview?.can_save === true && review.preview.items?.length
    && !review.preview.errors?.length);
}

export function quickInputKind(kind, filename = "") {
  return filename ? "auto" : kind;
}

// The local calendar date of the most recent Sunday (today, on a Sunday), as YYYY-MM-DD.
// Built from date parts, so daylight-saving changes cannot shift the day.
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export function weekStart(date = new Date()) {
  return isoDay(new Date(date.getFullYear(), date.getMonth(), date.getDate() - date.getDay()));
}

export function addDaysISO(iso, days) {
  const [y, m, d] = String(iso).split("-").map(Number);
  return isoDay(new Date(y, m - 1, d + days));
}

export const LISTEN_SERVICES = { spotify: "Spotify", apple: "Apple Music", youtube: "YouTube Music", deezer: "Deezer", bandcamp: "Bandcamp" };

export function listenChoice(value) {
  return typeof value === "string" && Object.hasOwn(LISTEN_SERVICES, value) ? value : "spotify";
}

export function listenUrl(service, artist, title = "") {
  const q = encodeURIComponent(title ? `${title} ${artist}` : artist);
  return {
    spotify: `https://open.spotify.com/search/${q}`,
    apple: `https://music.apple.com/search?term=${q}`,
    youtube: `https://music.youtube.com/search?q=${q}`,
    deezer: `https://www.deezer.com/search/${q}`,
    bandcamp: `https://bandcamp.com/search?q=${q}`,
  }[listenChoice(service)];
}

export function stackStatusLabel(status) {
  return { kept: "Kept", passed: "Passed", known: "Already knew", snoozed: "Not now" }[status] || "";
}

export function latestRequest() {
  let sequence = 0;
  return {
    start: () => ++sequence,
    current: (token) => token === sequence,
  };
}
