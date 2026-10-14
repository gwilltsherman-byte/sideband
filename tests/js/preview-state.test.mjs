import test from "node:test";
import assert from "node:assert/strict";
import { previewAvailability, previewInViewport, previewResult } from "../../musicfinder/web/preview-state.js";

const matchingPreview = { artist: "Björk", title: "Jóga", preview_url: "https://audio.example.test/joga.mp3" };
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("only an actual safe preview URL makes a row playable", () => {
  assert.equal(previewResult(null).status, "unavailable");
  assert.equal(previewResult({}).status, "unavailable");
  assert.deepEqual(previewResult(matchingPreview), { status: "ready", info: matchingPreview });
  for (const url of ["not an address", "javascript:alert(1)", "http://audio.example.test/song.mp3", "https://user:password@audio.example.test/song.mp3"]) {
    assert.throws(() => previewResult({ ...matchingPreview, preview_url: url }), /Invalid preview address/);
  }
});

test("duplicate and remastered rows share one check without changing taste", async () => {
  const gate = deferred();
  const calls = [];
  const checks = previewAvailability({ lookup: (artist, title) => { calls.push([artist, title]); return gate.promise; } });
  const first = checks.request("Björk", "Jóga");
  const duplicate = checks.request("Bjork", "Joga (2013 Remaster)");
  await settle();
  assert.equal(calls.length, 1);
  gate.resolve(matchingPreview);
  assert.equal((await first).status, "ready");
  assert.equal((await duplicate).status, "ready");
  assert.equal((await checks.request("Björk", "Jóga")).status, "ready");
  assert.equal(calls.length, 1);
});

test("visible-row checks run with bounded concurrency while lists remain independent", async () => {
  const gates = Array.from({ length: 6 }, deferred);
  let running = 0;
  let mostRunning = 0;
  let started = 0;
  const checks = previewAvailability({ concurrency: 2, lookup: async () => {
    const index = started++;
    mostRunning = Math.max(mostRunning, ++running);
    await gates[index].promise;
    running -= 1;
    return null;
  } });
  const reads = Array.from({ length: 6 }, (_, index) => checks.request(`Artist ${index}`, "Song"));
  await settle();
  assert.equal(started, 2);
  gates[0].resolve();
  await settle();
  assert.equal(started, 3);
  for (const gate of gates) gate.resolve();
  assert.equal((await Promise.all(reads)).every((result) => result.status === "unavailable"), true);
  assert.equal(mostRunning, 2);
});

test("navigation cancels queued removed rows, but active metadata can safely finish", async () => {
  const gate = deferred();
  const calls = [];
  const checks = previewAvailability({ concurrency: 1, lookup: (artist) => { calls.push(artist); return gate.promise; } });
  const visible = checks.request("Visible", "Song");
  const removed = checks.request("Removed", "Song");
  checks.cancelPending();
  assert.equal((await removed).status, "cancelled");
  await settle();
  assert.deepEqual(calls, ["Visible"]);
  gate.resolve(matchingPreview);
  await visible;
  await settle();
  assert.deepEqual(calls, ["Visible"]);
  await checks.request("Removed", "Song");
  assert.deepEqual(calls, ["Visible", "Removed"]);
});

test("failed music lookups remain errors and can be retried, never cached as absence", async () => {
  let calls = 0;
  const failure = new Error("Music service unavailable");
  const checks = previewAvailability({ lookup: async () => { if (++calls === 1) throw failure; return matchingPreview; } });
  const failed = await checks.request("Björk", "Jóga");
  assert.equal(failed.status, "error");
  assert.equal(failed.error, failure);
  await settle();
  assert.equal((await checks.request("Björk", "Jóga", { retry: true })).status, "ready");
  assert.equal(calls, 2);
});

test("Retry bypasses positive and absent metadata and asks the source for a fresh URL", async () => {
  const calls = [];
  const checks = previewAvailability({ lookup: async (_artist, _track, options) => { calls.push(options.retry); return calls.length === 1 ? null : matchingPreview; } });
  assert.equal((await checks.request("Björk", "Jóga")).status, "unavailable");
  assert.equal((await checks.request("Björk", "Jóga")).status, "unavailable");
  await settle();
  assert.equal((await checks.request("Björk", "Jóga", { retry: true })).status, "ready");
  await settle();
  assert.equal((await checks.request("Björk", "Jóga", { retry: true })).status, "ready");
  assert.deepEqual(calls, [false, true, true]);
});

test("metadata expires and cache memory stays bounded across long sessions", async () => {
  let currentTime = 0;
  const calls = [];
  const checks = previewAvailability({ now: () => currentTime, readyTtl: 20, unavailableTtl: 5, capacity: 2, lookup: async (artist) => { calls.push(artist); return artist === "Absent" ? null : matchingPreview; } });
  await checks.request("Absent", "Song");
  currentTime = 6;
  await settle();
  await checks.request("Absent", "Song");
  assert.deepEqual(calls, ["Absent", "Absent"]);
  await checks.request("Ready", "Song");
  currentTime = 27;
  await settle();
  await checks.request("Ready", "Song");
  assert.equal(calls.filter((artist) => artist === "Ready").length, 2);
  await checks.request("Next", "Song");
  await checks.request("Last", "Song");
  await settle();
  await checks.request("Ready", "Song");
  assert.equal(calls.filter((artist) => artist === "Ready").length, 3);
});

test("expired or failed playback can forget only its own cached song", async () => {
  let calls = 0;
  const checks = previewAvailability({ lookup: async () => { calls++; return matchingPreview; } });
  await checks.request("Björk", "Jóga");
  await checks.request("Radiohead", "Reckoner");
  checks.forget("Björk", "Jóga");
  await settle();
  await checks.request("Björk", "Jóga");
  await checks.request("Radiohead", "Reckoner");
  assert.equal(calls, 3);
});

test("browsers without IntersectionObserver still check only on-screen rows", () => {
  const rect = { top: 10, bottom: 90, left: 0, right: 400 };
  assert.equal(previewInViewport(rect, 800, 400), true);
  assert.equal(previewInViewport({ ...rect, top: 800, bottom: 880 }, 800, 400), false);
  assert.equal(previewInViewport({ ...rect, top: -100, bottom: 0 }, 800, 400), false);
  assert.equal(previewInViewport({ ...rect, left: 400, right: 800 }, 800, 400), false);
  assert.equal(previewInViewport({ ...rect, top: -50, bottom: 10 }, 800, 400), true);
});
