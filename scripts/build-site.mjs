// Builds the hosted  version of musicfinder into ./site
//
//   npm install && npm run build
//
// The site is static: the page, the Python package (run in the browser by Pyodide), and Pyodide
// itself, copied from node_modules so the site doesn't depend on a third-party CDN. The only
// server-side piece is server/proxy.mjs, the relay to the music-data services.

import { createHash } from "node:crypto";
import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.join(root, "site");
const web = path.join(root, "musicfinder", "web");

// Python modules the browser never needs (local web server and command line).
const SKIP_PY = new Set(["musicfinder/server.py", "musicfinder/cli.py", "musicfinder/__main__.py"]);
const WEB_FILES = ["app.js", "ui-state.js", "artist-picker.js", "listening-signals.js", "preview-state.js", "browser-api.js", "worker.js", "style.css", "manifest.webmanifest",
  "brand-mark.svg", "favicon.svg", "icon-180.png", "icon-192.png", "icon-512.png", "dm-sans-regular.ttf", "dm-sans-semibold.ttf", "fraunces-medium.ttf", "dm-sans-OFL.txt", "fraunces-OFL.txt"];
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
    throw new Error("Pyodide is missing: run `npm install` first.");
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
  for (const f of [...WEB_FILES, "sw.js"]) hash.update(await readFile(path.join(web, f)));
  hash.update(await readFile(path.join(web, "index.html")));
  const version = hash.digest("hex").slice(0, 12);
  await writeFile(path.join(out, "py", "manifest.json"), JSON.stringify({ version, files }, null, 1));

  // 2. Pyodide, under a versioned path so it can be cached forever
  const pyodideOut = path.join(out, "pyodide", pyodideVersion);
  await mkdir(pyodideOut, { recursive: true });
  for (const f of PYODIDE_FILES) await cp(path.join(pyodideDir, f), path.join(pyodideOut, f));

  // 3. the page
  for (const f of WEB_FILES) {
    if (["app.js", "listening-signals.js", "preview-state.js"].includes(f)) {
      const source = (await readFile(path.join(web, f), "utf8"))
        .replace('from "./ui-state.js"', `from "./ui-state.js?v=${version}"`)
        .replace('from "./artist-picker.js"', `from "./artist-picker.js?v=${version}"`)
        .replace('from "./listening-signals.js"', `from "./listening-signals.js?v=${version}"`)
        .replace('from "./preview-state.js"', `from "./preview-state.js?v=${version}"`)
        .replace('import("./browser-api.js")', `import("./browser-api.js?v=${version}")`);
      await writeFile(path.join(out, "static", f), source);
    } else await cp(path.join(web, f), path.join(out, "static", f));
  }
  let html = await readFile(path.join(web, "index.html"), "utf8");
  const head = [
    `<script>window.MUSICFINDER_MODE = "browser"; window.MUSICFINDER_VERSION = "${version}";`
      + ` window.MUSICFINDER_PYODIDE = new URL("./pyodide/${pyodideVersion}/", location.href).href;`
      + ` window.MUSICFINDER_RELAY = ${JSON.stringify(process.env.SIDEBAND_RELAY_URL || "")};</script>`,
    `<link rel="manifest" href="./static/manifest.webmanifest">`,
    `<link rel="apple-touch-icon" href="./static/icon-180.png">`,
    `<meta name="apple-mobile-web-app-capable" content="yes">`,
    `<meta name="mobile-web-app-capable" content="yes">`,
  ].join("\n  ");
  if (!html.includes("</head>")) throw new Error("index.html has no </head>");
  html = html.replaceAll('="/static/', '="./static/');
  for (const f of ["app.js", "style.css", "favicon.svg"]) html = html.replaceAll(`="./static/${f}"`, `="./static/${f}?v=${version}"`);
  html = html.replace("</head>", `  ${head}\n</head>`);
  await writeFile(path.join(out, "index.html"), html);
  await writeFile(path.join(out, ".nojekyll"), "");
  const shell = ["index.html", "py/manifest.json", ...files.map(f => `py/${f}`),
    ...WEB_FILES.map(f => `static/${f}`), ...PYODIDE_FILES.map(f => `pyodide/${pyodideVersion}/${f}`)];
  const serviceWorker = (await readFile(path.join(web, "sw.js"), "utf8"))
    .replace('__VERSION__', `${version}-${pyodideVersion}`)
    .replace('__SHELL__', JSON.stringify(shell));
  await writeFile(path.join(out, "sw.js"), serviceWorker);


  let bytes = 0;
  for (const f of PYODIDE_FILES) bytes += (await stat(path.join(pyodideOut, f))).size;
  console.log(`Built ./site (version ${version}): ${files.length} Python files, Pyodide ${pyodideVersion}`
    + ` (${(bytes / 1e6).toFixed(1)} MB before compression).`);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
