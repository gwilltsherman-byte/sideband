import test from "node:test";
import assert from "node:assert/strict";
import { explorationChoice, batchChoice, nextRecommendationAction, latestRequest, quickReviewCurrent, quickInputKind } from "../../musicfinder/web/ui-state.js";

test("saved recommendation preferences survive missing, corrupt and out-of-range values", () => {
  for (const value of [null, undefined, "", "broken", Infinity]) assert.equal(explorationChoice(value), 0.15);
  assert.equal(explorationChoice("0.65"), 0.65);
  assert.equal(explorationChoice(-2), 0);
  assert.equal(explorationChoice(9), 1);
  for (const value of [null, undefined, "broken", 0, 1000]) assert.equal(batchChoice(value), 10);
  assert.equal(batchChoice("20"), 20);
  assert.equal(batchChoice(30), 30);
});

test("history gets an actionable preparation step and an unchanged inconclusive test stays completed", () => {
  assert.equal(nextRecommendationAction({ plays: 0 }), "history");
  assert.equal(nextRecommendationAction({ plays: 5000, graph_ready: true }), "prepare");
  assert.equal(nextRecommendationAction({ plays: 5000, graph_ready: false, personalization: { tested_current: true } }), "prepare");
  assert.equal(nextRecommendationAction({ plays: 5000, graph_ready: true, personalization: { tested_current: true, model_current: false, status: "limited" } }), "current");
  assert.equal(nextRecommendationAction({ plays: 5000, graph_ready: true, personalization: { tested_current: true, model_current: true } }), "current");
  assert.equal(nextRecommendationAction({ plays: 0, job: { running: true } }), "working");
  assert.equal(nextRecommendationAction({ plays: 20, graph_ready: true, personalization: { can_evaluate: false, tested_current: false, status: "limited", next_action: "import" } }), "more_history");
  assert.equal(nextRecommendationAction({ plays: 20, graph_ready: false, personalization: { can_evaluate: false, status: "needs_update", next_action: "prepare" } }), "prepare");
  assert.equal(nextRecommendationAction({ plays: 0, graph_ready: false, personalization: { next_action: "prepare" } }), "prepare");
  assert.equal(nextRecommendationAction({ plays: 0, has_data: true, graph_ready: true, personalization: { next_action: "import" } }), "taste");
});

test("quick taste can be saved only after a successful review of the exact unchanged input", () => {
  const review = { text: "Radiohead", kind: "artists", name: "", preview: { can_save: true, items: [{ artist: "Radiohead", kind: "picked_artist" }], errors: [] } };
  assert.equal(quickReviewCurrent(null, "Radiohead", "artists"), false);
  assert.equal(quickReviewCurrent(review, "Radiohead", "artists"), true);
  assert.equal(quickReviewCurrent(review, "Radiohead\nBjörk", "artists"), false);
  assert.equal(quickReviewCurrent(review, "Radiohead", "songs"), false);
  assert.equal(quickReviewCurrent(review, "Radiohead", "artists", "playlist.csv"), false);
  assert.equal(quickReviewCurrent({ ...review, preview: { ...review.preview, can_save: false } }, "Radiohead", "artists"), false);
  assert.equal(quickReviewCurrent({ ...review, preview: { ...review.preview, errors: ["Too many rows"] } }, "Radiohead", "artists"), false);
});

test("file input detects its columns regardless of the current paste mode", () => {
  assert.equal(quickInputKind("artists", "playlist.csv"), "auto");
  assert.equal(quickInputKind("songs", "artists.txt"), "auto");
  assert.equal(quickInputKind("artists"), "artists");
  assert.equal(quickInputKind("songs"), "songs");
  const review = { text: "Artist,Track\nRadiohead,Weird Fishes", kind: "auto", name: "playlist.csv", preview: { can_save: true, items: [{ artist: "Radiohead", track: "Weird Fishes" }] } };
  assert.equal(quickReviewCurrent(review, review.text, quickInputKind("artists", review.name), review.name), true);
});

test("an older delayed ranking cannot replace the most recent dial results", async () => {
  const requests = latestRequest();
  let resolveOld;
  const oldData = new Promise((resolve) => { resolveOld = resolve; });
  let shown;
  const oldToken = requests.start();
  const oldLoad = oldData.then((data) => { if (requests.current(oldToken)) shown = data; });
  // Changing the dial invalidates an in-flight request even before its debounce expires.
  requests.start();
  const newToken = requests.start();
  if (requests.current(newToken)) shown = "new dial";
  resolveOld("old dial");
  await oldLoad;
  assert.equal(shown, "new dial");
});
