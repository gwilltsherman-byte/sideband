import test from "node:test";
import assert from "node:assert/strict";
import { explorationChoice, batchChoice, nextRecommendationAction, latestRequest } from "../../musicfinder/web/ui-state.js";

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
