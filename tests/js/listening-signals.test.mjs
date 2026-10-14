import test from "node:test";
import assert from "node:assert/strict";
import { previewObservation, feedbackIdentity, trackIdentity, feedbackIO } from "../../musicfinder/web/listening-signals.js";

const nextTurn = () => new Promise((resolve) => setImmediate(resolve));

test("rapid choices on different songs save in order and a failed save does not drop later choices", async () => {
  let release;
  const requested = [];
  const access = feedbackIO({ read: async () => ({}), write: async (choice) => {
    requested.push(choice);
    if (choice === "first song") await new Promise((resolve) => { release = resolve; });
    if (choice === "broken song") throw new Error("Not saved");
    return { saved: choice };
  } });
  const first = access.save("first song");
  const second = access.save("second song");
  await nextTurn();
  assert.deepEqual(requested, ["first song"]);
  release();
  assert.deepEqual(await first, { saved: "first song" });
  assert.deepEqual(await second, { saved: "second song" });
  const failed = access.save("broken song");
  const last = access.save("last song");
  await assert.rejects(failed, /Not saved/);
  assert.deepEqual(await last, { saved: "last song" });
  assert.deepEqual(requested, ["first song", "second song", "broken song", "last song"]);
});

test("a delayed feedback snapshot is reread after a new choice rather than overwriting it", async () => {
  const releases = [];
  let releaseWrite;
  const access = feedbackIO({
    read: () => new Promise((resolve) => releases.push(resolve)),
    write: () => new Promise((resolve) => { releaseWrite = resolve; }),
  });
  const reading = access.read();
  await nextTurn();
  assert.equal(releases.length, 1);
  const writing = access.save({ artist: "Björk", track: "Joga", verdict: "dislike" });
  await nextTurn();
  releases[0]({ saved_items: [] });
  await nextTurn();
  assert.equal(releases.length, 1); // no polling while the save remains pending
  releaseWrite({ saved_items: [{ verdict: "dislike" }] });
  await writing;
  await nextTurn();
  assert.equal(releases.length, 2);
  releases[1]({ saved_items: [{ verdict: "dislike" }] });
  assert.deepEqual(await reading, { saved_items: [{ verdict: "dislike" }] });
});

test("brief previews and time spent paused do not become preference signals", () => {
  const listen = previewObservation();
  listen.start(0, 0);
  listen.sample(9, 9000);
  listen.suspend();
  listen.sample(9, 60000);
  assert.equal(listen.take(), null);
  listen.start(9, 60000);
  listen.sample(10, 61000);
  assert.equal(listen.take(), 10000);
  assert.equal(listen.take(), null);
});

test("seek jumps, buffering and muted playback add no invented listening", () => {
  const listen = previewObservation();
  listen.start(0, 0);
  listen.sample(5, 5000);
  listen.sample(25, 5100); // seek forwards, not twenty seconds heard
  listen.suspend();
  listen.sample(25, 15100); // waiting for the source
  listen.start(25, 15100);
  listen.sample(30, 20100, { audible: false });
  assert.equal(listen.take(), null);
  listen.sample(35, 25100);
  assert.equal(listen.take(), 10000);
});

test("a preview is capped, emitted once, and a real replay has a new observation", () => {
  const listen = previewObservation();
  listen.start(0, 0);
  listen.sample(90, 90000);
  assert.equal(listen.take(), 60000);
  listen.sample(100, 100000);
  assert.equal(listen.take(), null);
  const replay = previewObservation();
  replay.start(0, 100000);
  replay.sample(10, 110000);
  assert.equal(replay.take(), 10000);
});

test("fast playback and backwards seeks never inflate listening duration", () => {
  const listen = previewObservation();
  listen.start(0, 0);
  listen.sample(20, 10000, { rate: 2 });
  listen.sample(0, 11000);
  assert.equal(listen.take(), 10000);
  const backwards = previewObservation();
  backwards.start(20, 0);
  backwards.sample(0, 1000);
  assert.equal(backwards.take(), null);
});

test("saved choices distinguish song feedback from an artist-wide choice", () => {
  assert.equal(feedbackIdentity(" Björk ", " Joga "), feedbackIdentity("björk", "joga"));
  assert.notEqual(feedbackIdentity("Björk", "Joga"), feedbackIdentity("Björk"));
  assert.notEqual(feedbackIdentity("Björk", "Joga"), feedbackIdentity("Björk", "Army of Me"));
  assert.notEqual(feedbackIdentity("Björk", "Joga"), feedbackIdentity("Another Artist", "Joga"));
});

test("provider accents, artist aliases and remaster names share one saved choice", () => {
  assert.equal(feedbackIdentity("Bjork", "Joga (Remastered)"), feedbackIdentity("Björk", "Jóga"));
  assert.equal(feedbackIdentity("Beatles", "Come Together - 2009 Remaster"), feedbackIdentity("The Beatles", "Come Together"));
  assert.equal(feedbackIdentity("Simon & Garfunkel", "The Sound of Silence"), feedbackIdentity("Simon and Garfunkel", "The Sound of Silence"));
});

test("song version and featured-credit variants collapse without losing song or artist scope", () => {
  for (const title of ["Joga (Live)", "Joga [with Someone]", "Joga - Radio Edit", "Joga feat. Someone", "Joga ft Someone"]) {
    assert.equal(trackIdentity(title), "joga");
    assert.equal(feedbackIdentity("Bjork", title), feedbackIdentity("Björk", "Joga"));
  }
  assert.equal(trackIdentity("The End"), "the end");
  assert.notEqual(feedbackIdentity("The Beatles", "The End - Live"), feedbackIdentity("Beatles"));
  assert.notEqual(feedbackIdentity("The Beatles", "The End - Live"), feedbackIdentity("Beatles", "End"));
});
