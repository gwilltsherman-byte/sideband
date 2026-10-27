import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { createServer } from '../../server/serve.mjs';

test('lookup server permits the configured Pages origin and rejects other sites', async () => {
  const old=process.env.FRONTEND_ORIGIN;
  process.env.FRONTEND_ORIGIN='https://gwilltsherman-byte.github.io';
  const server=createServer();server.listen(0,'127.0.0.1');await once(server,'listening');
  const base='http://127.0.0.1:'+server.address().port;
  try {
    const denied=await fetch(base+'/api/proxy?config=1',{headers:{origin:'https://attacker.example'}});
    assert.equal(denied.status,403);
    const allowed=await fetch(base+'/api/proxy?config=1',{headers:{origin:process.env.FRONTEND_ORIGIN,'sec-fetch-site':'cross-site'}});
    assert.equal(allowed.status,200);
    assert.equal(allowed.headers.get('access-control-allow-origin'),process.env.FRONTEND_ORIGIN);
    assert.equal(typeof (await allowed.json()).lastfm,'boolean');
    assert.equal((await fetch(base+'/api/proxy?url=https://example.com/')).status,400);
    assert.equal((await fetch(base+'/api/proxy?config=1',{method:'POST'})).status,405);
    assert.equal((await fetch(base+'/%2e%2e%2fpackage.json')).status,404);
  } finally {
    await new Promise(resolve=>server.close(resolve));
    if(old===undefined)delete process.env.FRONTEND_ORIGIN;else process.env.FRONTEND_ORIGIN=old;
  }
});

test('browser package paths work beneath a Pages project directory',()=>{
  const api=readFileSync(new URL('../../musicfinder/web/browser-api.js',import.meta.url),'utf8');
  const worker=readFileSync(new URL('../../musicfinder/web/worker.js',import.meta.url),'utf8');
  assert.ok(api.includes('new URL("./worker.js", import.meta.url)'));
  assert.ok(worker.includes('new URL("../", import.meta.url)'));
  assert.ok(!worker.includes('fetch(`/py/'));
  const manifest=JSON.parse(readFileSync(new URL('../../musicfinder/web/manifest.webmanifest',import.meta.url),'utf8'));
  assert.equal(manifest.start_url,'../');
  assert.ok(manifest.icons.every(i=>!i.src.startsWith('/')));
});
