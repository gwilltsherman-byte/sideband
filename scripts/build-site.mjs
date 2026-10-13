// Builds the hosted (Netlify) version of musicfinder into ./site
//
//   npm install && npm run build
//
// The site is static: the page, the Python package (run in the browser by Pyodide), and Pyodide
// itself, copied from node_modules so the site doesn't depend on a third-party CDN. The only
// server-side piece is netlify/functions/proxy.mjs, the relay to the music-data services.

import { createHash } from "node:crypto";
import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.join(root, "site");
const web = path.join(root, "musicfinder", "web");

// Python modules the browser never needs (local web server and command line).
const SKIP_PY = new Set(["musicfinder/server.py", "musicfinder/cli.py", "musicfinder/__main__.py"]);
const WEB_FILES = ["app.js", "browser-api.js", "worker.js", "style.css", "manifest.webmanifest",
  "icon-180.png", "icon-192.png", "icon-512.png"];
const PYODIDE_FILES = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];

async function walk(dir) {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "__pycache__" && entry.name !== "web") found.push(...await walk(full));
    } else if (entry.name.endsWith(".py")) {
      found.push(full);
    }
  }
  return found;
}

async function main() {
  const pyodideDir = path.join(root, "node_modules", "pyodide");
  let pyodideVersion;
  try {
    pyodideVersion = JSON.parse(await readFile(path.join(pyodideDir, "package.json"), "utf8")).version;
  } catch {
    throw new Error("Pyodide is missing: run `npm install` first (Netlify does this automatically).");
  }

  await rm(out, { recursive: true, force: true });
  await mkdir(path.join(out, "static"), { recursive: true });

  // 1. the Python package, plus a manifest with a content hash for cache-busting
  const hash = createHash("sha256");
  const files = [];
  for (const full of (await walk(path.join(root, "musicfinder"))).sort()) {
    const rel = path.relative(root, full).split(path.sep).join("/");
    if (SKIP_PY.has(rel)) continue;
    const text = await readFile(full);
    hash.update(rel).update(text);
    files.push(rel);
    await mkdir(path.dirname(path.join(out, "py", rel)), { recursive: true });
    await writeFile(path.join(out, "py", rel), text);
  }
  for (const f of WEB_FILES) hash.update(await readFile(path.join(web, f)));
  const version = hash.digest("hex").slice(0, 12);
  await writeFile(path.join(out, "py", "manifest.json"), JSON.stringify({ version, files }, null, 1));

  // 2. Pyodide, under a versioned path so it can be cached forever
  const pyodideOut = path.join(out, "pyodide", pyodideVersion);
  await mkdir(pyodideOut, { recursive: true });
  for (const f of PYODIDE_FILES) await cp(path.join(pyodideDir, f), path.join(pyodideOut, f));

  // 3. the page
  for (const f of WEB_FILES) await cp(path.join(web, f), path.join(out, "static", f));
  let html = await readFile(path.join(web, "index.html"), "utf8");
  const head = [
    `<script>window.MUSICFINDER_MODE = "browser"; window.MUSICFINDER_VERSION = "${version}";`
      + ` window.MUSICFINDER_PYODIDE = "/pyodide/${pyodideVersion}/";</script>`,
    `<link rel="manifest" href="/static/manifest.webmanifest">`,
    `<link rel="apple-touch-icon" href="/static/icon-180.png">`,
    `<meta name="apple-mobile-web-app-capable" content="yes">`,
    `<meta name="mobile-web-app-capable" content="yes">`,
  ].join("\n  ");
  if (!html.includes("</head>")) throw new Error("index.html has no </head>");
  html = html.replace("</head>", `  ${head}\n</head>`);
  await writeFile(path.join(out, "index.html"), html);

  let bytes = 0;
  for (const f of PYODIDE_FILES) bytes += (await stat(path.join(pyodideOut, f))).size;
  console.log(`Built ./site (version ${version}): ${files.length} Python files, Pyodide ${pyodideVersion}`
    + ` (${(bytes / 1e6).toFixed(1)} MB before compression).`);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
