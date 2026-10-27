import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = (await readFile(new URL("../../musicfinder/web/browser-api.js", import.meta.url), "utf8"))
  .replaceAll('import.meta.url', '"http://localhost/static/browser-api.js"')
  .replaceAll("export ", "") + "\nglobalThis.bridge = { request };";

function bridge() {
  let worker;
  const sandbox = { URL, URLSearchParams, Blob, TextEncoder,
    location: { search: "" }, window: {}, navigator: {},
    document: { querySelector: () => null, addEventListener() {} },
    Worker: class { constructor() { worker = this; } postMessage() {} },
  };
  vm.runInNewContext(source, sandbox);
  return { worker, request: sandbox.bridge.request };
}

test("a worker crash completes pending requests and subsequent calls instead of hanging the UI", async () => {
  const b = bridge();
  const pending = b.request("GET", "/api/state");
  b.worker.onerror({ message: "engine stopped" });
  assert.equal((await pending).status, 500);
  assert.equal((await b.request("GET", "/api/state")).payload.error, "engine stopped");
});

test("fatal startup and successful responses settle exactly the corresponding requests", async () => {
  const b = bridge();
  const first = b.request("GET", "/api/state");
  const second = b.request("GET", "/api/profile");
  b.worker.onmessage({ data: { type: "response", id: 2, status: 200, payload: { plays: 12 } } });
  assert.equal((await second).payload.plays, 12);
  b.worker.onmessage({ data: { type: "fatal", error: "unavailable" } });
  assert.equal((await first).payload.error, "unavailable");
});
