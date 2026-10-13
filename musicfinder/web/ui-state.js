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
  if (next === "import") return state.plays ? "more_history" : "history";
  if (next === "listen") return "current";
  if (!state.plays) return "history";
  if (!state.graph_ready || !state.personalization?.tested_current) return "prepare";
  // A fresh unsuccessful test is still a completed test. Do not keep asking the
  // listener to rerun an unchanged history just because fitting was inconclusive.
  return "current";
}

export function latestRequest() {
  let sequence = 0;
  return {
    start: () => ++sequence,
    current: (token) => token === sequence,
  };
}
