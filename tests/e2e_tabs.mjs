// Two open copies of the hosted app must never overwrite each other's saved data.
//   node tests/e2e_tabs.mjs http://127.0.0.1:8888 path/to/small_history.json
import { execSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(execSync("npm root -g").toString().trim() + "/playwright");
const [base, jsonPath] = process.argv.slice(2);
const check = (cond, msg) => { if (!cond) throw new Error("FAILED: " + msg); console.log("ok:", msg); };

const browser = await chromium.launch({ args: ["--no-proxy-server"] });
const context = await browser.newContext(); // one profile: the tabs share IndexedDB, like a real browser
const open = async (hash = "#setup") => {
  const p = await context.newPage();
  await p.goto(base + "/" + hash);
  await p.waitForSelector("#artist-grid button, .rec, .empty", { timeout: 120_000 });
  return p;
};
const plays = async (p) => p.evaluate(async () => (await (await import("/static/browser-api.js")).request("GET", "/api/state")).payload.plays);

// Scenario 1 (the reviewers' reproduction): tab A imports, tab B deletes, then tab A is used again and
// autosaves. Before the fix, A's stale copy overwrote B's deletion and the "deleted" history came back.
const a = await open();
await a.setInputFiles("#files", jsonPath);
await a.waitForFunction(() => /plays \(/.test(document.querySelector("#file-log")?.textContent || ""), null, { timeout: 120_000 });
await a.waitForTimeout(1500);
const b = await open();
if (!process.env.OLD_CODE) {
  await a.waitForSelector("#elsewhere", { timeout: 15_000 });
  check(true, "the older tab is told the app was opened elsewhere");
}
check((await plays(b)) > 0, "the newer tab sees the data imported in the older one");
await b.evaluate(async () => (await import("/static/browser-api.js")).request("POST", "/api/clear", { what: "data" }));
await b.waitForTimeout(1500);
await a.evaluate(() => { location.hash = "#taste"; });
await a.waitForTimeout(25_000); // longer than the autosave interval
await b.close();
await a.close();
const c = await open();
check((await plays(c)) === 0, "a deletion made in the newer tab stays deleted after the older tab is used");
if (process.env.OLD_CODE) { await browser.close(); process.exit(0); }

// Scenario 2: the old tab is reused ("Use it here instead"): it takes over cleanly with the latest data.
const d = await open();
await c.waitForSelector("#elsewhere", { timeout: 15_000 });
await d.evaluate(async () => (await import("/static/browser-api.js")).request("POST", "/api/clear", { what: "data" }));
await c.click("#elsewhere button");
await c.waitForSelector("#artist-grid button", { timeout: 120_000 }); // Setup is shown again
await d.waitForSelector("#elsewhere", { timeout: 15_000 });
check((await plays(c)) === 0, "taking over in the old tab picks up the deletion made in the newer tab");
await browser.close();
console.log("ALL PASSED");
