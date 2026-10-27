import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import { createServer } from "../../server/serve.mjs";

test("published HTML and module dependencies request the same content version", async () => {
  execFileSync(process.execPath, ["scripts/build-site.mjs"], { cwd: new URL("../../", import.meta.url) });
  const root = new URL("../../site/", import.meta.url);
  const { version } = JSON.parse(await readFile(new URL("py/manifest.json", root), "utf8"));
  const html = await readFile(new URL("index.html", root), "utf8");
  const app = await readFile(new URL("static/app.js", root), "utf8");
  for (const asset of ["app.js", "style.css", "listening-desk.css", "taste-filters.css", "favicon.svg", "icon-180.png", "manifest.webmanifest"]) assert.ok(html.includes(`./static/${asset}?v=${version}`));
  assert.equal((html.match(/rel="apple-touch-icon"/g) || []).length, 1);
  const manifest = JSON.parse(await readFile(new URL("static/manifest.webmanifest", root), "utf8"));
  assert.deepEqual(manifest.icons.map(icon => icon.src), [192, 512].map(size => `icon-${size}.png?v=${version}`));
  for (const dependency of ["ui-state.js", "artist-picker.js", "listening-signals.js", "preview-state.js", "browser-api.js"]) assert.ok(app.includes(`./${dependency}?v=${version}`));
  const picker = await readFile(new URL("static/artist-picker.js", root), "utf8");
  assert.ok(picker.includes("artistChoices"));
  const signals = await readFile(new URL("static/listening-signals.js", root), "utf8");
  assert.ok(signals.includes(`./artist-picker.js?v=${version}`));
  const previews = await readFile(new URL("static/preview-state.js", root), "utf8");
  assert.ok(previews.includes(`./listening-signals.js?v=${version}`));
  const sw = await readFile(new URL("sw.js", root), "utf8");
  assert.ok(sw.includes("static/artist-picker.js"));
  assert.ok(sw.includes("static/listening-signals.js"));
  assert.ok(sw.includes("static/preview-state.js"));
  assert.ok(html.includes(`MUSICFINDER_VERSION = "${version}"`));

  // Standalone SVGs must ship with the offline shell and remain renderable when
  // served with nosniff. An omitted file or generic MIME type breaks the logo.
  const server = createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const size of [180, 192, 512]) {
      const asset = `icon-${size}.png`;
      const source = await readFile(new URL(`../../musicfinder/web/${asset}`, import.meta.url));
      assert.ok(sw.includes(`static/${asset}`));
      assert.equal(source.readUInt32BE(16), size);
      assert.equal(source.readUInt32BE(20), size);
      const response = await fetch(`${base}/static/${asset}?v=${version}`);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("content-type"), "image/png");
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), source);
    }
    for (const asset of ["brand-mark.svg", "favicon.svg"]) {
      const source = await readFile(new URL(`../../musicfinder/web/${asset}`, import.meta.url), "utf8");
      const published = await readFile(new URL(`static/${asset}`, root), "utf8");
      assert.equal(published, source);
      assert.ok(sw.includes(`static/${asset}`));
      const response = await fetch(`${base}/static/${asset}?v=${version}`);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("content-type"), "image/svg+xml");
      assert.equal(response.headers.get("x-content-type-options"), "nosniff");
      assert.equal(await response.text(), source);
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});
