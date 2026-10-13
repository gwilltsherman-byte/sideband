import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('cached worker keeps requested startup parameters and API responses are never cached', async () => {
  const handlers = {};
  const cached = new Response('worker code', { headers: { 'Content-Type': 'text/javascript' } });
  Object.defineProperty(cached, 'url', { value: 'https://example.com/sideband/static/worker.js' });
  const cache = { match: async () => cached };
  const self = { registration: { scope: 'https://example.com/sideband/' }, addEventListener: (name, fn) => { handlers[name] = fn; } };
  const source = readFileSync(new URL('../../musicfinder/web/sw.js', import.meta.url), 'utf8')
    .replace('__VERSION__', 'test').replace('__SHELL__', JSON.stringify(['static/worker.js', 'index.html']));
  vm.runInNewContext(source, { self, URL, Response, caches: { open: async () => cache }, fetch: () => { throw new Error('Offline'); } });
  let response;
  handlers.fetch({ request: new Request('https://example.com/sideband/static/worker.js?v=build&pyodide=versioned'), respondWith: value => { response = value; } });
  const result = await response;
  assert.equal(result.url, '');
  assert.equal(await result.text(), 'worker code');
  let intercepted = false;
  handlers.fetch({ request: new Request('https://example.com/sideband/api/proxy?config=1'), respondWith: () => { intercepted = true; } });
  assert.equal(intercepted, false);
});
