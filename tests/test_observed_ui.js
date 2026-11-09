'use strict';

// Interaction checks of the shipped script for the "Terminal sessions" page (observed Claude Code sessions).
// The DOM double does not verify layout, focus handling or screen-reader output.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const base = path.join(__dirname, '..', 'dashboard', 'static');
const html = readFileSync(path.join(base, 'index.html'), 'utf8');
const script = readFileSync(path.join(base, 'app.js'), 'utf8');

const TOKEN = 'TESTTOKEN0123456789abcdefghijklmnopqrstuvwxyz';
const HOOK_URL = `http://127.0.0.1:47831/hook/observed/${TOKEN}`;
const HOOK_CONFIG = {url: HOOK_URL, snippet: {hooks: {PermissionRequest: [{hooks: [{type: 'http', url: HOOK_URL}]}]}},
  note: 'Add this hooks block to your own Claude Code settings.'};

function fixture() {
  let document;
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {};
      this.dataset = {}; this.hidden = false; this.disabled = false; this.open = false;
      this.attributes = {}; this.value = ''; this._text = ''; this.className = '';
      this.classList = {toggle() {}};
      this.elements = new Proxy({}, {get: (target, key) => target[key] ||= new Element('input')});
    }
    set textContent(value) {this._text = String(value); this.children = [];}
    get textContent() {return this._text + this.children.map(c => c.textContent).join(' ');}
    set innerHTML(value) {throw new Error('HTML rendering is forbidden in this fixture');}
    append(...children) {for (const child of children) {child.parentElement = this; this.children.push(child);}}
    replaceChildren(...children) {this.children = []; this._text = ''; this.append(...children);}
    setAttribute(key, value) {this.attributes[key] = value;}
    removeAttribute(key) {delete this.attributes[key];}
    addEventListener(name, handler) {(this.listeners[name] ||= []).push(handler);}
    emit(name, event = {}) {return (this.listeners[name] || []).map(handler => handler(event));}
    focus() {document.activeElement = this;}
    click() {this.focus(); return Promise.all(this.emit('click'));}
    showModal() {this.open = true;}
    close() {this.open = false; this.emit('close');}
    closest() {return this.parentElement || this;}
    reportValidity() {return true;}
    querySelectorAll(selector) {
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      if (selector === '*') return descendants;
      if (selector.startsWith('.')) return descendants.filter(e => e.className.split(' ').includes(selector.slice(1)));
      if (selector === '[data-close]') return descendants.filter(e => 'data-close' in e.attributes);
      return descendants.filter(e => selector.split(',').some(tag => e.tagName === tag.trim().toUpperCase()));
    }
  }
  const nodes = new Map();
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]); element.id = match[2];
    element.hidden = /\shidden(?:\s|>)/.test(match[0]);
    element.parentElement = new Element(); nodes.set(element.id, element);
  }
  const dialogs = [...nodes.values()].filter(e => e.tagName === 'DIALOG');
  const views = [...html.matchAll(/<button\b[^>]*data-view="([^"]+)"[^>]*>/g)].map(match => {
    const element = new Element('button'); element.dataset.view = match[1];
    element.hidden = /\shidden(?:\s|>)/.test(match[0]); return element;
  });
  const classes = new Map();
  document = {
    activeElement: null, body: new Element('body'), hidden: false,
    getElementById(id) {assert.ok(nodes.has(id), `HTML element #${id} exists`); return nodes.get(id);},
    createElement(tag) {return new Element(tag);}, addEventListener() {},
    querySelector(selector) {if (!classes.has(selector)) classes.set(selector, new Element()); return classes.get(selector);},
    querySelectorAll(selector) {return selector === 'dialog' ? dialogs : selector === '[data-view]' ? views : [];},
  };
  const calls = [];
  const routes = {};  // 'METHOD /path' -> {status, body} or a function returning one
  const stored = [];
  function fetch(url, options = {}) {
    const method = options.method || 'GET';
    calls.push({url, method, options});
    const route = routes[`${method} ${url}`];
    if (!route) return new Promise(() => {});
    const {status = 200, body} = typeof route === 'function' ? route(options) : route;
    return Promise.resolve({ok: status < 400, status, json: async () => body});
  }
  const storage = {getItem() {return null;}, setItem(key, value) {stored.push([key, value]);}, removeItem() {}};
  const runtime = {document, fetch, setInterval() {}, console, sessionStorage: storage, localStorage: storage,
    Option: class Option extends Element {constructor(label, value) {super('option'); this.textContent = label; this.value = value;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.t={updateView,loadObserved,setProvider(v){providerInfo=v;applyProviderText();},setView(v){view=v;updateView();}};'), runtime);
  return {document, nodes, views, calls, routes, stored, api: runtime.t};
}

const claudeInfo = {provider: 'claude', configured: true, capabilities: {provider: 'claude'}};
const codexInfo = {provider: 'codex', configured: true, capabilities: {provider: 'codex'}};
const noneInfo = {provider: 'none', configured: false, capabilities: {provider: 'none'}};
const T0 = 1700000000;
const session = (extra = {}) => ({id: 's1', project: 'proj-a', first_seen: T0 - 600, last_seen: T0, status: 'active', subagent_seen_at: null, ...extra});
const card = (extra = {}) => ({id: 'a1', session_id: 's1', project: 'proj-a', tool_name: 'Bash', summary: 'ls -la', agent_type: null,
  status: 'pending', decided_by: null, decision: null, outcome: 'unknown', decided_at: null, expires_at: T0 + 900, created_at: T0, warning: null, ...extra});
const snapshot = (extra = {}) => ({enabled: true, reason: null, port: 47831, sessions: [], approvals: [], refused: 0,
  limits: {max_sessions: 256, max_pending: 32, quiet_seconds: 1800}, ...extra});
const flush = () => new Promise(resolve => setImmediate(resolve));

async function open(data, provider = claudeInfo) {
  const f = fixture();
  f.routes['GET /api/observed'] = {body: data};
  f.api.setProvider(provider);
  f.api.setView('observed');
  await flush();
  return f;
}
const all = (f, id) => f.nodes.get(id).querySelectorAll('*');
// The DOM double does not connect the static nodes of index.html to the panel, so the page is the sum of its parts.
const PARTS = ['observed-status', 'observed-port', 'observed-limit', 'observed-error', 'observed-message', 'observed-sessions', 'observed-refused',
  'observed-approvals', 'observed-note', 'observed-snippet-toggle', 'observed-rotate', 'observed-rotate-confirm', 'observed-snippet'];
const pageText = f => PARTS.map(id => f.nodes.get(id).textContent).join(' | ');
const buttonsIn = (f, id) => all(f, id).filter(e => e.tagName === 'BUTTON');
const labels = f => ['observed-sessions', 'observed-approvals', 'observed-rotate-confirm'].flatMap(id => buttonsIn(f, id).map(b => b.textContent));
const toggle = f => f.nodes.get('observed-snippet-toggle');
const rotate = f => f.nodes.get('observed-rotate');
const confirmRotate = f => buttonsIn(f, 'observed-rotate-confirm').find(b => b.textContent === 'Confirm rotate');
const approvalButtons = (f, name) => buttonsIn(f, 'observed-approvals').filter(b => b.textContent === name);

test('nav entry and page are hidden for Codex and for no provider', async () => {
  const nav = f => f.views.find(v => v.dataset.view === 'observed');
  assert.ok(nav(fixture()), 'the nav entry exists in index.html');
  for (const info of [codexInfo, noneInfo, null]) {
    const f = fixture();
    if (info) f.api.setProvider(info);
    assert.equal(nav(f).hidden, true);
    f.api.setView('observed');
    await flush();
    assert.equal(f.nodes.get('observed-panel').hidden, true);
    assert.equal(f.calls.filter(c => c.url.startsWith('/api/observed')).length, 0);
  }
  const g = await open(snapshot());
  assert.equal(nav(g).hidden, false);
  assert.equal(g.nodes.get('observed-panel').hidden, false);
  g.api.setProvider(codexInfo);
  assert.equal(nav(g).hidden, true);
  assert.equal(g.nodes.get('observed-panel').hidden, true);
});

test('off reasons are shown in plain words and a null port is never printed', async () => {
  const phrases = {port_in_use: 'port in use', token_unreadable: 'token file unreadable',
    token_permissions: 'token file has the wrong permissions', listener_error: 'listener error',
    settings_unavailable: 'settings could not be read', settings_invalid: 'settings are invalid'};
  for (const [reason, phrase] of Object.entries(phrases)) {
    const f = await open(snapshot({enabled: false, reason, port: null}));
    assert.equal(f.nodes.get('observed-status').textContent, `Observed sessions off: ${phrase}`);
    assert.ok(!/null|undefined/.test(pageText(f)), pageText(f));
  }
  const off = await open(snapshot({enabled: false, reason: 'port_in_use', port: 47831}));
  assert.ok(off.nodes.get('observed-port').textContent.includes('47831'));
  const on = await open(snapshot());
  assert.match(on.nodes.get('observed-status').textContent, /^Observed sessions on/);
  const unknown = await open(snapshot({enabled: false, reason: '<b>x</b>', port: null}));
  assert.ok(!unknown.nodes.get('observed-status').textContent.includes('<b>'));
  assert.equal(on.nodes.get('observed-limit').textContent, 'Only calls that reach a permission prompt are sent, so in Auto mode this list is not a complete record.');
  assert.ok(on.nodes.get('observed-note').textContent.includes('Changes to the observed port or approval wait apply when the dashboard restarts. After changing the port, rotate the token.'));
});

test('session rows show quiet status, last seen and no subagent count', async () => {
  const f = await open(snapshot({sessions: [
    session({id: 's1', project: 'proj-a', status: 'quiet', subagent_seen_at: T0 - 60}),
    session({id: 's2', project: 'proj-b', status: 'active'}),
    session({id: 's3', project: 'proj-c', status: 'ended'})], refused: 3}));
  const rows = f.nodes.get('observed-sessions').children;
  assert.equal(rows.length, 3);
  assert.ok(rows[0].textContent.includes('proj-a') && rows[0].textContent.includes('quiet'));
  assert.ok(rows[0].textContent.includes('Last seen'));
  assert.ok(rows[0].textContent.includes('subagent activity seen'));
  assert.ok(rows[1].textContent.includes('active') && !rows[1].textContent.includes('subagent'));
  assert.ok(rows[2].textContent.includes('ended'));
  assert.ok(!/\d+\s+subagents?/i.test(pageText(f)));
  assert.ok(f.nodes.get('observed-refused').textContent.includes('3'));
});

test('pending card shows text and Allow and Deny buttons', async () => {
  const f = await open(snapshot({approvals: [card({agent_type: 'reviewer'})]}));
  const text = f.nodes.get('observed-approvals').textContent;
  for (const part of ['Your terminal session', 'proj-a', 'Bash', 'ls -la', 'reviewer', 'Expires', 'may already be answered in the terminal']) {
    assert.ok(text.includes(part), part);
  }
  assert.deepEqual(labels(f).filter(l => ['Allow', 'Deny'].includes(l)), ['Allow', 'Deny']);
});

test('closed card has no buttons', async () => {
  const f = await open(snapshot({approvals: [card({status: 'closed', decided_by: 'timed out'})]}));
  assert.ok(f.nodes.get('observed-approvals').textContent.includes('closed: answered elsewhere or timed out'));
  assert.ok(!labels(f).includes('Allow') && !labels(f).includes('Deny'));
});

test('decided cards show who decided, the outcome and the inference note', async () => {
  const inferred = await open(snapshot({approvals: [card({status: 'closed', decided_by: 'terminal (inferred)', outcome: 'ran', decided_at: T0 + 5})]}));
  let text = inferred.nodes.get('observed-approvals').textContent;
  assert.ok(text.includes('Answered in the terminal (inferred): ran'));
  assert.ok(text.includes('Inferred from later events, not a receipt'));
  assert.ok(!text.includes('closed: answered elsewhere'));
  assert.ok(!labels(inferred).includes('Allow'));
  const notRun = await open(snapshot({approvals: [card({status: 'closed', decided_by: 'terminal (inferred)', outcome: 'not run'})]}));
  assert.ok(notRun.nodes.get('observed-approvals').textContent.includes('Answered in the terminal (inferred): not run'));
  const allowed = await open(snapshot({approvals: [card({status: 'answered', decided_by: 'dashboard', decision: 'allow', outcome: 'ran'})]}));
  text = allowed.nodes.get('observed-approvals').textContent;
  assert.ok(text.includes('Allowed here: ran'));
  assert.ok(!text.includes('Inferred from later events'));
  assert.ok(!labels(allowed).includes('Allow'));
  const denied = await open(snapshot({approvals: [card({status: 'answered', decided_by: 'dashboard', decision: 'deny', outcome: 'not run'})]}));
  assert.ok(denied.nodes.get('observed-approvals').textContent.includes('Denied here: not run'));
  assert.ok(!denied.nodes.get('observed-approvals').textContent.includes('ran although denied here'));
});

test('ran although denied here warning is shown', async () => {
  const f = await open(snapshot({approvals: [card({status: 'answered', decided_by: 'dashboard', decision: 'deny', outcome: 'ran', warning: 'ran although denied here'})]}));
  const text = f.nodes.get('observed-approvals').textContent;
  assert.ok(text.includes('Denied here: ran'));
  assert.ok(text.includes('ran although denied here'));
});

test('Allow and Deny post and a closed response updates the card', async () => {
  const f = await open(snapshot({approvals: [card({id: 'a1'}), card({id: 'a2'})]}));
  f.routes['POST /api/observed/approvals/a1/allow'] = {status: 200, body: {result: 'ok'}};
  f.routes['POST /api/observed/approvals/a2/deny'] = {status: 409, body: {result: 'closed'}};
  const allow1 = approvalButtons(f, 'Allow')[0];
  f.routes['GET /api/observed'] = {body: snapshot({approvals: [card({id: 'a1', status: 'answered', decided_by: 'dashboard', decision: 'allow'}), card({id: 'a2'})]})};
  await allow1.click();
  await flush();
  const posts = f.calls.filter(c => c.method === 'POST');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/api/observed/approvals/a1/allow');
  assert.ok(f.nodes.get('observed-approvals').textContent.includes('Allowed here'));
  // a2 is still shown as pending by the server snapshot, but the 409 closes it locally without buttons
  const deny = approvalButtons(f, 'Deny')[0];
  assert.ok(deny);
  await deny.click();
  await flush();
  assert.equal(f.calls.filter(c => c.method === 'POST').at(-1).url, '/api/observed/approvals/a2/deny');
  assert.ok(f.nodes.get('observed-approvals').textContent.includes('closed: answered elsewhere or timed out'));
  assert.ok(!labels(f).includes('Deny'));
});

test('snippet is fetched only on open and the token is rendered only inside the snippet panel', async () => {
  const f = await open(snapshot({approvals: [card()], sessions: [session()]}));
  f.routes['GET /api/observed/hook-config'] = {body: HOOK_CONFIG};
  assert.equal(f.calls.filter(c => c.url.endsWith('/hook-config')).length, 0);
  assert.ok(!pageText(f).includes(TOKEN));
  await toggle(f).click();
  await flush();
  assert.equal(f.calls.filter(c => c.url.endsWith('/hook-config')).length, 1);
  const snippet = f.nodes.get('observed-snippet');
  assert.ok(snippet.textContent.includes(TOKEN));
  for (const id of ['observed-status', 'observed-port', 'observed-limit', 'observed-note', 'observed-sessions', 'observed-approvals', 'observed-refused', 'observed-error', 'observed-message']) {
    assert.ok(!f.nodes.get(id).textContent.includes(TOKEN), id);
  }
  assert.equal(f.nodes.get('announcement').textContent.includes(TOKEN), false);
  // a poll while open neither refetches the token nor leaks it elsewhere
  await f.api.loadObserved();
  assert.equal(f.calls.filter(c => c.url.endsWith('/hook-config')).length, 1);
  assert.ok(!f.nodes.get('observed-sessions').textContent.includes(TOKEN));
  assert.ok(f.stored.every(([k, v]) => !String(v).includes(TOKEN)));
  // closing clears it
  assert.equal(toggle(f).textContent, 'Hide hook snippet');
  await toggle(f).click();
  assert.ok(!pageText(f).includes(TOKEN));
  assert.equal(snippet.children.length, 0);
  // reopen, then leave the page: cleared again
  await toggle(f).click();
  await flush();
  assert.ok(snippet.textContent.includes(TOKEN));
  f.api.setView('overview');
  assert.ok(!pageText(f).includes(TOKEN));
  assert.equal(snippet.children.length, 0);
});

test('a hook-config response that arrives after the panel closed is not rendered', async () => {
  const f = await open(snapshot());
  let release;
  f.routes['GET /api/observed/hook-config'] = () => ({status: 200, body: HOOK_CONFIG});
  const pending = new Promise(r => {release = r;});
  const original = f.routes['GET /api/observed/hook-config'];
  f.routes['GET /api/observed/hook-config'] = options => { release(); return original(options); };
  const opening = toggle(f).click();
  f.api.setView('overview');
  await opening; await pending; await flush();
  assert.ok(!pageText(f).includes(TOKEN));
});

test('rotating the token asks for confirmation and clears the snippet', async () => {
  const f = await open(snapshot());
  f.routes['GET /api/observed/hook-config'] = {body: HOOK_CONFIG};
  f.routes['POST /api/observed/rotate-token'] = {body: {rotated: true}};
  await toggle(f).click();
  await flush();
  assert.ok(f.nodes.get('observed-snippet').textContent.includes(TOKEN));
  await rotate(f).click();
  assert.equal(f.calls.filter(c => c.url.endsWith('/rotate-token')).length, 0);
  await confirmRotate(f).click();
  await flush();
  assert.equal(f.calls.filter(c => c.url.endsWith('/rotate-token')).length, 1);
  assert.ok(!pageText(f).includes(TOKEN));
  assert.ok(f.nodes.get('observed-message').textContent.includes('rotated'));
});

test('all text is escaped', async () => {
  const evil = '<img onerror=1>';
  const f = await open(snapshot({sessions: [session({project: evil})],
    approvals: [card({project: evil, tool_name: evil, summary: evil, agent_type: evil})]}));
  const elements = PARTS.flatMap(id => all(f, id));
  assert.ok(f.nodes.get('observed-sessions').textContent.includes(evil));
  assert.ok(f.nodes.get('observed-approvals').textContent.includes(evil));
  assert.ok(!elements.some(e => e.tagName === 'IMG'));
});
