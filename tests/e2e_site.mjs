// Browser end-to-end test of the hosted build, on an emulated phone: start instantly from a few
// picked artists (no Spotify export, no API key), then add the export later.
//   node tests/e2e_site.mjs http://127.0.0.1:8888 path/to/my_spotify_data.zip out_dir '["Artist", ...]'
import { execSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium, devices } = require(execSync("npm root -g").toString().trim() + "/playwright");
const [base, zipPath, outDir, picksJson] = process.argv.slice(2);
const picks = JSON.parse(picksJson);
const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const check = (cond, msg) => { if (!cond) throw new Error("FAILED: " + msg); log("ok:", msg); };

const browser = await chromium.launch({ args: ["--no-proxy-server"] });
const context = await browser.newContext({ ...devices["iPhone 13"] });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/fonts\.g/.test(m.text())) errors.push(m.text()); });

async function waitForJob(limitMs) {
  await page.waitForSelector("#job-strip:not([hidden])", { timeout: 30_000 });
  let lastStep = "";
  const start = Date.now();
  while (await page.locator("#job-strip:not([hidden])").count()) {
    const step = await page.locator("#job-step").innerText().catch(() => "");
    if (step !== lastStep) { log("progress:", step, await page.locator("#job-count").innerText().catch(() => "")); lastStep = step; }
    await page.waitForTimeout(1000);
    if (Date.now() - start > limitMs) throw new Error("job took too long");
  }
  return (Date.now() - start) / 1000;
}

await page.goto(base + "/");
await page.waitForSelector("#artist-grid button", { timeout: 120_000 });
check(true, "engine booted and showed Setup");
check((await page.locator("#key, input[type=password]").count()) === 0, "no API key to enter");
check(await page.locator("#build").isDisabled(), "nothing to build before any pick");

// 1. Instant start: pick favourites by searching for them.
// This synthetic catalog uses generated names, reached through the main artist search.
for (const name of picks) {
  await page.fill("#pick-q", name.toLowerCase());
  const row = page.locator(`#pick-results li[data-name="${name.replace(/"/g, '\\"')}"]`);
  await row.waitFor({ timeout: 30_000 });
  await row.locator("button[data-pick=love]").click();
  await page.waitForFunction((n) => [...document.querySelectorAll("#pick-chips .pick-chip.love")].some((c) => c.textContent.includes(n)), name, { timeout: 30_000 });
}
check(true, `picked ${picks.length} favourite artists by searching`);
await page.screenshot({ path: `${outDir}/site-picks.png` });

await page.click("#build");
log(`map from picks built in ${(await waitForJob(600_000)).toFixed(0)}s`);
await page.waitForSelector(".rec", { timeout: 60_000 });
check(await page.locator("#batch-size").inputValue() === "10", "starts with a manageable list of ten artists");
await page.selectOption("#batch-size", "30");
await page.waitForFunction(() => document.querySelectorAll(".rec").length >= 20, null, { timeout: 60_000 });
let recs = await page.locator(".rec-name").allInnerTexts();
check(recs.length >= 20, `${recs.length} recommendations from picks alone`);
check(!recs.some((r) => picks.includes(r)), "picked artists are not recommended back");
check((await page.locator(".view-head p").first().innerText()).includes("you picked"), "says what the picks are based on");
await page.screenshot({ path: `${outDir}/site-foryou-picks.png` });

await page.locator(".rec").first().locator("button[data-act=like]").click();
await page.waitForFunction(() => document.querySelector(".rec .rec-state")?.textContent.includes("liked 1"), null, { timeout: 60_000 });
check(true, "rating saved");
await page.locator(".rec").first().locator("button[data-act=undo]").click();
await page.waitForFunction(() => document.querySelector(".rec .rec-state")?.textContent.includes("liked 0"), null, { timeout: 60_000 });
check(await page.locator(".rec").first().locator("button[data-act=undo]").isHidden(), "rating can be undone without deleting the other ratings");
await page.locator(".rec").first().locator("button[data-act=like]").click();
await page.waitForFunction(() => document.querySelector(".rec .rec-state")?.textContent.includes("liked 1"), null, { timeout: 60_000 });

await page.goto(base + "/#songs");
await page.waitForSelector(".song", { timeout: 120_000 });
check((await page.locator(".song").count()) > 10, "songs listed");

await page.goto(base + "/#explore");
await page.waitForSelector("#tag-form", { timeout: 60_000 });
await page.fill("#tag-input", "jazz");
await page.click("#tag-form button");
await page.waitForSelector("#tag-result .rec", { timeout: 120_000 });
check(true, "genre search returned gateway artists");

await page.goto(base + "/#taste");
await page.waitForSelector("text=Your taste so far", { timeout: 60_000 });
check(true, "taste page works with picks only");

await page.goto(base + "/#accuracy");
await page.waitForSelector("#run-eval", { timeout: 60_000 });
check(await page.locator("#run-eval").isDisabled(), "accuracy test waits for the Spotify export");

// 2. Later, the Spotify export arrives: add it, and the map is updated with it.
await page.goto(base + "/#setup");
await page.locator("#history-details summary").click();
await page.waitForSelector("#drop", { timeout: 60_000 });
await page.setInputFiles("#files", zipPath);
await page.waitForFunction(() => /plays \(/.test(document.querySelector("#file-log")?.textContent || ""), null, { timeout: 180_000 });
log("import:", await page.locator("#file-log").innerText());
await page.waitForFunction(() => /Update|Improve/.test(document.querySelector("#build")?.textContent || ""), null, { timeout: 30_000 });
check(true, "offers to update the recommendations");
check((await page.locator("#pick-chips .pick-chip.love").count()) === picks.length, "picks kept after importing");
await page.click("#build");
log(`map with history built in ${(await waitForJob(900_000)).toFixed(0)}s`);
await page.waitForSelector(".rec", { timeout: 60_000 });
recs = await page.locator(".rec-name").allInnerTexts();
check(recs.length >= 20, `${recs.length} recommendations with history`);
await page.screenshot({ path: `${outDir}/site-foryou.png` });

await page.goto(base + "/#taste");
await page.waitForSelector(".tiles", { timeout: 60_000 });
check(true, "taste profile rendered");

// a fresh visit must find everything saved in the browser
await page.goto("about:blank");
await page.waitForTimeout(1500);
await page.goto(base + "/#for-you");
await page.waitForSelector(".rec", { timeout: 120_000 });
check(await page.locator(".rec-name").first().innerText() !== "", "data and map survived a page reload");
check(await page.locator("#batch-size").inputValue() === "30", "artists-per-list preference survives a page reload");

await page.goto(base + "/#accuracy");
await page.waitForSelector("#run-eval", { timeout: 60_000 });
await page.click("#run-eval");
const evalStart = Date.now();
await page.waitForSelector("#job-strip:not([hidden])", { timeout: 30_000 });
while (await page.locator("#job-strip:not([hidden])").count()) {
  await page.waitForTimeout(2000);
  if (Date.now() - evalStart > 1_500_000) throw new Error("accuracy test took too long");
}
log(`accuracy test finished in ${((Date.now() - evalStart) / 1000).toFixed(0)}s`);
await page.goto(base + "/#accuracy");
await page.waitForSelector(".summary p", { timeout: 60_000 });
log("summary:", (await page.locator(".summary p").first().innerText()).slice(0, 200));
await page.screenshot({ path: `${outDir}/site-accuracy.png`, fullPage: false });

check(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
await browser.close();
log("ALL PASSED");
