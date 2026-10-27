# Sideband icons

The install icon is one white record on pink. `app-icon.svg` is its source. Run `node scripts/generate-icons.mjs` with Sharp available to export the 180px, 192px and 512px icons and the optically enlarged favicon. Exports contain no extra text metadata.

Preserve the opaque background and mask-safe placement. Rebuild the site after replacing an asset to refresh its content hash and offline cache.

Outlined Fraunces lettering and redistributed font files retain the license in `../../musicfinder/web/fraunces-OFL.txt`.
