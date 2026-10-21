import test from "node:test";
import assert from "node:assert/strict";
import { filterSavedChoices } from "../../musicfinder/web/ui-state.js";

const choices = [
  { artist: "Björk", track: "", verdict: "like" },
  { artist: "Björk", track: "Jóga", verdict: "dislike" },
  { artist: "Radiohead", track: "Weird Fishes/Arpeggi", verdict: "like" },
  { artist: "Nina Simone", track: "Sinnerman", verdict: "known" },
  { artist: "Radiohead", track: "", verdict: "known" },
];

test("saved-choice search finds accented names and song titles without changing order or data", () => {
  const before = JSON.stringify(choices);
  assert.deepEqual(filterSavedChoices(choices, { query: " BJORK " }), choices.slice(0, 2));
  assert.deepEqual(filterSavedChoices(choices, { query: "joga bjork" }), [choices[1]]);
  assert.deepEqual(filterSavedChoices(choices, { query: "arpeggi" }), [choices[2]]);
  assert.deepEqual(filterSavedChoices(choices, { query: "not in this library" }), []);
  assert.equal(JSON.stringify(choices), before);
});

test("artist and song filters keep their decisions independent and combine with verdict and search", () => {
  assert.deepEqual(filterSavedChoices(choices, { scope: "artist" }), [choices[0], choices[4]]);
  assert.deepEqual(filterSavedChoices(choices, { scope: "song", verdict: "like" }), [choices[2]]);
  assert.deepEqual(filterSavedChoices(choices, { query: "radiohead", verdict: "known" }), [choices[4]]);
  assert.deepEqual(filterSavedChoices(choices, { query: "bjork", scope: "artist", verdict: "dislike" }), []);
  assert.deepEqual(filterSavedChoices(choices, { verdict: "known" }), [choices[3], choices[4]]);
});

test("empty libraries and unrecognized filters remain safe", () => {
  assert.deepEqual(filterSavedChoices([], { query: "music" }), []);
  assert.deepEqual(filterSavedChoices(choices, { scope: "unrecognized", verdict: "unrecognized" }), choices);
  assert.deepEqual(filterSavedChoices([{ artist: "Björk", verdict: "like" }], { scope: "artist" }), [{ artist: "Björk", verdict: "like" }]);
});
