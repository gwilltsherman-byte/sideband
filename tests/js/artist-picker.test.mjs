import test from "node:test";
import assert from "node:assert/strict";
import { ARTIST_STYLES, ARTIST_CATALOG, artistChoices, artistIdentity } from "../../musicfinder/web/artist-picker.js";

const names = artists => artists.map(artist => artist.name);

test("catalog identities agree with the backend's artist matching for spelling variants", () => {
  for (const [name, expected] of [
    [" BjÖrk ", "bjork"], ["The Beatles", "beatles"], ["The Weeknd", "weeknd"],
    ["Simon & Garfunkel", "simon and garfunkel"], ["Florence + the Machine", "florence and the machine"],
    ["R.E.M.", "r e m"], ["Motörhead", "motorhead"], ["Straße", "strasse"],
    ["Σίσυφος", "σισυφοσ"], ["  A   B  ", "a b"], [null, ""],
  ]) assert.equal(artistIdentity(name), expected);
});

test("the curated catalog covers every style with unique artists and valid crossover tags", () => {
  assert.ok(ARTIST_CATALOG.length >= 180);
  assert.equal(new Set(names(ARTIST_CATALOG)).size, ARTIST_CATALOG.length);
  const ids = new Set(ARTIST_STYLES.map(style => style.id));
  assert.equal(ids.size, 12);
  for (const artist of ARTIST_CATALOG) {
    assert.ok(artist.name.trim());
    assert.ok(artist.styles.length);
    assert.ok(artist.styles.every(style => ids.has(style)));
    assert.equal(new Set(artist.styles).size, artist.styles.length);
  }
  for (const style of ids) assert.ok(ARTIST_CATALOG.filter(artist => artist.styles.includes(style)).length >= 20);
});

test("the initial screen includes each broad style and familiar artists from several eras", () => {
  const choices = artistChoices();
  assert.equal(choices.length, 24);
  for (const { id } of ARTIST_STYLES) assert.ok(choices.some(artist => artist.styles.includes(id)), id);
  for (const name of ["Taylor Swift", "The Beatles", "Miles Davis", "Johann Sebastian Bach", "Kendrick Lamar"]) {
    assert.ok(names(choices).includes(name));
  }
  assert.deepEqual(artistChoices({ styles: [] }), choices);
});

test("style filters narrow buttons without pretending an unselected genre is a personal artist preference", () => {
  const jazz = artistChoices({ styles: ["jazz"], limit: 1000 });
  assert.ok(jazz.length >= 20);
  assert.ok(jazz.every(artist => artist.styles.includes("jazz")));
  const union = artistChoices({ styles: ["jazz", "classical"], limit: 1000 });
  assert.ok(union.every(artist => artist.styles.some(style => ["jazz", "classical"].includes(style))));
  assert.deepEqual(artistChoices({ styles: ["unknown"] }), []);
  assert.deepEqual(artistChoices({ styles: ["unknown", "jazz"] }), artistChoices({ styles: ["jazz"] }));
  assert.deepEqual(artistChoices(), artistChoices({ selected: [] }));
});

test("explicit picks adapt suggestions to their own styles while retaining unrelated exploration", () => {
  const rock = artistChoices({ selected: ["Radiohead"] });
  const jazz = artistChoices({ selected: ["Miles Davis"] });
  assert.notDeepEqual(names(rock), names(jazz));
  assert.equal(rock[0].name, "Tame Impala");
  assert.equal(jazz[0].name, "Ella Fitzgerald");
  assert.ok(rock.slice(0, 3).every(artist => artist.styles.some(style => ["indie", "rock", "electronic"].includes(style))));
  assert.ok(jazz.slice(0, 3).every(artist => artist.styles.includes("jazz")));
  for (let index = 3; index < jazz.length; index += 4) assert.ok(!jazz[index].styles.includes("jazz"));
  assert.ok(!names(rock).includes("Radiohead"));
  assert.ok(!names(jazz).includes("Miles Davis"));
  assert.equal(rock.length, 24);
  assert.equal(jazz.length, 24);
});

test("filtering is respected even when picks come from another style", () => {
  const choices = artistChoices({ styles: ["classical"], selected: ["Kendrick Lamar"] });
  assert.ok(choices.length > 0);
  assert.ok(choices.every(artist => artist.styles.includes("classical")));
});

test("matching folds accents, case, punctuation and spacing and unknown names do not steer the catalog", () => {
  const options = { selected: ["  BJORK  ", "bJÖrK"], excluded: [" BEYONCE ", "R E M", "Beatles", "Florence & the Machine"] };
  const choices = artistChoices({ ...options, limit: 1000 });
  for (const name of ["Björk", "Beyoncé", "R.E.M.", "The Beatles", "Florence + the Machine"]) assert.ok(!names(choices).includes(name));
  assert.deepEqual(artistChoices({ selected: ["Not a catalog artist", ""] }), artistChoices());
  assert.deepEqual(artistChoices({ selected: ["Björk"] }), artistChoices({ selected: ["  BJORK  ", "bJÖrK"] }));
  assert.deepEqual(artistChoices({ selected: ["The Beatles"] }), artistChoices({ selected: ["beatles"] }));
  assert.deepEqual(artistChoices({ excluded: ["Unknown"] }), artistChoices());
});

test("pagination is deterministic, complete and never repeats an artist for unchanged choices", () => {
  for (const options of [{}, { selected: ["Radiohead", "Beyoncé"] }, { styles: ["jazz"], selected: ["Ella Fitzgerald"] }]) {
    const all = artistChoices({ ...options, limit: 1000 });
    const paged = [];
    for (let page = 0; page < Math.ceil(all.length / 7); page++) paged.push(...artistChoices({ ...options, page, limit: 7 }));
    assert.deepEqual(paged, all);
    assert.equal(new Set(names(paged)).size, all.length);
    assert.deepEqual(artistChoices({ ...options, page: 10000, limit: 7 }), []);
    assert.deepEqual(artistChoices(options), artistChoices(options));
  }
});

test("empty results and malformed optional inputs are safe and the shared catalog cannot be mutated", () => {
  assert.deepEqual(artistChoices({ excluded: names(ARTIST_CATALOG) }), []);
  assert.deepEqual(artistChoices({ limit: 0 }), []);
  assert.deepEqual(artistChoices(null), artistChoices());
  assert.deepEqual(artistChoices({ selected: null, excluded: [null, 2], styles: null, page: -5, limit: NaN }), artistChoices());
  assert.throws(() => ARTIST_CATALOG[0].styles.push("invented"), TypeError);
  assert.throws(() => artistChoices()[0].name = "changed", TypeError);
});
