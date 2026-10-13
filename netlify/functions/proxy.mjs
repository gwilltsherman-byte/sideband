// Relay from the musicfinder page to the public music-data APIs.
//
// Browsers block a web page from reading most of these services directly (CORS), so the page asks
// this function instead: GET /api/proxy?url=<https URL of an allowed API>. Only GET, and only the
// specific API endpoints musicfinder uses, so it can't be used as a general-purpose proxy; browsers
// will not let other websites' pages use it (non-browser programs can, but only for those same public
// endpoints). Nothing is stored or logged here.
//
// Last.fm needs an API key. Listeners never enter one: the site's owner may set LASTFM_API_KEY in the
// Netlify site's environment variables, and the relay adds it to Last.fm requests here (the key never
// reaches the browser; GET /api/proxy?config=1 only tells the page whether there is one). Without it
// the app uses the free sources only and sends nothing to Last.fm.
//
// Errors produced by the relay itself (bad request, upstream unreachable...) carry an X-Relay-Error
// header and a {"relay_error": ...} body, so the app never mistakes them for a music service's answer
// (and never caches them).

const ALLOWED = {
  "ws.audioscrobbler.com": ["/2.0/"],
  "api.deezer.com": ["/search/artist", "/search/track", "/artist/", "/genre"],
  "musicbrainz.org": ["/ws/2/artist/"],
  "labs.api.listenbrainz.org": ["/similar-artists/json"],
};
// Only Last.fm's public, read-only lookups (the site's key is never usable for anything else).
const LASTFM_METHODS = new Set(["artist.getsimilar", "artist.gettoptags", "artist.getinfo", "artist.gettoptracks",
  "track.getsimilar", "tag.gettopartists"]);
// MusicBrainz and ListenBrainz ask every client to identify itself.
const USER_AGENT = "musicfinder/0.1 ( https://github.com/gwilltsherman-byte/music )";
const TIMEOUT_MS = 9000;
const MAX_BYTES = 2_000_000;

function reply(status, body, extra = {}) {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...extra },
  });
}

function fail(status, message, extra = {}) {
  return reply(status, { relay_error: message }, { "X-Relay-Error": "1", ...extra });
}

export function checkTarget(raw) {
  let target;
  try {
    target = new URL(raw);
  } catch {
    return { error: "Missing or invalid url parameter" };
  }
  const prefixes = ALLOWED[target.hostname];
  if (target.protocol !== "https:" || target.username || target.password || target.port || !prefixes
      || !prefixes.some((p) => target.pathname.startsWith(p)) || target.pathname.includes("..")) {
    return { error: "That address is not one of the music services musicfinder uses" };
  }
  return { target };
}

function lastfmKey() {
  const fromNetlify = globalThis.Netlify?.env?.get?.("LASTFM_API_KEY");
  return (fromNetlify || process.env.LASTFM_API_KEY || "").trim();
}

export default async function proxy(req) {
  if (req.method !== "GET") return fail(405, "Only GET is allowed", { Allow: "GET" });
  // Browsers label every request with where it came from; refuse other websites' pages.
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") {
    return fail(403, "This relay only serves the musicfinder site it belongs to");
  }
  const params = new URL(req.url).searchParams;
  // The page asks once per visit which services this relay offers (only whether a key is set, never the key).
  if (params.get("config") === "1" && !params.has("url")) return reply(200, { lastfm: Boolean(lastfmKey()) });
  const { target, error } = checkTarget(params.get("url") || "");
  if (error) return fail(400, error);
  if (target.hostname === "ws.audioscrobbler.com") {
    const methods = target.searchParams.getAll("method");
    if (methods.length !== 1 || !LASTFM_METHODS.has(methods[0])) {
      return fail(400, "That Last.fm method is not one musicfinder uses");
    }
    const key = lastfmKey();
    if (!key) return fail(503, "Last.fm is not set up on this site");
    target.searchParams.set("api_key", key);
  }

  let upstream;
  try {
    upstream = await fetch(target, {
      headers: { "User-Agent": USER_AGENT, Accept: "application/json" },
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return fail(502, `${target.hostname} did not respond`);
  }
  if (upstream.status >= 300 && upstream.status < 400) {
    return fail(502, `${target.hostname} answered with a redirect`);
  }
  const body = await upstream.text();
  if (body.length > MAX_BYTES) return fail(502, "Response too large");
  return reply(upstream.status, body, {
    "Content-Type": upstream.headers.get("content-type") || "application/json; charset=utf-8",
  });
}

export const config = { path: "/api/proxy" };
