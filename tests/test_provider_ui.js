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

function fixture(provider = 'absent') {
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
    get options() {return this.children.filter(c => c.tagName === 'OPTION');}
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
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    contains(child){return child===this||this.querySelectorAll('*').includes(child);}
    reportValidity(){return true;}
    dispatchEvent(event){this.emit(event.type,event);}
    setSelectionRange(start){this.selectionStart=start;}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(c=>c!==this);}
    querySelectorAll(selector) {
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      if (selector === '*') return descendants;
      if(selector==='*')return descendants;
      if(selector==='[data-draft-key]')return descendants.filter(e=>e.dataset.draftKey);
      if(selector.includes(' ')&&!selector.includes(',')){const [parent,child]=selector.split(' ');return this.querySelectorAll(parent).flatMap(e=>e.querySelectorAll(child));}
      if(selector.startsWith('.'))return descendants.filter(e=>e.className?.split(' ').includes(selector.slice(1)));
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
    getElementById(id) {return nodes.get(id)||[...nodes.values()].flatMap(e=>e.querySelectorAll('*')).find(e=>e.id===id);},
    createElement(tag) {return new Element(tag);}, addEventListener() {},
    querySelector(selector) {if (!classes.has(selector)) classes.set(selector, new Element()); return classes.get(selector);},
    querySelectorAll(selector) {return selector === 'dialog' ? dialogs : selector === '[data-view]' ? views : [];},
  };
  const requests = [];
  const response = data => ({ok: true, json: async () => data});
  const providerCalls = [];
  function fetch(url, options) {
    if (url === '/api/provider') {
      providerCalls.push(url);
      if (provider === 'absent') return Promise.resolve({ok: false, status: 404, json: async () => ({error: 'Not found'})});
      if (provider === 'network') return Promise.reject(new TypeError('network down'));
      if (provider === 'unreadable') return Promise.resolve({ok: true, json: async () => {throw new SyntaxError('bad json');}});
      return Promise.resolve(response(provider));
    }
    if (url.includes('/review') || url.includes('/respond') || url.includes('/alternative') || url.endsWith('/message')) return new Promise((resolve, reject) => requests.push({url, options, resolve: data => resolve(response(data)), fail: data => resolve({ok: false, json: async () => data}), reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={document, fetch, setInterval() {}, console, Option: class Option extends Element {constructor(label, value) {super('option'); this.textContent = label; this.value = value;}}, Event:class Event{constructor(type){this.type=type;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.providerTest={render,renderTasks,renderDetail,renderConversation,openRun,openApprovalReview,loadProvider,setWorkspace(value){state=value;stale=false;detailSignature="";},setConversation(value){conversationId="root";conversationData=value;renderConversation();}};'), runtime);
  const settle = async () => {for (let i = 0; i < 12; i++) await Promise.resolve();};
  return {document, nodes, requests, providerCalls, settle, api: runtime.providerTest};
}

const info = (provider, overrides = {}) => {
  const base = {
    codex: {guidance_while_running: 'yes', subagent_questions: 'yes', plan: 'yes', recovery: 'yes', assessment: 'yes', approval_alternative: 'yes'},
    claude: {guidance_while_running: 'no', subagent_questions: 'no', plan: 'unconfirmed', recovery: 'no', assessment: 'no', approval_alternative: 'no'},
    none: {guidance_while_running: 'no', subagent_questions: 'no', plan: 'no', recovery: 'no', assessment: 'no', approval_alternative: 'no'},
  }[provider];
  return {provider, configured: provider !== 'none', capabilities: {provider, ...base, ...overrides}};
};

function workspace(status = 'connected', detail = '', taskOverrides = {}) {
  return {connection: {status, detail, last_event_at: null, server_version: null},
    projects: [{id: 'p1', name: 'Project One'}], roles: [{id: 'chief_of_staff', label: 'Chief of Staff', model: 'm', reasoning: 'high'}], approvals: [],
    tasks: [{id: 'root', project_id: 'p1', title: 'Build feature', role: 'chief_of_staff', status: 'completed', model: 'm',
      recovery_available: true, created_at: '2026-10-18T09:00:00Z', updated_at: '2026-10-18T09:30:00Z', ...taskOverrides}]};
}

async function ready(provider, state = workspace()) {
  const f = fixture(provider);
  await f.settle();
  f.api.setWorkspace(state);
  f.api.render();
  return f;
}
const text = (f, id) => f.nodes.get(id).textContent;

test('labels follow the provider endpoint', async () => {
  const claude = await ready(info('claude'), workspace('connected'));
  assert.equal(claude.providerCalls.length, 1);
  assert.equal(text(claude, 'connection-label'), 'Claude connected');
  assert.equal(text(claude, 'source-title'), 'Claude');
  assert.equal(text(claude, 'provider-note'), 'Dashboard-managed Claude runs');
  assert.equal(text(claude, 'completion-note').startsWith('Completed means the Claude turn finished.'), true);
  claude.api.setWorkspace(workspace('connecting'));
  claude.api.render();
  assert.equal(text(claude, 'connection-label'), 'Connecting to Claude');
  assert.equal(claude.nodes.get('start-run').title, 'Wait for the Claude connection');
  claude.api.setWorkspace(workspace('disconnected'));
  claude.api.render();
  assert.equal(text(claude, 'connection-label'), 'Claude disconnected');
  claude.api.setWorkspace(workspace('connected'));
  claude.api.render();
  claude.api.openRun();
  assert.equal(text(claude, 'run-dialog-title'), 'Start a Claude run');
  const codex = await ready(info('codex'), workspace('connected'));
  assert.equal(text(codex, 'connection-label'), 'Codex connected');
  assert.equal(text(codex, 'source-title'), 'Codex App Server');
});

test('labels default to Codex wording without endpoint', async () => {
  for (const provider of ['absent', 'network', 'unreadable', {provider: 'mystery', capabilities: {}}, {provider: 'claude'}]) {
    const f = await ready(provider, workspace('connected'));
    assert.equal(text(f, 'connection-label'), 'Codex connected');
    assert.equal(text(f, 'source-title'), 'Codex App Server');
    assert.equal(text(f, 'provider-note'), 'Dashboard-managed Codex runs');
    assert.equal(text(f, 'completion-note').startsWith('Completed means the Codex turn finished.'), true);
    f.api.setWorkspace(workspace('connecting')); f.api.render();
    assert.equal(text(f, 'connection-label'), 'Connecting to Codex');
    assert.equal(f.nodes.get('start-run').title, 'Wait for the Codex connection');
    f.api.setWorkspace(workspace('disconnected')); f.api.render();
    assert.equal(text(f, 'connection-label'), 'Codex disconnected');
    f.api.setWorkspace(workspace('connected', '', {})); f.api.render(); f.api.openRun();
    assert.equal(text(f, 'run-dialog-title'), 'Start a Codex run');
    f.api.renderDetail('root');
    assert.ok(f.nodes.get('task-detail').querySelectorAll('button').some(b => b.textContent === 'Recover task'));
  }
});

test('provider chip and detail row', async () => {
  const f = await ready(info('claude'), workspace('connected', '', {provider: 'claude'}));
  const state = workspace('connected', '', {provider: 'claude'});
  f.api.setWorkspace(state);
  f.api.renderTasks(state.tasks);
  const chips = f.nodes.get('task-list').querySelectorAll('.provider-chip');
  assert.equal(chips.length, 1);
  assert.equal(chips[0].textContent, 'Claude');
  f.api.renderDetail('root');
  const detail = f.nodes.get('task-detail');
  const labels = detail.querySelectorAll('dt').map(e => e.textContent);
  assert.ok(labels.includes('Provider'));
  const values = detail.querySelectorAll('dd').map(e => e.textContent);
  assert.equal(values[labels.indexOf('Provider')], 'Claude');
  for (const provider of [undefined, 'codex']) {
    const codexState = workspace('connected', '', provider ? {provider} : {});
    f.api.setWorkspace(codexState);
    f.api.renderTasks(codexState.tasks);
    assert.equal(f.nodes.get('task-list').querySelectorAll('.provider-chip').length, 0);
    f.api.renderDetail('root');
    assert.equal(f.nodes.get('task-detail').querySelectorAll('dt').some(e => e.textContent === 'Provider'), false);
  }
  const literal = workspace('connected', '', {provider: '<img src=x>'});
  f.api.setWorkspace(literal);
  f.api.renderTasks(literal.tasks);
  assert.equal(f.nodes.get('task-list').querySelectorAll('.provider-chip')[0].textContent, '<img src=x>');
});

test('none provider disables start run', async () => {
  const f = await ready(info('none'), workspace('disabled', 'No provider configured.'));
  assert.equal(text(f, 'connection-label'), 'No provider configured');
  assert.equal(text(f, 'source-title'), 'No provider configured');
  assert.equal(text(f, 'source-detail'), 'No provider configured.');
  assert.equal(f.nodes.get('start-run').disabled, true);
  assert.equal(f.nodes.get('start-run').title, 'No provider configured');
  assert.equal(text(f, 'provider-note'), 'No provider configured');
  assert.equal(text(f, 'completion-note'), "Completed means the run's turn finished. Independent acceptance and release review still apply.");
  assert.equal(text(f, 'run-dialog-title'), 'Start a run');
  assert.doesNotMatch(text(f, 'completion-note') + text(f, 'run-dialog-title') + text(f, 'provider-note'), /the the|a the|Codex|Claude/);
  // Even a (never expected) connected status cannot start a run without a provider.
  f.api.setWorkspace(workspace('connected'));
  f.api.render();
  assert.equal(f.nodes.get('start-run').disabled, true);
  f.api.openRun();
  assert.equal(f.nodes.get('run-dialog').open, false);
});

test('disabled status never says Codex disconnected', async () => {
  const cases = [[info('none'), 'No provider configured.'], [info('claude'), 'Claude backend is not implemented yet.'],
    ['absent', 'Some stub detail.'], [info('codex'), 'Some stub detail.']];
  for (const [provider, detail] of cases) {
    const f = await ready(provider, workspace('disabled', detail));
    const label = text(f, 'connection-label');
    assert.doesNotMatch(label, /Codex disconnected/);
    assert.notEqual(label, '');
    assert.equal(f.nodes.get('start-run').disabled, true);
    assert.doesNotMatch(text(f, 'source-title'), /Codex App Server/);
    assert.equal(text(f, 'source-detail'), detail);
  }
  const stub = await ready(info('claude'), workspace('disabled', 'Claude backend is not implemented yet.'));
  assert.equal(text(stub, 'connection-label'), 'Claude backend not implemented yet');
  assert.equal(text(stub, 'source-title'), 'Claude backend');
  assert.equal(stub.nodes.get('start-run').title, 'Claude backend is not implemented yet.');
});

test('claude hides recovery and alternative controls', async () => {
  const claude = await ready(info('claude'), workspace('connected'));
  claude.api.renderDetail('root');
  assert.equal(claude.nodes.get('task-detail').querySelectorAll('button').some(b => b.textContent === 'Recover task'), false);
  const codex = await ready(info('codex'), workspace('connected'));
  codex.api.renderDetail('root');
  assert.ok(codex.nodes.get('task-detail').querySelectorAll('button').some(b => b.textContent === 'Recover task'));
  // A capability that is "no" hides the control; "unconfirmed" and "yes" keep it.
  const unconfirmed = await ready(info('claude', {recovery: 'unconfirmed'}), workspace('connected'));
  unconfirmed.api.renderDetail('root');
  assert.ok(unconfirmed.nodes.get('task-detail').querySelectorAll('button').some(b => b.textContent === 'Recover task'));

  const approval = {id: 'req', task_id: 'root', kind: 'command', status: 'pending', resolution_mode: 'decline',
    available_decisions: ['decline'], summary: 'Synthetic command request', can_request_alternative: true};
  for (const [provider, hidden] of [[info('claude'), true], [info('codex'), false]]) {
    const state = {...workspace('connected'), approvals: [approval]};
    state.tasks[0].status = 'waiting_approval';
    const f = await ready(provider, state);
    const loading = f.api.openApprovalReview(approval);
    f.requests[0].fail({error: 'Synthetic context missing.', code: 'command_missing', action: 'Ask for a reviewable alternative.', retryable: true, can_request_alternative: true});
    await loading;
    assert.equal(f.nodes.get('approval-guidance-section').hidden, hidden);
    assert.equal(f.nodes.get('request-approval-alternative').hidden, hidden);
    assert.equal(f.nodes.get('request-approval-alternative').disabled, true === hidden ? true : false);
  }
});

test('claude hides the conversation view recover button', async () => {
  const conversation = {task_id: 'root', turn_id: 't', messages: [], questions: [], can_send: false, send_mode: 'steer',
    agents: {}, recovery_available: true};
  const recoverButtons = (f) => f.nodes.get('conversation-content').querySelectorAll('button').filter(b => b.textContent === 'Recover task');
  const codex = await ready(info('codex'), workspace('connected'));
  codex.api.setConversation(conversation);
  assert.equal(recoverButtons(codex).length, 1);
  assert.match(text(codex, 'conversation-content'), /delegated work needs recovery checks/);
  const claude = await ready(info('claude'), workspace('connected'));
  claude.api.setConversation(conversation);
  assert.equal(recoverButtons(claude).length, 0);
  assert.doesNotMatch(text(claude, 'conversation-content'), /delegated work needs recovery checks/);
  const absent = await ready('absent', workspace('connected'));
  absent.api.setConversation(conversation);
  assert.equal(recoverButtons(absent).length, 1);
});
