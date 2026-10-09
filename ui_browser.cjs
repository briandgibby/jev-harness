// The single browser owner. RPC is loopback-only; page content grants no authority.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const http = require('http');
const child = require('child_process');
const { chromium } = require('playwright');
const canonical = value => JSON.stringify(value, (_, item) => {
  if (item && typeof item === 'object' && !Array.isArray(item))
    return Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]]));
  return item;
});
const hash = value => crypto.createHash('sha256').update(canonical(value)).digest('hex');
const fileHash = name => crypto.createHash('sha256').update(fs.readFileSync(name)).digest('hex');
const read = name => JSON.parse(fs.readFileSync(name, 'utf8'));
const write = (name, value) => {
  fs.mkdirSync(path.dirname(name), { recursive: true });
  const fd = fs.openSync(name, 'wx', 0o600);
  try { fs.writeFileSync(fd, canonical(value) + '\n'); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
};
const pins = read(path.join(__dirname, 'computer-use-pins.json'));
function doctor() {
  const meta = read(require.resolve('playwright/package.json'));
  const browserMeta = read(path.join(path.dirname(require.resolve('playwright-core/package.json')), 'browsers.json'));
  const revision = browserMeta.browsers.find(item => item.name === 'chromium');
  const executable = chromium.executablePath();
  for (const [name, actual, expected] of [
    ['platform', process.platform + '-' + process.arch, pins.platform],
    ['node_version', process.version, pins.node_version],
    ['playwright_version', meta.version, pins.playwright_version],
    ['chromium_revision', revision.revision, pins.chromium_revision],
    ['chromium_version', revision.browserVersion, pins.chromium_version],
    ['chromium_executable_sha256', fileHash(executable), pins.chromium_executable_sha256]
  ]) if (actual !== expected) throw Error(name + ' differs from computer-use-pins.json; run setup or deliberately update the pin.');
  return { status: 'verified', pins, executable };
}
if (process.argv[2] === '--doctor') {
  try { console.log(canonical(doctor())); } catch (error) { console.error(error.message); process.exitCode = 1; }
} else main().catch(error => { console.error(error.message); process.exit(1); });

async function main() {
  const root = path.resolve(process.argv[2]);
  const admitted = JSON.parse(child.execFileSync('python', ['-B', path.join(__dirname, 'computer_use.py'), 'admit', '--directory', root], { cwd: __dirname, encoding: 'utf8' }));
  if (admitted.status !== 'admitted') throw Error('Fixture admission failed; inspect task/configuration.');
  const {config, task} = admitted;
  const runtime = doctor();
  if (fs.existsSync(path.join(root, 'session.json'))) throw Error('Session already exists; inspect it or reset into a new directory. Restart never retries actions.');
  const owner = fs.openSync(path.join(root, 'owner.lock'), 'wx', 0o600);
  fs.closeSync(owner); // Never removed: a crashed owner cannot be silently replaced.
  const session = {id: crypto.randomUUID(), token: crypto.randomBytes(32).toString('hex')};
  const origin = 'http://127.0.0.1:' + config.port;
  const started = Date.now();
  let previous = null, sequence = 0, steps = 0, cancelled = false, unknown = false, busy = Promise.resolve();
  const event = value => {
    const entry = {sequence: sequence++, previous, created_ms: Date.now(), ...value};
    entry.hash = hash(entry);
    const fd = fs.openSync(path.join(root, 'events.jsonl'), 'a', 0o600);
    try {fs.writeFileSync(fd, canonical(entry) + '\n'); fs.fsyncSync(fd);} finally {fs.closeSync(fd);}
    previous = entry.hash;
  };
  const record = (kind, value) => {
    const item = {schema_version: 1, kind, id: crypto.randomUUID(), created_ms: Date.now(), value};
    const name = path.join(root, 'records', item.id + '.json'); write(name, item); return name;
  };
  const browser = await chromium.launch({headless: config.headless, executablePath: runtime.executable});
  const context = await browser.newContext({viewport: config.viewport, serviceWorkers: 'block', acceptDownloads: false});
  const networkRequests = [];
  const allowedRequests = [], failedRequests = [];
  context.on('request', request => networkRequests.push(request.url()));
  context.on('requestfailed', request => failedRequests.push(request.url()));
  await context.route('**/*', route => {
    if (route.request().url() === origin + '/fixture' && route.request().method() === 'GET') {
      allowedRequests.push(route.request().url()); return route.continue();
    }
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(config.action_timeout_ms);
  const trusted = () => {
    if (fileHash(path.join(root, 'config.json')) !== admitted.config_file_hash ||
        fileHash(path.join(root, 'task.json')) !== admitted.task_file_hash ||
        fileHash(path.join(root, 'fixture.html')) !== admitted.fixture_file_hash)
      throw Error('Admitted task/configuration/fixture changed; reset into a new directory.');
  };
  async function snapshot() {
    trusted();
    if (page.url() !== origin + '/fixture') throw Error('Wrong surface/origin; stop and inspect the session.');
    if (canonical(page.viewportSize()) !== canonical(config.viewport)) throw Error('Viewport changed; reinitialize the fixture.');
    const note = page.getByRole('textbox', {name: 'Synthetic note', exact: true});
    const save = page.getByRole('button', {name: 'Save draft', exact: true});
    for (const [name, locator] of [['note', note], ['save', save]]) {
      if (await locator.count() !== 1) throw Error('Ambiguous or missing target: ' + name + '; inspect the observation.');
      if (!await locator.isVisible() || !await locator.isEnabled()) throw Error('Hidden or disabled target: ' + name + '; inspect the observation.');
    }
    const values = await page.evaluate(() => ({note: document.querySelector('#note').value,
      draft: document.querySelector('#draft').textContent, ...window.fixture}));
    return {url: page.url(), viewport: page.viewportSize(), network_requests: [...networkRequests],
      allowed_requests: [...allowedRequests], failed_requests: [...failedRequests], ...values,
      targets: [{id:'note', role:'textbox', name:'Synthetic note', visible:true, enabled:true, count:1},
                {id:'save', role:'button', name:'Save draft', visible:true, enabled:true, count:1}]};
  }
  async function observe() {
    const value = await snapshot();
    return {session_id: session.id, complete: true, backend: 'playwright-' + pins.playwright_version,
      created_ms: Date.now(), snapshot: value, state_hash: hash(value)};
  }
  function artifact(name, kind) {
    if (typeof name !== 'string' || !/^[0-9a-f-]{36}\.json$/.test(name)) throw Error('Invalid record filename.');
    const item = read(path.join(root, 'records', name));
    if (item.id + '.json' !== name || item.kind !== kind || item.schema_version !== 1) throw Error('Wrong artifact identity or kind.');
    return item;
  }
  async function execute(payload) {
    if (cancelled || fs.existsSync(path.join(root, 'STOP'))) throw Error('Session cancelled; no further actions permitted.');
    if (unknown) throw Error('unknown_outcome: inspect retained intent and reconcile by observation; no retry.');
    const attempts = path.join(root, 'attempts');
    if (fs.existsSync(attempts) && fs.readdirSync(attempts).some(name => name.endsWith('.intent.json') &&
        !fs.existsSync(path.join(attempts, name.replace('.intent.json', '.result.json')))))
      throw Error('unknown_outcome: unacknowledged durable intent prevents further actions; inspect and reset.');
    const permit = artifact(payload.permit, 'ActionPermit'), grant = permit.value;
    const intentPath = path.join(root, 'attempts', permit.id + '.intent.json');
    if (fs.existsSync(intentPath)) throw Error('Permit already consumed; inspect execution, never repeat it.');
    if (Date.now() - started > config.max_run_ms || steps >= config.max_steps) throw Error('max_run_ms or max_steps exceeded; inspect and reset.');
    const observed = artifact(grant.observation, 'UIObservation');
    const action = artifact(grant.action, 'UIAction');
    const now = Date.now();
    if (grant.session_id !== session.id || observed.value.session_id !== session.id ||
        grant.config_hash !== hash(config) || grant.task_hash !== hash(task) ||
        grant.observation_hash !== hash(observed) || grant.action_hash !== hash(action) ||
        grant.state_hash !== observed.value.state_hash || observed.value.complete !== true ||
        now < observed.value.created_ms || now - observed.value.created_ms > config.freshness_ms)
      throw Error('Expired or inconsistent permit/observation; reobserve before issuing another permit.');
    const current = await snapshot();
    if (hash(current) !== grant.state_hash) throw Error('Stale state; reobserve before acting.');
    const expected = current.note !== task.note ? {label:'fill_note', target:'note', argument:task.note} :
      current.draft !== task.note || current.save_count !== 1 ? {label:'save_draft', target:'save', argument:null} : null;
    if (!expected || canonical(action.value) !== canonical(expected)) throw Error('Unsupported or unauthorized action/argument; rules cannot widen task permissions.');
    const decision = artifact(grant.decision, 'JevShadow');
    if (grant.decision_hash !== hash(decision) || decision.value.action_hash !== hash(action)) throw Error('Missing or changed shadow audit mapping.');
    const audit = path.resolve(root, decision.value.audit);
    if (path.dirname(audit) !== path.join(root, 'jev-audit') || fileHash(audit) !== decision.value.audit_hash)
      throw Error('Missing or changed Jev audit; no action permitted.');
    // Durably consume BEFORE effect. No result after this point means unknown_outcome.
    write(intentPath, {permit: payload.permit, permit_hash:hash(permit), pre:current, step:steps + 1});
    steps++; unknown = true;
    event({event:'intent', permit:payload.permit, intent:path.relative(root, intentPath), intent_hash:fileHash(intentPath)});
    try {
      if (expected.label === 'fill_note') await page.getByRole('textbox', {name:'Synthetic note', exact:true}).fill(expected.argument);
      else await page.getByRole('button', {name:'Save draft', exact:true}).click();
      const post = await observe();
      const result = {status:'executed', permit:payload.permit, pre:current, post, step:steps};
      const resultPath = record('UIExecution', result);
      write(path.join(root, 'attempts', permit.id + '.result.json'), {execution:path.basename(resultPath), hash:fileHash(resultPath)});
      event({event:'executed', record:path.relative(root, resultPath), record_hash:fileHash(resultPath)});
      unknown = false;
      return {...result, execution:resultPath};
    } catch (error) {
      event({event:'unknown_outcome', permit:payload.permit, error:'Action or acknowledgement failed; inspect intent and fresh observation. No retry.'});
      throw Error('unknown_outcome: action may have happened; inspect intent and observe. No retry.');
    }
  }
  const server = http.createServer(async (request, response) => {
    if (request.method === 'GET' && request.url === '/fixture') {
      try {trusted(); response.writeHead(200, {'Content-Type':'text/html; charset=utf-8', 'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'"}); response.end(fs.readFileSync(path.join(root, 'fixture.html')));}
      catch (error) {response.writeHead(500); response.end('Fixture integrity failed.');}
      return;
    }
    if (request.method !== 'POST' || request.headers.authorization !== 'Bearer ' + session.token ||
        request.headers.origin || !/^\/rpc\/(observe|execute|stop|capture|shutdown)$/.test(request.url)) {
      response.writeHead(403); response.end('Forbidden'); return;
    }
    let raw = '', tooLarge = false;
    for await (const data of request) {raw += data.toString('utf8'); if (Buffer.byteLength(raw) > 8192) {tooLarge=true; break;}}
    const operation = request.url.slice(5);
    if (operation === 'stop') {cancelled=true; if (!fs.existsSync(path.join(root, 'STOP'))) write(path.join(root,'STOP'), {cancelled_ms:Date.now()});}
    const run = async () => {
      try {
        if (tooLarge) throw Error('RPC payload exceeds 8192 bytes.');
        const payload = JSON.parse(raw);
        let value;
        if (operation === 'observe') value = await observe();
        else if (operation === 'execute') value = await execute(payload);
        else if (operation === 'capture') {
          await snapshot();
          const name = path.join(root, 'captures', crypto.randomUUID() + '.png');
          fs.mkdirSync(path.dirname(name), {recursive:true});
          await page.screenshot({path:name});
          value = {status:'captured', path:name, sha256:fileHash(name), provider_called:false};
          record('Capture', value);
        }
        else value = {status:operation === 'stop' ? 'cancelled' : 'stopped'};
        response.writeHead(200, {'Content-Type':'application/json'}); response.end(canonical(value));
        if (operation === 'shutdown') {await browser.close(); server.close();}
      } catch (error) {
        event({event:'failed', operation, error:error.message});
        response.writeHead(200, {'Content-Type':'application/json'}); response.end(canonical({status:'failed', error:error.message}));
      }
    };
    busy = busy.then(run, run);
  });
  await new Promise((resolve, reject) => {server.once('error', reject); server.listen(config.port, '127.0.0.1', resolve);});
  await page.goto(origin + '/fixture', {timeout:config.action_timeout_ms});
  write(path.join(root, 'session.json'), session);
  event({event:'ready', session_id:session.id, config_hash:hash(config), task_hash:hash(task), fixture_hash:admitted.fixture_file_hash, pins_hash:hash(pins)});
  console.log(canonical({status:'ready', directory:root, origin, session_id:session.id}));
  process.on('SIGTERM', () => {browser.close().finally(() => server.close());});
}
