'use strict';

// Dependency-free interaction checks of the shipped script. This small DOM double
// does not verify browser layout, native Escape handling or screen-reader output.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');
const base = path.join(__dirname, '..', 'dashboard', 'static');
const html = readFileSync(path.join(base, 'index.html'), 'utf8');
const script = readFileSync(path.join(base, 'app.js'), 'utf8');

function fixture() {
  let document;
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {};
      this.dataset = {}; this.hidden = false; this.disabled = false; this.open = false;
      this.attributes = {}; this.value = ''; this._text = '';
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
    emit(name, event = {}) {return (this.listeners[name] || []).map(handler => handler(event));}
    focus() {document.activeElement = this;}
    click() {this.focus(); return this.emit('click');}
    showModal() {this.open = true; this.querySelectorAll('button')[0]?.focus();}
    close() {this.open = false; this.emit('close');}
    closest() {return this.parentElement || this;}
    querySelectorAll(selector) {
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      if (selector === '*') return descendants;
      if (selector === 'form .form-error') return [];
      if (selector === '[data-close]') return descendants.filter(e => 'data-close' in e.attributes);
      return descendants.filter(e => selector.split(',').some(tag => e.tagName === tag.toUpperCase()));
    }
  }
  const nodes = new Map();
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]); element.id = match[2];
    element.hidden = /\shidden(?:\s|>)/.test(match[0]);
    element.parentElement = new Element(); nodes.set(element.id, element);
  }
  const dialogs = [...nodes.values()].filter(e => e.tagName === 'DIALOG');
  for (const dialog of dialogs) {
    const markup = html.match(new RegExp(`<dialog id="${dialog.id}"[^>]*>([\\s\\S]*?)</dialog>`))[1];
    for (const button of markup.matchAll(/<button\b([^>]*)>([^<]*)<\/button>/g)) {
      const element = new Element('button'); element.textContent = button[2];
      if (button[1].includes('data-close')) element.setAttribute('data-close', '');
      dialog.append(element);
    }
  }
  const views = [...html.matchAll(/data-view="([^"]+)"/g)].map(match => {
    const element = new Element('button'); element.dataset.view = match[1]; return element;
  });
  const classes = new Map();
  document = {
    activeElement: null, body: new Element('body'), hidden: false,
    getElementById(id) {assert.ok(nodes.has(id), `HTML element #${id} exists`); return nodes.get(id);},
    createElement(tag) {return new Element(tag);}, addEventListener() {},
    querySelector(selector) {if (!classes.has(selector)) classes.set(selector, new Element()); return classes.get(selector);},
    querySelectorAll(selector) {return selector === 'dialog' ? dialogs : selector === '[data-view]' ? views : [];},
  };
  const suffix = randomUUID();
  const members = ['alpha', 'beta'].map(id => ({id, name: `Synthetic ${id} ${suffix}`,
    role: `Synthetic ${id} role`, description: 'Generated test fixture', coins: 0}));
  const requests = [];
  const response = data => ({ok: true, json: async () => data});
  function fetch(url, options) {
    if (url === '/api/team') return Promise.resolve(response({members, awards: []}));
    if (url.includes('/prompt')) return new Promise((resolve, reject) => requests.push({url, options, resolve: data => resolve(response(data)), reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  vm.runInNewContext(script, {document, fetch, setInterval() {}, console});
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {
    document, nodes, requests, members, settle,
    async ready() {views.find(e => e.dataset.view === 'team').click(); await settle();},
    buttons() {return nodes.get('team-grid').querySelectorAll('button');},
    open(index) {return this.buttons()[index].click()[0];},
    close() {nodes.get('agent-dialog').querySelectorAll('[data-close]')[0].click();},
    prompt: () => nodes.get('agent-prompt'), status: () => nodes.get('agent-prompt-status'),
  };
}

test('every member opens its own prompt as literal, multiline, read-only text', async () => {
  const f = fixture(); await f.ready();
  assert.equal(f.buttons().length, f.members.length);
  for (let index = 0; index < f.members.length; index++) {
    const member = f.members[index];
    assert.equal(f.buttons()[index].attributes['aria-label'], `Details for ${member.name}`);
    assert.equal(f.buttons()[index].attributes['aria-haspopup'], 'dialog');
    const pending = f.open(index);
    assert.equal(f.requests[index].url, `/api/team/${member.id}/prompt`);
    assert.equal(f.requests[index].options.method, 'GET');
    assert.equal(f.nodes.get('agent-dialog').open, true);
    assert.equal(f.nodes.get('agent-dialog-title').textContent, `${member.name} · ${member.role}`);
    assert.match(f.status().textContent, /Loading/);
    assert.equal(f.prompt().hidden, true);
    const text = `Synthetic ${randomUUID()}\n  preserve indentation\n<img src=x onerror=alert(1)>\n<script>throw 1</script>`;
    f.requests[index].resolve({role_id: member.id, prompt: text}); await pending;
    assert.equal(f.prompt().textContent, text);
    assert.equal(f.prompt().children.length, 0);
    assert.equal(f.prompt().tagName, 'PRE');
    assert.equal(f.prompt().hidden, false);
    assert.match(html, /<pre\b[^>]*id="agent-prompt"[^>]*tabindex="0"[^>]*aria-label="Personal prompt"/);
    assert.doesNotMatch(html.match(/<pre\b[^>]*id="agent-prompt"[^>]*>/)[0], /contenteditable/);
    f.close();
    assert.equal(f.document.activeElement, f.buttons()[index]);
    assert.equal(f.prompt().textContent, '');
    assert.equal(f.prompt().hidden, true);
  }
});

test('network failure clears previous content and reopening recovers with fresh GET', async () => {
  const f = fixture(); await f.ready();
  let pending = f.open(0);
  f.requests[0].resolve({role_id: 'alpha', prompt: 'Synthetic previous prompt'}); await pending; f.close();
  pending = f.open(1);
  assert.equal(f.prompt().textContent, '');
  f.requests[1].reject(new Error('Synthetic unavailable')); await pending;
  assert.match(f.status().textContent, /Prompt unavailable.*Close and reopen/);
  assert.equal(f.prompt().hidden, true);
  f.close(); pending = f.open(1);
  f.requests[2].resolve({role_id: 'beta', prompt: 'Synthetic recovered prompt'}); await pending;
  assert.equal(f.prompt().textContent, 'Synthetic recovered prompt');
  assert.equal(f.requests.length, 3);
});

test('empty, wrong-role and malformed prompt responses fail closed', async () => {
  for (const result of [{role_id: 'beta', prompt: 'Synthetic wrong role'}, {role_id: 'alpha', prompt: ' \n '},
    {role_id: 'alpha', prompt: 42}, {prompt: 'Synthetic missing identity'}, null]) {
    const f = fixture(); await f.ready(); const pending = f.open(0);
    f.requests[0].resolve(result); await pending;
    assert.equal(f.prompt().hidden, true);
    assert.equal(f.prompt().textContent, '');
    assert.match(f.status().textContent, /Prompt unavailable/);
  }
});

test('late success and failure cannot replace reopened member or closed dialog', async () => {
  for (const fail of [false, true]) {
    const f = fixture(); await f.ready(); const first = f.open(0); f.close();
    const second = f.open(1);
    f.requests[1].resolve({role_id: 'beta', prompt: 'Synthetic current prompt'}); await second;
    if (fail) f.requests[0].reject(new Error('Synthetic stale error'));
    else f.requests[0].resolve({role_id: 'alpha', prompt: 'Synthetic stale prompt'});
    await first;
    assert.equal(f.prompt().textContent, 'Synthetic current prompt');
    assert.equal(f.status().textContent, 'Personal prompt');
    f.close(); const closed = f.open(0); f.close();
    f.requests[2].resolve({role_id: 'alpha', prompt: 'Synthetic closed prompt'}); await closed;
    assert.equal(f.prompt().hidden, true);
    assert.equal(f.prompt().textContent, '');
    assert.equal(f.nodes.get('agent-dialog').open, false);
  }
});

test('an old request for the same member cannot override a newer request', async () => {
  const f = fixture(); await f.ready(); const first = f.open(0); f.close(); const second = f.open(0);
  f.requests[1].resolve({role_id: 'alpha', prompt: 'Synthetic latest version'}); await second;
  f.requests[0].resolve({role_id: 'alpha', prompt: 'Synthetic older version'}); await first;
  assert.equal(f.prompt().textContent, 'Synthetic latest version');
});
