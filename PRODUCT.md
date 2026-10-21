# Sideband

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Music listeners who want to discover artists and songs from music they already enjoy. The repository supports both occasional browsing on a phone and repeated listening on a desktop. This audience is inferred from the shipped workflows; no demographic assumptions are made.

## Product Purpose

Turn the listener's own taste (favorite artists, optional pasted lists, and their Keep / Pass / Know them / Not now decisions) into useful, explainable discoveries. A listening history is an optional extra, never required. Success means a listener can choose a favorite, find unfamiliar music, understand why it appeared, listen when a matching preview exists, and refine their taste without losing their place.

## Capabilities and Constraints

- Six navigation routes: This week (default), Songs, Explore, Your taste, Accuracy, Setup. For you remains as the full ranked list, linked from This week.
- This week: a weekly batch of about ten unfamiliar artists (close matches plus wildcards set by the adventurous dial) with Keep, Pass, Know them and Not now, undo, a Sorted this week list, 5 more, Your keepers with Share list, More songs per artist, and a Listen on choice of music service. Seen artists do not come back; an unanswered artist returns at most once.
- Offline starter artist catalog; live artist search; favorites and dislikes; bulk text/playlist inputs; optional Spotify ZIP/JSON listening-history import in Setup.
- Artist and song recommendations, adjustable exploration, feedback and undo, saved ratings, and three distinct song sources.
- Previews appear only after verified matching clips are found; missing, lookup failure, audio failure, retry, and playback are separate states.
- Accuracy results are grounded in Keep / Pass choices and ratings, plus observed history when one is imported. A candidate percentile is not a like probability. Synthetic demo data must be visibly labeled.
- Plain JavaScript and CSS frontend, Python recommendation engine, browser Pyodide worker or local Python server. Preserve API contracts, data storage, service worker, hosting, routes, and integrations.
- Device-local storage; no automatic cross-device sync. Backups and restore remain available. Music lookup sends artist/song names to the existing services.

## Operating Context

Installed iPhone/Mac web app or browser, desktop and mobile, light and dark environments. No account, sign-in or Spotify export is required at any point. Initial music-map creation can take several minutes. Offline access supports saved input; new discovery depends on lookup connectivity.

## Brand Commitments

Sideband is the existing product name. The user requests one independently designed, complete result, with Apple, Stripe, and Linear serving as principle references rather than templates. Product facts and working features must remain intact.

Sideband’s color identity comes from independent music publishing and physical records: record-sleeve ivory, wine and aubergine structure, and amber labels. Keep it distinct from Milo’s chalk, carbon, and burnt-orange training identity. Green is reserved for positive evidence and liked feedback; generic selections and taste data use Sideband’s wine and rose family.

## Product Principles

- Bring music and the next useful action forward.
- Keep explanations available without making every listener read model details.
- Preserve deliberate feedback and make changes reversible.
- Tell the truth about uncertainty, storage, and unavailable playback.

## Accessibility & Inclusion

Keyboard access, visible focus, readable contrast, responsive desktop/mobile layouts, reduced motion, and clear loading, empty, error, success, and disabled states are required by the brief.

## Evidence on Hand

README.md, RUNNING.md, frontend and engine source, existing tests, the live app, and a labeled synthetic demo. No testimonials or commercial claims are supplied.

## Listening desk redesign — October 2026

The main weekly view is a finite listening workspace: one active artist, a numbered queue, previous/next navigation, immediate choices, persistent active position, keepers and reversible decisions. The shared masthead exposes the preferred music service on every route. More songs can expand and collapse. Saved choices support search, artist/song scope, verdict filtering and incremental display. All seven routes and the original backend remain available.

Success means selecting a favourite and reaching discoveries, deciding and undoing without losing position, returning to keepers quickly, and recovering from unavailable previews or service errors. Assumed usage is short mobile discovery sessions and longer desktop listening. These assumptions come from existing features; no demographic claims are made. The record logo and established ivory/wine/aubergine/amber brand remain requirements. This redesign replaces the navigation and weekly composition, not product facts or engine contracts.
