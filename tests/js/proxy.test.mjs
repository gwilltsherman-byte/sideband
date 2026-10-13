import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import proxy, { checkTarget, config } from "../../server/proxy.mjs";

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

const call = (url, init = {}) =>
  proxy(new Request(`https://sideband.example/api/proxy?url=${encodeURIComponent(url)}`, init));

test("routes at /api/proxy", () => assert.equal(config.path, "/api/proxy"));

test("allows only the music APIs musicfinder uses", () => {
  for (const ok of [
    "https://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist=Radiohead&api_key=K&format=json",
    "https://api.deezer.com/search/artist?q=Radiohead&limit=10",
    "https://api.deezer.com/artist/399/related?limit=50",
    "https://musicbrainz.org/ws/2/artist/?query=artist%3A%22Bj%C3%B6rk%22&fmt=json",
    "https://labs.api.listenbrainz.org/similar-artists/json?artist_mbids=x&algorithm=y",
  ]) assert.ok(checkTarget(ok).target, ok);
  for (const bad of [
    "http://ws.audioscrobbler.com/2.0/", // not https
    "https://example.com/", "https://evil.api.deezer.com.example.com/search/artist",
    "https://api.deezer.com/user/me", "https://musicbrainz.org/admin",
    "https://user:pw@api.deezer.com/artist/1", "https://api.deezer.com:8443/artist/1",
    "https://169.254.169.254/latest/meta-data", "not a url", "",
  ]) assert.ok(checkTarget(bad).error, bad);
});

test("forwards GETs with an identifying User-Agent and passes status and body through", async () => {
  let seen;
  globalThis.fetch = async (target, init) => {
    seen = { target: String(target), init };
    return new Response('{"data":[1]}', { status: 200, headers: { "content-type": "application/json" } });
  };
  const res = await call("https://api.deezer.com/search/artist?q=x", { headers: { "sec-fetch-site": "same-origin" } });
  assert.equal(res.status, 200);
  assert.equal(await res.text(), '{"data":[1]}');
  assert.equal(seen.target, "https://api.deezer.com/search/artist?q=x");
  assert.match(seen.init.headers["User-Agent"], /^Sideband\//);
  assert.equal(seen.init.redirect, "manual");
  assert.equal(res.headers.get("cache-control"), "no-store");
  assert.equal(res.headers.get("x-relay-error"), null); // genuine upstream answers are not marked

  process.env.LASTFM_API_KEY = "SITEKEY";
  globalThis.fetch = async () => new Response('{"error":29}', { status: 429 });
  assert.equal((await call("https://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist=x")).status, 429);
  delete process.env.LASTFM_API_KEY;
});

test("adds the site's Last.fm key on the server and allows only read-only Last.fm lookups", async () => {
  let seen = null;
  globalThis.fetch = async (target) => { seen = new URL(String(target)); return new Response('{"artist":{}}'); };
  const lfm = "https://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist=Radiohead&api_key=relay&format=json";

  delete process.env.LASTFM_API_KEY;
  const config = () => proxy(new Request("https://sideband.example/api/proxy?config=1")).then((r) => r.json());
  assert.deepEqual(await config(), { lastfm: false });
  let res = await call(lfm);
  assert.equal(res.status, 503);
  assert.equal(res.headers.get("x-relay-error"), "1"); // never cached by the app
  assert.equal(seen, null);

  process.env.LASTFM_API_KEY = " SITEKEY ";
  try {
    assert.deepEqual(await config(), { lastfm: true }); // whether there is a key, never the key
    res = await call(lfm);
    assert.equal(res.status, 200);
    assert.equal(seen.searchParams.get("api_key"), "SITEKEY"); // the placeholder is replaced
    assert.equal(seen.searchParams.get("artist"), "Radiohead");
    assert.ok(!(await res.text()).includes("SITEKEY"));
    seen = null;
    for (const method of ["auth.getSession", "user.getInfo", "track.scrobble", "", "artist.getinfo&method=user.getInfo"]) {
      res = await call(`https://ws.audioscrobbler.com/2.0/?method=${method}&api_key=relay`);
      assert.equal(res.status, 400, method);
    }
    assert.equal(seen, null);
  } finally {
    delete process.env.LASTFM_API_KEY;
  }
});

test("refuses other websites, other methods, redirects and dead upstreams", async () => {
  globalThis.fetch = async () => { throw new Error("should not be called"); };
  assert.equal((await call("https://api.deezer.com/artist/1", { headers: { "sec-fetch-site": "cross-site" } })).status, 403);
  assert.equal((await call("https://example.com/")).status, 400);
  assert.equal((await proxy(new Request("https://sideband.example/api/proxy?url=x", { method: "POST" }))).status, 405);

  globalThis.fetch = async () => new Response("", { status: 302, headers: { location: "https://example.com" } });
  assert.equal((await call("https://api.deezer.com/artist/1")).status, 502);
  globalThis.fetch = async () => { throw new TypeError("fetch failed"); };
  const res = await call("https://api.deezer.com/artist/1");
  assert.equal(res.status, 502);
  assert.match((await res.json()).relay_error, /did not respond/);
  assert.equal(res.headers.get("x-relay-error"), "1");
});
