import test from "node:test";
import assert from "node:assert/strict";
import { weekStart, addDaysISO, listenChoice, listenUrl, stackStatusLabel } from "../../musicfinder/web/ui-state.js";

test("the week starts on the most recent local Sunday", () => {
  assert.equal(weekStart(new Date(2026, 9, 18, 0, 0)), "2026-10-18"); // a Sunday, just after midnight
  assert.equal(weekStart(new Date(2026, 9, 18, 23, 59)), "2026-10-18");
  assert.equal(weekStart(new Date(2026, 9, 19, 9, 0)), "2026-10-18"); // Monday
  assert.equal(weekStart(new Date(2026, 9, 24, 23, 59)), "2026-10-18"); // Saturday night
  assert.equal(weekStart(new Date(2026, 0, 2)), "2025-12-28"); // across a year boundary
  assert.equal(weekStart(new Date(2028, 2, 1)), "2028-02-27"); // across a leap day
});

test("adding days stays on calendar dates across months and years", () => {
  assert.equal(addDaysISO("2026-10-18", 7), "2026-10-25");
  assert.equal(addDaysISO("2026-12-27", 7), "2027-01-03");
  assert.equal(addDaysISO("2028-02-27", 2), "2028-02-29");
  assert.equal(addDaysISO("2026-03-01", -1), "2026-02-28");
  // The next week always starts seven days later, including across daylight-saving changes.
  for (let day = 0; day < 400; day += 13) {
    const date = new Date(2026, 0, 1 + day, 12);
    assert.equal(addDaysISO(weekStart(date), 7), weekStart(new Date(date.getFullYear(), date.getMonth(), date.getDate() + 7, 12)));
  }
});

test("a saved listening service falls back to Spotify when missing or unknown", () => {
  for (const value of [null, undefined, "", "napster", "toString", "__proto__", 3]) assert.equal(listenChoice(value), "spotify");
  for (const value of ["spotify", "apple", "youtube", "deezer", "bandcamp"]) assert.equal(listenChoice(value), value);
});

test("listen links search each service for the song and artist", () => {
  assert.equal(listenUrl("spotify", "Björk"), "https://open.spotify.com/search/Bj%C3%B6rk");
  assert.equal(listenUrl("apple", "Björk", "Jóga"), "https://music.apple.com/search?term=J%C3%B3ga%20Bj%C3%B6rk");
  assert.equal(listenUrl("youtube", "AC/DC", "T.N.T."), "https://music.youtube.com/search?q=T.N.T.%20AC%2FDC");
  assert.equal(listenUrl("deezer", "Simon & Garfunkel"), "https://www.deezer.com/search/Simon%20%26%20Garfunkel");
  assert.equal(listenUrl("bandcamp", "Khruangbin", "Maria También"), "https://bandcamp.com/search?q=Maria%20Tambi%C3%A9n%20Khruangbin");
  assert.equal(listenUrl("unknown", "Radiohead"), "https://open.spotify.com/search/Radiohead");
});

test("sorted artists get a plain status label", () => {
  assert.equal(stackStatusLabel("kept"), "Kept");
  assert.equal(stackStatusLabel("passed"), "Passed");
  assert.equal(stackStatusLabel("known"), "Already knew");
  assert.equal(stackStatusLabel("snoozed"), "Not now");
  assert.equal(stackStatusLabel("open"), "");
  assert.equal(stackStatusLabel(undefined), "");
});
