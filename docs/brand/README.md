# Sideband logo assets

The mark is a plain record: a white disc with a hot-pink label, on a bright coral ground for icons. It stands for the music you already love, Sideband's starting point, and is kept simple so it reads at any size. The lettering keeps the app’s existing Fraunces identity.

![Sideband identity in light and dark](sideband-identity.png)

## Files

- `../../musicfinder/web/brand-mark.svg`: white-and-pink record used in the application header.
- `sideband-light.svg`: transparent coral record and ink lockup for light backgrounds.
- `sideband-dark.svg`: transparent white record and ivory lockup for dark backgrounds.
- `app-icon.svg`: full-bleed icon master, with mask-safe placement.
- `../../musicfinder/web/favicon.svg`: optically enlarged favicon.
- `../../musicfinder/web/icon-{180,192,512}.png`: installed app icons.

SVG lockups contain outlined Fraunces Medium lettering, so they render without a font download. Keep the existing font license in `../../musicfinder/web/fraunces-OFL.txt` with any redistributed font files. The original vector geometry and outlined lettering were authored locally; PNGs are raster exports, not stock or generated imagery. Their provenance is embedded in the PNG metadata.

For icon updates, render `app-icon.svg` to the three exact PNG dimensions with an SVG renderer (the current exports used Chromium via Playwright). Keep the opaque ground and preserve the proportions. Re-embed image provenance after replacing any PNG. Rebuild the site to update its content hash and offline cache.

See `../../DESIGN.md` for color, spacing, sizing, and interaction rules.

## Verification

- Browser review in Chromium: 1440×1000 desktop and 390×844 phone, light and dark. The mark sits in the existing 32px header box with no layout change; no overflow or collision with Appearance.
- The mark was compared at display, 32px and 16px sizes across several bright colorways; coral with a pink label was chosen because it stays bright without reading as a fried egg (white and yellow).
- The favicon and emblem are still served as SVG with `nosniff` and included in the generated site and offline precache (covered by `tests/js/build.test.mjs`).
- All 48 JavaScript tests passed and the production build succeeded.
- All app-icon PNGs have the exact target dimensions and opaque backgrounds. At 512px the white disc has a 153.6px radius, inside the 204.8px maskable safe radius.
- The interface palette is unchanged; coral and pink are used only in the logo.
- No animation was introduced. Real device installation and automatic OS icon refresh were not tested.

[Desktop app](../screenshots/overview.jpg) · [Mobile, light](mobile.jpg) · [Mobile, dark](mobile-dark.jpg)

