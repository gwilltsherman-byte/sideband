# Interface redesign verification

Verified on 2026-10-13 against the redesign branch. Local preview data is isolated from personal listening data. The recommendation screenshots use the explicitly labeled simulated listener.

## Completed checks

- All six routes inspected at desktop and 390 × 844 phone sizes; loaded For you, Songs, Explore, Your taste, Accuracy, and Setup. No page-level horizontal overflow in the final phone check. Wider evidence tables scroll within their own containers.
- Pick and save artists, filter and expand the starter catalog, reload saved choices, review and submit pasted favorites, build recommendations, change list length, rate artist and song results, and Undo.
- Expand recommendation evidence, search for a genre through the mobile shortcut, submit jazz, and reach its recommendation results.
- Switch and retain appearance, inspect light and dark screens, check visible keyboard focus and the keyboard-accessible backup restore trigger. Reduced-motion behavior is implemented for loading, transitions, and genre-result scrolling.
- Combined independent critique and accessibility/code review followed by one coordinated correction and confirmation. Fixed mobile Accuracy overflow, buried mobile search and Setup action, delayed first recommendations, weak field borders, concealed stale-update action, playback labels, and refresh recovery. Final review disposition: ship.
- 43 JavaScript regression tests pass, including hosting/cache behavior, saved settings, catalog selection, feedback ordering, and preview states.
- 110 Python regression tests pass across `test_app_server.py`, `test_picks.py`, `test_recommendation_feedback.py`, `test_song_learning.py`, `test_playback_previews.py`, and `test_backup.py`.
- Production build succeeds (`9a1ade37484a`). Self-hosted fonts and licenses are included in the generated site and content-version cache. No new frontend dependency.

## References and judgment

The [Apple](https://www.apple.com/), [Stripe](https://stripe.com/), and [Linear](https://linear.app/) homepages were opened and visually inspected. The design uses their relevant principles of clear hierarchy, purposeful color, and stable wayfinding. Sideband’s editorial music identity and compact listening workflows are its own.

## Limits

Actual audio playback, a full screen-reader audit, physical iPhone testing, and the complete hosted Pyodide startup path were not verified end to end in this pass. Preview availability and failure behavior are covered by regression tests; synthetic demo recommendations intentionally have no matching audio. Import/backup backend behavior is covered by tests; the UI check did not restore or delete personal data. The design detector reported no findings in the supplied markup/scripts but could not resolve the linked CSS path, so stylesheet review was manual. Production deployment was not performed.

## Repeat

Run `npm run test:js`, the six Python suites listed above, and `npm run build`. Start the local app according to `RUNNING.md`, with a separate test-data directory. Use demo mode for a substantial, clearly labeled dataset. Check the six routes at desktop and phone widths, then exercise pick → build → rate → Undo and genre search.

## Screenshots

- [Setup on desktop](screenshots/overview.jpg)
- [Discoveries on desktop](screenshots/discovery.jpg)
- [Discoveries on a phone](screenshots/discovery-mobile.jpg)

Product constraints live in `PRODUCT.md`; reusable design rules live in `DESIGN.md`.
