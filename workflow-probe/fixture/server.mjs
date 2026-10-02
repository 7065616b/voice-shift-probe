import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, extname, isAbsolute, relative, resolve, sep } from 'node:path';

const fixtureDir = dirname(fileURLToPath(import.meta.url));
const profiles = new Set(['healthy', 'total-drift', 'duplicate-save', 'reload-loss', 'cosmetic-only']);
const items = Object.freeze([
  { id: 'microphone', name: '마이크', price: 19000, quantity: 1 },
  { id: 'cable', name: '케이블', price: 5000, quantity: 2 },
  { id: 'notebook', name: '노트', price: 3000, quantity: 1 },
]);
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.zip': 'application/zip' };

function send(res, status, body, contentType = 'application/json; charset=utf-8') {
  res.writeHead(status, { 'content-type': contentType, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
  res.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

function sessionFor(url, sessions) {
  const profile = url.searchParams.get('profile') ?? 'healthy';
  const session = url.searchParams.get('session');
  if (!profiles.has(profile) || !session || !/^[a-zA-Z0-9_-]{1,100}$/.test(session)) return null;
  const key = `${profile}:${session}`;
  if (!sessions.has(key)) sessions.set(key, { orders: [], seenIntents: new Set() });
  return { profile, state: sessions.get(key) };
}

async function serveFile(res, filePath) {
  try {
    const contents = await readFile(filePath);
    send(res, 200, contents, mime[extname(filePath)] ?? 'application/octet-stream');
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'EISDIR') send(res, 404, { error: 'File not found' });
    else send(res, 500, { error: 'Could not read file' });
  }
}

export async function startFixture({ port = 0, host = '127.0.0.1', reportDir } = {}) {
  const sessions = new Map();
  const root = reportDir === undefined ? null : resolve(reportDir);
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? '/', 'http://localhost');
      if (req.method === 'GET' && url.pathname === '/') {
        await serveFile(res, resolve(fixtureDir, 'index.html'));
        return;
      }
      if (req.method === 'GET' && url.pathname === '/app.js') {
        await serveFile(res, resolve(fixtureDir, 'app.js'));
        return;
      }
      if (req.method === 'GET' && url.pathname === '/style.css') {
        await serveFile(res, resolve(fixtureDir, 'style.css'));
        return;
      }
      if (req.method === 'GET' && root && (url.pathname === '/report' || url.pathname.startsWith('/report/'))) {
        let suffix;
        try { suffix = decodeURIComponent(url.pathname.slice('/report'.length)); }
        catch { send(res, 400, { error: 'Invalid path' }); return; }
        if (suffix.includes('\0') || suffix.includes('\\')) { send(res, 400, { error: 'Invalid path' }); return; }
        const target = resolve(root, `.${suffix === '' || suffix === '/' ? '/index.html' : suffix}`);
        const rel = relative(root, target);
        if (rel === '..' || rel.startsWith(`..${sep}`) || isAbsolute(rel)) { send(res, 403, { error: 'Outside report directory' }); return; }
        await serveFile(res, target);
        return;
      }
      if (url.pathname === '/api/orders' && (req.method === 'GET' || req.method === 'POST')) {
        const selected = sessionFor(url, sessions);
        if (!selected) { send(res, 400, { error: 'Valid profile and session are required' }); return; }
        const { profile, state } = selected;
        if (req.method === 'GET') {
          // One deliberately wrong presentation rule: a reload hides saved orders.
          const hidden = profile === 'reload-loss' && url.searchParams.get('reloaded') === '1';
          send(res, 200, { items, orders: hidden ? [] : state.orders });
          return;
        }
        let raw = '';
        for await (const chunk of req) {
          raw += chunk;
          if (raw.length > 4096) { send(res, 413, { error: 'Body too large' }); return; }
        }
        let body;
        try { body = JSON.parse(raw); }
        catch { send(res, 400, { error: 'Invalid JSON' }); return; }
        if (typeof body.intentId !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(body.intentId)) {
          send(res, 400, { error: 'Valid intentId is required' }); return;
        }
        // Delayed response makes two rapid clicks observable; storage is updated
        // synchronously first so concurrent requests cannot race past deduplication.
        if (profile === 'duplicate-save' || !state.seenIntents.has(body.intentId)) {
          state.orders.push({ id: `order-${state.orders.length + 1}`, intentId: body.intentId, total: 32000 });
          state.seenIntents.add(body.intentId);
        }
        await new Promise((done) => setTimeout(done, 80));
        send(res, 200, { orders: state.orders });
        return;
      }
      send(res, 404, { error: 'Route not found' });
    } catch {
      if (!res.headersSent) send(res, 500, { error: 'Fixture error' });
      else res.end();
    }
  });
  await new Promise((accept, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => { server.off('error', reject); accept(); });
  });
  const address = server.address();
  return {
    url: `http://${host}:${address.port}`,
    close: () => new Promise((done, reject) => server.close((error) => error ? reject(error) : done())),
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const reportDir = process.env.WORKFLOW_PROBE_REPORT_DIR ?? resolve(fixtureDir, '../report');
  const port = Number(process.env.PORT ?? 8787);
  const fixture = await startFixture({ port, reportDir });
  process.stdout.write(`Workflow Probe fixture: ${fixture.url}\n`);
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, async () => { await fixture.close(); process.exit(0); });
}
