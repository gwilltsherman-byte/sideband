import http from 'node:http';
import { readFile, stat, realpath } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import proxy from './proxy.mjs';

const site = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../site');
const relayOnly = process.argv.includes('--relay-only');
const types = {'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8',
  '.mjs':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8',
  '.json':'application/json','.webmanifest':'application/manifest+json','.wasm':'application/wasm',
  '.png':'image/png','.ttf':'font/ttf','.woff2':'font/woff2','.zip':'application/zip','.py':'text/plain; charset=utf-8'};

export function createServer() {
  return http.createServer(async (req,res) => {
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Referrer-Policy','no-referrer');
    const scheme=req.headers['x-forwarded-proto']==='https'?'https':'http';
    const origin=scheme+'://'+(req.headers.host||'localhost');
    let url;
    try {url=new URL(req.url,origin);} catch {res.writeHead(400);res.end('Invalid URL');return;}
    const allowed=process.env.FRONTEND_ORIGIN||origin;
    const requestOrigin=req.headers.origin;
    if(requestOrigin && requestOrigin!==origin && requestOrigin!==allowed) {
      res.writeHead(403);res.end('Origin is not allowed');return;
    }
    if(requestOrigin) {
      res.setHeader('Access-Control-Allow-Origin',requestOrigin);
      res.setHeader('Vary','Origin');
    }
    if(url.pathname==='/healthz') {res.setHeader('Content-Type','application/json');res.end('{"ok":true}');return;}
    if(url.pathname==='/api/proxy') {
      if(req.method==='OPTIONS') {res.setHeader('Access-Control-Allow-Methods','GET, OPTIONS');res.writeHead(204);res.end();return;}
      const headers=new Headers();
      for(const [key,value] of Object.entries(req.headers))if(value!==undefined)headers.set(key,String(value));
      // A configured frontend origin may call the lookup service from Pages.
      if(requestOrigin===allowed)headers.delete('sec-fetch-site');
      try {
        const answer=await proxy(new Request(url,{method:req.method,headers}));
        res.statusCode=answer.status;
        for(const [key,value] of answer.headers)res.setHeader(key,value);
        res.end(Buffer.from(await answer.arrayBuffer()));
      } catch {res.writeHead(502);res.end('Lookup service unavailable');}
      return;
    }
    if(relayOnly || req.method!=='GET') {res.writeHead(404);res.end('Not found');return;}
    try {
      const filename=path.resolve(site,'.'+decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));
      if(!filename.startsWith(site+path.sep) || !(await stat(filename)).isFile())throw new Error('Not a site file');
      if(!(await realpath(filename)).startsWith(site+path.sep))throw new Error('Not a site file');
      res.setHeader('Content-Type',types[path.extname(filename)]||'application/octet-stream');
      res.end(await readFile(filename));
    } catch {res.writeHead(404);res.end('Not found');}
  });
}

if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const port=Number(process.env.PORT||8765);
  createServer().listen(port,'0.0.0.0',()=>console.log(`Sideband is running at http://localhost:${port}`));
}
