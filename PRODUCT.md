# Sideband

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Music listeners who want to discover artists and songs from music they already enjoy. The repository supports both occasional browsing on a phone and repeated listening on a desktop. This audience is inferred from the shipped workflows; no demographic assumptions are made.

## Product Purpose

Turn favorite artists, saved songs, optional listening history, and explicit feedback into useful, explainable discoveries. Success means a listener can choose a favorite, find unfamiliar music, understand why it appeared, listen when a matching preview exists, and refine their taste without losing their place.

## Capabilities and Constraints

- Six existing hash routes: For you, Songs, Explore, Your taste, Accuracy, Setup.
- Offline starter artist catalog; live artist search; favorites and dislikes; bulk text/playlist inputs; optional Spotify ZIP/JSON import.
- Artist and song recommendations, adjustable exploration, feedback and undo, saved ratings, and three distinct song sources.
- Previews appear only after verified matching clips are found; missing, lookup failure, audio failure, retry, and playback are separate states.
- Accuracy results are grounded in ratings and observed history. A candidate percentile is not a like probability. Synthetic demo data must be visibly labeled.
- Plain JavaScript and CSS frontend, Python recommendation engine, browser Pyodide worker or local Python server. Preserve API contracts, data storage, service worker, hosting, routes, and integrations.
- Device-local storage; no automatic cross-device sync. Backups and restore remain available. Music lookup sends artist/song names to the existing services.

## Operating Context

Installed iPhone/Mac web app or browser, desktop and mobile, light and dark environments. No account or Spotify export required to start. Initial music-map creation can take several minutes. Offline access supports saved input; new discovery depends on lookup connectivity.

## Brand Commitments

Sideband is the existing product name. The user requests one independently designed, complete result, with Apple, Stripe, and Linear serving as principle references rather than templates. Product facts and working features must remain intact.

## Product Principles

- Bring music and the next useful action forward.
- Keep explanations available without making every listener read model details.
- Preserve deliberate feedback and make changes reversible.
- Tell the truth about uncertainty, storage, and unavailable playback.

## Accessibility & Inclusion

Keyboard access, visible focus, readable contrast, responsive desktop/mobile layouts, reduced motion, and clear loading, empty, error, success, and disabled states are required by the brief.

## Evidence on Hand

README.md, RUNNING.md, frontend and engine source, existing tests, the live app, and a labeled synthetic demo. No testimonials or commercial claims are supplied.
