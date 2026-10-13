import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";

test("published HTML and module dependencies request the same content version", async () => {
  execFileSync(process.execPath, ["scripts/build-site.mjs"], { cwd: new URL("../../", import.meta.url) });
  const root = new URL("../../site/", import.meta.url);
  const { version } = JSON.parse(await readFile(new URL("py/manifest.json", root), "utf8"));
  const html = await readFile(new URL("index.html", root), "utf8");
  const app = await readFile(new URL("static/app.js", root), "utf8");
  for (const asset of ["app.js", "style.css"]) assert.ok(html.includes(`./static/${asset}?v=${version}`));
  for (const dependency of ["ui-state.js", "browser-api.js"]) assert.ok(app.includes(`./${dependency}?v=${version}`));
  assert.ok(html.includes(`MUSICFINDER_VERSION = "${version}"`));
});
