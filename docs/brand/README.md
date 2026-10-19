# Sideband logo assets

The offset-band S pairs music’s curved grooves with a forward diagonal cut. Two opposing bands share one silhouette, expressing the way Sideband connects familiar music to something adjacent. The lettering keeps the app’s existing Fraunces identity.

![Sideband identity in light and dark](sideband-identity.png)

## Files

- `../../musicfinder/web/brand-mark.svg`: amber emblem used in the application header.
- `sideband-light.svg`: transparent wine/ink lockup for light backgrounds.
- `sideband-dark.svg`: transparent amber/ivory lockup for dark backgrounds.
- `app-icon.svg`: full-bleed icon master, with mask-safe placement.
- `../../musicfinder/web/favicon.svg`: optically enlarged favicon.
- `../../musicfinder/web/icon-{180,192,512}.png`: installed app icons.

SVG lockups contain outlined Fraunces Medium lettering, so they render without a font download. Keep the existing font license in `../../musicfinder/web/fraunces-OFL.txt` with any redistributed font files. The original vector geometry and outlined lettering were authored locally; PNGs are raster exports, not stock or generated imagery. Their provenance is embedded in the PNG metadata.

For icon updates, render `app-icon.svg` to the three exact PNG dimensions with an SVG renderer (the original exports used Sharp). Keep the opaque ground and preserve the proportions. Re-embed image provenance after replacing any PNG. Rebuild the site to update its content hash and offline cache.

See `../../DESIGN.md` for color, spacing, sizing, and interaction rules.

## Verification

- Browser review: 1440×1000 desktop, 1024×768 compact desktop, 390×844 phone, and 320×720 narrow phone. No header overflow or collision with Appearance. Light and dark treatments inspected.
- The Sideband home link is accessible by name, has a 44px-high target, accepts Enter, and shows a 3px ivory keyboard outline. It uses the existing For you route and its first-use Setup fallback.
- The mark loaded correctly in the running app. The favicon and emblem are served as SVG with `nosniff`, included in the generated site and offline precache. This verifies cache inclusion, not an installed-device offline session.
- All 43 JavaScript tests passed. The production build and asset/HTTP test passed again after final PNG metadata was embedded.
- All app-icon PNGs have the exact target dimensions and opaque backgrounds. At 512px, the amber ink stays within a 171.12px radius, safely inside the 204.8px maskable safe radius. The five shipping logo files total 20,120 bytes.
- Artist selection, reload persistence, and removal were exercised in the local preview.
- Independent finishing review: **ship**. The exported lettering matches the app; amber/aubergine contrast is 9.45:1 and wine/ivory is 8.35:1.
- No animation was introduced. The existing reduced-motion rules remain intact. Real device installation and automatic OS icon refresh were not tested.
- Impeccable’s combined review retained the established type and palette. Its detector reported existing type/radius metadata drift and could not resolve the HTML’s absolute stylesheet path; the stylesheet was also checked directly. No unrelated style migration was made.

[Desktop app](../screenshots/overview.jpg) · [Mobile, light](mobile.jpg) · [Mobile, dark](mobile-dark.jpg)

