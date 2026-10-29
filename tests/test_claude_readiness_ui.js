'use strict';

// Claude readiness labels and the Start run button, checked on the shipped script with a small DOM
// double and synthetic HTTP. Not browser evidence and not a live Claude run.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const base = path.join(__dirname, '..', 'dashboard', 'static');
const html = readFileSync(path.join(base, 'index.html'), 'utf8');
const script = readFileSync(path.join(base, 'app.js'), 'utf8');

function fixture(provider) {
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {}; this.dataset = {};
      this.hidden = false; this.disabled = false; this.open = false; this.attributes = {}; this.value = ''; this._text = '';
      this.classList = {toggle() {}};
      this.elements = new Proxy({}, {get: (target, key) => target[key] ||= new Element('input')});
    }
    set textContent(value) {this._text = String(value); this.children = [];}
    get textContent() {return this._text + this.children.map(c => c.textContent).join('');}
    set innerHTML(value) {throw new Error('HTML rendering is forbidden in this fixture');}
    append(...children) {for (const child of children) {child.parentElement = this; this.children.push(child);}}
    replaceChildren(...children) {this.children = []; this._text = ''; this.append(...children);}
    setAttribute(key, value) {this.attributes[key] = value;}
    removeAttribute(key) {delete this.attributes[key];}
    addEventListener(name, handler) {(this.listeners[name] ||= []).push(handler);}
    focus() {}
    showModal() {this.open = true;}
    close() {this.open = false;}
    closest() {return this.parentElement || this;}
    querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
    querySelectorAll(selector) {
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      if (selector === '*') return descendants;
      if (selector.startsWith('.')) return descendants.filter(e => e.className?.split(' ').includes(selector.slice(1)));
      return descendants.filter(e => selector.split(',').some(tag => e.tagName === tag.trim().toUpperCase()));
    }
  }
  const nodes = new Map();
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]); element.id = match[2];
    element.parentElement = new Element(); nodes.set(element.id, element);
  }
  const classes = new Map();
  const document = {
    activeElement: null, body: new Element('body'), hidden: false,
    getElementById(id) {return nodes.get(id) || [...nodes.values()].flatMap(e => e.querySelectorAll('*')).find(e => e.id === id);},
    createElement(tag) {return new Element(tag);}, addEventListener() {},
    querySelector(selector) {if (!classes.has(selector)) classes.set(selector, new Element()); return classes.get(selector);},
    querySelectorAll() {return [];},
  };
  function fetch(url) {
    if (url === '/api/provider') {
      if (provider === 'absent') return Promise.resolve({ok: false, status: 404, json: async () => ({error: 'Not found'})});
      return Promise.resolve({ok: true, json: async () => provider});
    }
    return new Promise(() => {});
  }
  const runtime = {document, fetch, setInterval() {}, console,
    Option: class Option extends Element {constructor(label, value) {super('option'); this.textContent = label; this.value = value;}},
    Event: class Event {constructor(type) {this.type = type;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.readinessTest={render,setWorkspace(value){state=value;stale=false;}};'), runtime);
  return {nodes, api: runtime.readinessTest};
}

const claude = {provider: 'claude', configured: true, capabilities: {provider: 'claude', guidance_while_running: 'no',
  subagent_questions: 'no', plan: 'unconfirmed', recovery: 'no', assessment: 'no', approval_alternative: 'no'}};

function workspace(status, detail = '', serverVersion = null) {
  return {connection: {status, detail, last_event_at: null, server_version: serverVersion},
    projects: [{id: 'p1', name: 'Project One'}], roles: [{id: 'chief_of_staff', label: 'Chief of Staff', model: 'opus', reasoning: 'high'}],
    approvals: [], tasks: []};
}

async function ready(provider, state) {
  const f = fixture(provider);
  for (let i = 0; i < 12; i++) await Promise.resolve();
  f.api.setWorkspace(state);
  f.api.render();
  return f;
}
const text = (f, id) => f.nodes.get(id).textContent;

test('claude connected reads Claude connected and enables Start run', async () => {
  const f = await ready(claude, workspace('connected', 'Claude Code 2.1.312 (login not verified)', '2.1.312'));
  assert.equal(text(f, 'connection-label'), 'Claude connected');
  assert.equal(text(f, 'source-detail'), 'Claude Code 2.1.312 (login not verified)');
  assert.equal(f.nodes.get('start-run').disabled, false);
  assert.equal(f.nodes.get('start-run').title, '');
});

test('claude connecting waits for the probe', async () => {
  const f = await ready(claude, workspace('connecting', 'Checking Claude Code'));
  assert.equal(text(f, 'connection-label'), 'Connecting to Claude');
  assert.equal(f.nodes.get('start-run').disabled, true);
  assert.equal(f.nodes.get('start-run').title, 'Wait for the Claude connection');
});

test('claude disabled uses the server detail', async () => {
  for (const detail of ['Claude Code was not found on PATH.', 'Claude Code did not report a version.']) {
    const f = await ready(claude, workspace('disabled', detail));
    assert.equal(text(f, 'connection-label'), detail.replace(/\.$/, ''));
    assert.doesNotMatch(text(f, 'connection-label'), /not implemented/);
    assert.equal(f.nodes.get('start-run').disabled, true);
    assert.equal(f.nodes.get('start-run').title, detail);
  }
});

test('Codex wording is unchanged without the provider endpoint', async () => {
  const f = await ready('absent', workspace('connected', 'Live App Server; opening this page starts no runs'));
  assert.equal(text(f, 'connection-label'), 'Codex connected');
  assert.equal(text(f, 'source-title'), 'Codex App Server');
  assert.equal(f.nodes.get('start-run').disabled, false);
  const waiting = await ready('absent', workspace('connecting'));
  assert.equal(text(waiting, 'connection-label'), 'Connecting to Codex');
});
