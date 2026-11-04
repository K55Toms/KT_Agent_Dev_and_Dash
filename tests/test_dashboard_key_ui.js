'use strict';

// Dashboard key in the page (docs/dashboard-api.md, "Dashboard key"). A small DOM double runs the shipped scripts;
// it does not verify a real browser's history, storage or CSP behaviour.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const base = path.join(__dirname, '..', 'dashboard', 'static');
const html = readFileSync(path.join(base, 'index.html'), 'utf8');
const script = readFileSync(path.join(base, 'app.js'), 'utf8');
const designs = readFileSync(path.join(base, 'designs.js'), 'utf8');

const KEY = 'Synthetic_page_key_for_tests_only_0123456789'; // Test value, not a secret.
const LOGO = `/api/logo/${'a'.repeat(64)}.png`;
const CONFIG = {sensitive_review_enabled: false, project_approval_modes: {}, theme: 'hybrid', dashboard_name: 'Synthetic',
  github_username: 'someone', github_visibility: 'private', logo_path: LOGO};

function element(id = '', hidden = false) {
  const e = {id, hidden, dataset: {}, children: [], listeners: {}, attributes: {}, value: '', textContent: '', disabled: false,
    classList: {toggle() {}, add() {}, remove() {}}, style: {},
    addEventListener(name, handler) {(this.listeners[name] ||= []).push(handler);},
    append(...c) {this.children.push(...c);}, replaceChildren(...c) {this.children = c;},
    querySelectorAll() {return [];}, querySelector() {return null;}, setAttribute(k, v) {this.attributes[k] = v;},
    removeAttribute(k) {delete this.attributes[k];}, focus() {}, close() {}, showModal() {}, remove() {}};
  e.elements = new Proxy({}, {get: (target, key) => target[key] ||= element()});
  return e;
}

function storage(mode, initial = {}) {
  const values = new Map(Object.entries(initial));
  if (mode === 'throws') return {getItem() {throw new Error('SecurityError');}, setItem() {throw new Error('SecurityError');}, values};
  return {getItem: (k) => values.has(k) ? values.get(k) : null, setItem: (k, v) => values.set(k, String(v)), values};
}

function page({hash = '', stored = {}, storageMode = 'ok', storageGetterThrows = false, respond = () => null} = {}) {
  const nodes = new Map();
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    nodes.set(match[2], element(match[2], /\shidden(?:\s|>)/.test(match[0])));
  }
  const selectors = new Map();
  const document = {
    body: element('body'), hidden: false, activeElement: null,
    getElementById: (id) => nodes.get(id) || (nodes.set(id, element(id)), nodes.get(id)),
    createElement: () => element(), createTextNode: (t) => ({textContent: t}), addEventListener() {},
    querySelector: (s) => selectors.get(s) || (selectors.set(s, element()), selectors.get(s)),
    querySelectorAll: () => [],
  };
  const calls = [], replaced = [], blobs = [];
  function fetch(url, options = {}) {
    calls.push({url, options});
    const data = respond(url);
    if (data === null) return new Promise(() => {});
    return Promise.resolve(data);
  }
  const store = storage(storageMode, stored);
  const runtime = {document, fetch, console, setInterval() {}, Event: class {}, Option: class {},
    location: {hash, pathname: '/', search: ''},
    history: {replaceState: (...args) => replaced.push(args)},
    URL: {createObjectURL: (blob) => {blobs.push(blob); return 'blob:synthetic-logo';}}};
  if (storageGetterThrows) Object.defineProperty(runtime, 'sessionStorage', {get() {throw new Error('SecurityError');}});
  else runtime.sessionStorage = store;
  return {runtime, document, nodes, calls, replaced, blobs, store};
}

const run = (f, source = script) => vm.runInNewContext(source, f.runtime);
const settle = async () => {for (let i = 0; i < 20; i++) await Promise.resolve();};
const keyOf = (call) => call.options.headers?.['X-Dashboard-Key'];
const apiCalls = (f) => f.calls.filter(c => c.url.startsWith('/api/'));

test('launch URL key is stored, stripped from the address bar and sent on every API call', async () => {
  const f = page({hash: '#key=' + KEY});
  run(f);
  await settle();
  assert.deepEqual(f.replaced, [[null, '', '/']]);
  assert.equal(f.store.values.get('dashboard-key'), KEY);
  assert.ok(apiCalls(f).length >= 3, 'provider, settings and state are requested at load');
  for (const call of apiCalls(f)) assert.equal(keyOf(call), KEY, call.url);
  assert.equal(f.nodes.get('key-required').hidden, true);
});

test('a reload without the fragment uses the key saved for this tab', async () => {
  const f = page({stored: {'dashboard-key': KEY}});
  run(f);
  await settle();
  assert.deepEqual(f.replaced, []);
  for (const call of apiCalls(f)) assert.equal(keyOf(call), KEY, call.url);
  assert.equal(f.nodes.get('key-required').hidden, true);
});

test('a missing key shows the launch URL message and sends no key header', async () => {
  const f = page();
  run(f);
  await settle();
  const notice = f.nodes.get('key-required');
  assert.equal(notice.hidden, false);
  assert.match(html, /Open the dashboard with the URL printed when it started\./);
  for (const call of apiCalls(f)) assert.equal(keyOf(call), undefined, call.url);
});

test('a malformed fragment is stripped and never used', async () => {
  const f = page({hash: '#key=short'});
  run(f);
  await settle();
  assert.deepEqual(f.replaced, [[null, '', '/']]);
  assert.equal(f.nodes.get('key-required').hidden, false);
  assert.equal(f.store.values.has('dashboard-key'), false);
  for (const call of apiCalls(f)) assert.equal(keyOf(call), undefined);
});

test('an unrelated fragment is left alone', async () => {
  const f = page({hash: '#main', stored: {'dashboard-key': KEY}});
  run(f);
  await settle();
  assert.deepEqual(f.replaced, []);
  for (const call of apiCalls(f)) assert.equal(keyOf(call), KEY);
});

for (const [label, options] of [['storage methods throw', {storageMode: 'throws'}], ['storage access throws', {storageGetterThrows: true}]]) {
  test(`when ${label}, the key is kept in memory and still sent`, async () => {
    const f = page({hash: '#key=' + KEY, ...options});
    run(f);
    await settle();
    assert.deepEqual(f.replaced, [[null, '', '/']]);
    assert.ok(apiCalls(f).length >= 3);
    for (const call of apiCalls(f)) assert.equal(keyOf(call), KEY, call.url);
    assert.equal(f.nodes.get('key-required').hidden, true);
  });
}

test('an uploaded logo is fetched with the key and shown from a blob URL', async () => {
  const png = {type: 'image/png'};
  const f = page({hash: '#key=' + KEY, respond: (url) => url === '/api/config' ? {ok: true, json: async () => CONFIG}
    : url === LOGO ? {ok: true, blob: async () => png} : null});
  run(f);
  await settle();
  const logoCall = f.calls.find(c => c.url === LOGO);
  assert.ok(logoCall, 'logo fetched through the keyed wrapper');
  assert.equal(keyOf(logoCall), KEY);
  assert.deepEqual(f.blobs, [png]);
  assert.equal(f.document.querySelector('.brand-logo').src, 'blob:synthetic-logo');
});

test('the design preview page sends the saved key and loads an uploaded logo as a blob', async () => {
  const png = {type: 'image/png'};
  const f = page({stored: {'dashboard-key': KEY}, respond: (url) => url === '/api/config' ? {ok: true, json: async () => CONFIG}
    : url === LOGO ? {ok: true, blob: async () => png} : null});
  const img = element();
  f.runtime.document.querySelectorAll = (s) => s === 'img' ? [img] : [];
  run(f, designs);
  await settle();
  assert.deepEqual(apiCalls(f).map(c => [c.url, keyOf(c)]), [['/api/config', KEY], [LOGO, KEY]]);
  assert.equal(img.src, 'blob:synthetic-logo');
});

test('the design preview page sends no key when none is saved', async () => {
  const f = page({storageMode: 'throws'});
  run(f, designs);
  await settle();
  assert.deepEqual(apiCalls(f).map(c => [c.url, keyOf(c)]), [['/api/config', undefined]]);
});

test('no script reaches the API except through the keyed wrapper', () => {
  for (const [name, source] of [['app.js', script], ['designs.js', designs]]) {
    assert.equal((source.match(/\bfetch\(/g) || []).length, 1, name + ' has one raw fetch call');
    assert.doesNotMatch(source, /EventSource|window\.open|XMLHttpRequest|sendBeacon|\.src\s*=\s*config\.logo_path/, name);
  }
  assert.doesNotMatch(html, /(?:src|href|action)="\/api\//);
});
