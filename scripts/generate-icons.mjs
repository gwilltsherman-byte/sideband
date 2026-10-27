// node scripts/generate-icons.mjs [absolute path to sharp's entry point]
import { readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const { default: sharp } = await import(process.argv[2] ? pathToFileURL(process.argv[2]).href : "sharp");
const source = await readFile(new URL("../docs/brand/app-icon.svg", import.meta.url));
const root = new URL("../musicfinder/web/", import.meta.url);
for (const size of [180, 192, 512]) {
  await sharp(source).resize(size, size).png().toFile(new URL(`icon-${size}.png`, root).pathname);
}
const mark = source.toString().match(/<path\b[^>]*\/>/)[0];
const favicon = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64" role="img" aria-label="Sideband"><rect width="64" height="64" rx="14" fill="#ff3d7f"/><g transform="translate(-6.4 -6.4) scale(1.2)">${mark}</g></svg>\n`;
await writeFile(new URL("favicon.svg", root), favicon);
console.log("Generated Sideband install icons and favicon.");
