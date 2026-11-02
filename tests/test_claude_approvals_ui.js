'use strict';

// Interaction checks of the shipped script for Claude tool-call approvals and the Claude settings.
// The DOM double does not verify layout, native dialog behaviour or screen-reader output.
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
      this.attributes = {}; this.value = ''; this._text = ''; this.className = '';
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
    showModal() {this.open = true;}
    close() {this.open = false; this.emit('close');}
    closest() {return this.parentElement || this;}
    reportValidity() {return true;}
    querySelectorAll(selector) {
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      if (selector === '*') return descendants;
      if (selector === 'form .form-error') return [];
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
  const requests = [];
  const response = data => ({ok: true, json: async () => data});
  function fetch(url, options) {
    if ((url === '/api/config' && options.body) || url.includes('/review') || url.includes('/sensitive-review') || url.includes('/respond')) return new Promise((resolve, reject) => requests.push({url, options, resolve: data => resolve(response(data)), fail: data => resolve({ok: false, json: async () => data}), reject}));
    return new Promise(() => {});
  }
  const runtime = {document, fetch, setInterval() {}, console, Option: class Option extends Element {constructor(label, value) {super('option'); this.textContent = label; this.value = value;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.t={render,saveSettings,validSettings,openApprovalReview,respondReviewedApproval,approvalDecisionDescription,deniedLine,applyProviderText,reviewableKinds,setProvider(v){providerInfo=v;applyProviderText();},setSettings(value){settings=value;settingsBusy=false;populateSettings();},setWorkspace(value,fresh=true){state=value;stale=!fresh;checkApprovalReview();}};'), runtime);
  return {document, nodes, requests, api: runtime.t};
}

const claudeInfo = {provider: 'claude', configured: true, capabilities: {provider: 'claude', approval_alternative: 'no'}};
const codexInfo = {provider: 'codex', configured: true, capabilities: {provider: 'codex'}};
const PROJECT = '0123456789abcdef0123456789abcdef';
const config = (extra = {}) => ({sensitive_review_enabled: true, project_approval_modes: {}, theme: 'hybrid', dashboard_name: 'Test', github_username: 'someone', github_visibility: 'private', logo_path: '/brand-logo.png', claude_approval_wait_seconds: 900, ...extra});
const toolCall = (extra = {}) => ({id: 'tc1', task_id: 't1', kind: 'tool_call', status: 'pending', native_method: 'PermissionRequest', requester: 'Kira Voss (Backend Developer) via Claude Code', summary: 'A tool call requires approval', reason: 'Claude Code asked to run a tool', scope: 'This one tool call only', resolution_mode: 'decline', available_decisions: ['decline'], created_at: '2026-11-02T09:00:00Z', ...extra});
function workspace(approvals, extra = {}) {
  return {connection: {status: 'connected', detail: ''}, projects: [{id: PROJECT, name: 'Project One'}], roles: [{id: 'chief_of_staff', label: 'Chief of Staff', model: 'm', reasoning: 'high'}],
    tasks: [{id: 't1', title: 'Task one', project_id: PROJECT, role: 'chief_of_staff', status: 'waiting_approval', provider: 'claude', created_at: '2026-11-02T09:00:00Z'}],
    approvals, questions: [], pricing: {}, ...extra};
}
function ready(approvals, {provider = claudeInfo, settings = config(), fresh = true, ws = {}} = {}) {
  const f = fixture();
  f.api.setProvider(provider);
  f.api.setSettings(settings);
  f.api.setWorkspace(workspace(approvals, ws), fresh);
  f.api.render();
  return f;
}
const all = (f, id) => f.nodes.get(id).querySelectorAll('*');
const cardText = f => f.nodes.get('approval-list').textContent;
const buttons = f => all(f, 'approval-list').filter(e => e.tagName === 'BUTTON');
const CONTEXT = {tool_name: 'Bash', tool_input: {command: 'rm -rf build && echo "<b>done</b>"', description: 'Clean the build folder'}};
async function review(approval, context = CONTEXT, opts) {
  const f = ready([approval], opts);
  const opening = f.api.openApprovalReview(approval);
  const body = {id: approval.id, task_id: approval.task_id, kind: approval.kind, review_id: randomUUID(), context};
  f.requests[0].resolve(body);
  await opening;
  return {f, body};
}

test('reviewableKinds includes tool_call', () => {
  const f = fixture();
  assert.equal(f.api.reviewableKinds.has('tool_call'), true);
  const g = ready([toolCall()]);
  const labels = buttons(g).map(b => b.textContent);
  assert.ok(labels.includes('Review request'));
  assert.ok(!/unsupported/.test(cardText(g)));
});

test('card shows complete input and requester', async () => {
  const {f, body} = await review(toolCall());
  const section = f.nodes.get('approval-command-context');
  assert.equal(section.hidden, false);
  assert.ok(section.textContent.includes('Bash'));
  const pres = section.querySelectorAll('pre');
  assert.equal(pres.length, 1);
  assert.equal(pres[0].textContent, JSON.stringify(body.context.tool_input, null, 2));
  assert.equal(pres[0].attributes.tabindex, '0');
  assert.ok(f.nodes.get('approval-review-task').textContent.includes('Kira Voss (Backend Developer) via Claude Code'));
  assert.equal(f.nodes.get('approval-review-context').hidden, true);
});

test('long and unusual values are shown whole as text, never as markup', async () => {
  const input = {command: 'x'.repeat(20000) + '\n<img src=x onerror=alert(1)>', file_path: '/a/b'};
  const {f} = await review(toolCall(), {tool_name: 'Write', tool_input: input});
  const pre = f.nodes.get('approval-command-context').querySelectorAll('pre')[0];
  assert.equal(pre.textContent, JSON.stringify(input, null, 2));
  assert.equal(pre.className, 'approval-review-context');
});

test('the one-call line shows the configured wait', async () => {
  for (const [seconds, wording] of [[900, '15 minutes'], [60, '1 minute'], [90, '1 minute 30 seconds'], [3600, '60 minutes'], [125, '2 minutes 5 seconds']]) {
    const {f} = await review(toolCall(), CONTEXT, {settings: config({claude_approval_wait_seconds: seconds})});
    assert.ok(f.nodes.get('approval-review-scope').textContent.startsWith(`This one call only. The run stops waiting after ${wording}.`), f.nodes.get('approval-review-scope').textContent);
    const g = ready([toolCall()], {settings: config({claude_approval_wait_seconds: seconds})});
    assert.ok(cardText(g).includes(`This one call only. The run stops waiting after ${wording}.`));
  }
});

test('only Accept and Decline are offered on a tool call', async () => {
  const {f} = await review(toolCall());
  assert.equal(f.nodes.get('approve-request').textContent, 'Accept');
  assert.equal(f.nodes.get('approve-request').disabled, false);
  assert.equal(f.nodes.get('decline-reviewed-request').textContent, 'Decline');
  assert.equal(f.nodes.get('decline-reviewed-request').hidden, false);
  assert.equal(f.nodes.get('decline-reviewed-request').disabled, false);
  assert.equal(f.nodes.get('cancel-reviewed-request').hidden, true);
  assert.equal(f.nodes.get('stop-reviewed-run').hidden, true);
  for (const id of ['request-approval-alternative', 'approval-guidance-section', 'approval-alternative-notice']) assert.equal(f.nodes.get(id).hidden, true, id);
});

test('accept sends the receipt and decline sends only the decision', async () => {
  const {f, body} = await review(toolCall());
  void f.api.respondReviewedApproval('accept');
  assert.match(f.requests[1].url, /\/respond$/);
  assert.deepEqual(JSON.parse(f.requests[1].options.body), {decision: 'accept', review_id: body.review_id});
  const g = await review(toolCall());
  void g.f.api.respondReviewedApproval('decline');
  assert.deepEqual(JSON.parse(g.f.requests[1].options.body), {decision: 'decline'});
});

test('buttons are disabled when the view is stale or disconnected', async () => {
  const {f} = await review(toolCall());
  const approval = toolCall();
  f.api.setWorkspace(workspace([approval], {connection: {status: 'disconnected'}}));
  assert.equal(f.nodes.get('approve-request').disabled, true);
  assert.equal(f.nodes.get('decline-reviewed-request').disabled, true);
  const g = ready([toolCall()], {fresh: false});
  for (const b of buttons(g)) assert.equal(b.disabled, true, b.textContent);
  const h = ready([toolCall()], {ws: {connection: {status: 'disconnected'}}});
  for (const b of buttons(h)) assert.equal(b.disabled, true, b.textContent);
});

test('expired approval has no buttons', () => {
  const states = [
    [{status: 'unavailable', unavailable_reason: 'expired', available_decisions: []}, /Expired/, /stopped waiting/],
    [{status: 'unavailable', unavailable_reason: 'connection_closed', available_decisions: []}, /Unavailable/, /no longer waiting/],
    [{status: 'unavailable', unavailable_reason: 'run_ended', available_decisions: []}, /Unavailable/, /ended or was stopped/],
    [{status: 'unavailable', unavailable_reason: 'dashboard_restarted', available_decisions: []}, /Unavailable/, /dashboard restarted/],
    [{status: 'unavailable', available_decisions: []}, /Unavailable/, /no longer waiting/],
    [{status: 'expired', available_decisions: []}, /Expired/, /stopped waiting/],
  ];
  for (const [extra, badge, detail] of states) {
    const f = ready([toolCall(extra)]);
    assert.equal(buttons(f).length, 0, JSON.stringify(extra));
    assert.match(cardText(f), badge);
    assert.match(cardText(f), detail);
    assert.match(cardText(f), /denied/);
    assert.ok(!cardText(f).includes('Reconnecting does not replay'), 'tool-call states have their own text');
  }
});

test('automatic accepts are labelled project policy', () => {
  const at = '2026-11-02T09:01:00Z';
  const labelled = (decision) => {
    const f = ready([toolCall({status: 'resolved', available_decisions: [], decision})]);
    return cardText(f);
  };
  assert.ok(labelled({source: 'project_policy', value: 'accept', at}).includes('Accepted automatically by project policy (one call)'));
  assert.ok(labelled({source: 'human', value: 'accept', at}).includes('Accepted by you (one call)'));
  assert.ok(labelled({source: 'human', value: 'decline', at}).includes('Declined by you'));
  assert.ok(labelled({source: 'human_sensitive_review', value: 'accept', at}).includes('Accepted by you after sensitive request review (one call)'));
});

test('Codex strings unchanged', async () => {
  const at = '2026-11-02T09:01:00Z';
  assert.equal(script.includes('innerHTML'), false);
  assert.match(String(script), /Approved automatically by this project’s policy/);
  const f = fixture();
  assert.match(f.api.approvalDecisionDescription({source: 'project_policy', value: 'accept', at}), /^Approved automatically by this project’s policy · /);
  assert.match(f.api.approvalDecisionDescription({source: 'human', value: 'accept', at}), /^Approved once by you · /);
  const codex = {id: 'c1', task_id: 't1', kind: 'command', status: 'pending', requester: 'Codex App Server', summary: 'Synthetic command', resolution_mode: 'decline', available_decisions: ['decline'], created_at: '2026-11-02T09:00:00Z'};
  const g = ready([codex], {provider: codexInfo});
  assert.ok(!/This one call only/.test(cardText(g)));
  const opening = g.api.openApprovalReview(codex);
  g.requests[0].resolve({id: 'c1', task_id: 't1', kind: 'command', review_id: 'r', context: {command: 'ls', cwd: '/p'}});
  await opening;
  assert.equal(g.nodes.get('approve-request').textContent, 'Approve once');
  assert.equal(g.nodes.get('decline-reviewed-request').textContent, 'Decline request');
  assert.equal(g.nodes.get('stop-reviewed-run').hidden, false);
  assert.ok(g.nodes.get('approval-review-scope').textContent.startsWith('This decision applies only to this exact native request.'));
});

test('run dialog notice for Claude names dashboard approvals, denial and the Settings wait', () => {
  const f = fixture();
  f.api.setProvider(claudeInfo);
  const notice = f.nodes.get('run-dialog-notice').textContent;
  assert.ok(notice.includes('asks for your approval in this dashboard'));
  assert.ok(notice.includes('calls you do not approve are denied'));
  assert.ok(notice.includes('can be set in Settings'));
  assert.ok(!notice.includes('later release'));
  assert.ok(!notice.includes('Codex'));
});

test('wait field hidden for Codex', () => {
  const f = fixture();
  assert.equal(f.nodes.get('claude-wait-fieldset').hidden, true);
  f.api.setProvider(codexInfo);
  assert.equal(f.nodes.get('claude-wait-fieldset').hidden, true);
  assert.equal(f.nodes.get('claude-automatic-help').hidden, true);
  f.api.setProvider(claudeInfo);
  assert.equal(f.nodes.get('claude-wait-fieldset').hidden, false);
  assert.equal(f.nodes.get('claude-automatic-help').hidden, false);
  f.api.setProvider({provider: 'none', capabilities: {}});
  assert.equal(f.nodes.get('claude-wait-fieldset').hidden, true);
});

test('wait field text, bounds and current value', () => {
  const f = fixture();
  f.api.setSettings(config({claude_approval_wait_seconds: 300}));
  const input = f.nodes.get('claude-approval-wait');
  assert.equal(String(input.value), '300');
  // Static markup text is not loaded into the DOM double, so the shipped HTML is checked directly.
  assert.ok(html.includes('<p class="field-help" id="claude-wait-unverified">Unverified above 120 seconds on this machine: a longer wait relies on Claude Code honouring a long hook timeout.</p>'));
  assert.match(html, /id="claude-approval-wait"[^>]*min="60"[^>]*max="3600"/);
});

test('out-of-range value shows an error and sends nothing', async () => {
  for (const bad of ['59', '3601', '0', '-60', '90.5', 'abc', '', ' ', '1e3', '0x100', '900 s']) {
    const f = fixture();
    f.api.setProvider(claudeInfo);
    f.api.setSettings(config());
    f.nodes.get('claude-approval-wait').value = bad;
    await f.api.saveSettings({preventDefault() {}});
    assert.equal(f.requests.length, 0, `value ${JSON.stringify(bad)} must not be sent`);
    assert.match(f.nodes.get('settings-error').textContent, /whole number of seconds from 60 to 3600/);
  }
});

test('a valid wait is sent as an integer; Codex saves do not send it', async () => {
  const f = fixture();
  f.api.setProvider(claudeInfo);
  f.api.setSettings(config());
  f.nodes.get('claude-approval-wait').value = '1800';
  void f.api.saveSettings({preventDefault() {}});
  assert.equal(f.requests.length, 1);
  assert.strictEqual(JSON.parse(f.requests[0].options.body).claude_approval_wait_seconds, 1800);
  f.requests[0].resolve(config({claude_approval_wait_seconds: 1800}));
  await new Promise(r => setImmediate(r));
  const g = fixture();
  g.api.setProvider(codexInfo);
  g.api.setSettings(config());
  g.nodes.get('claude-approval-wait').value = 'garbage';
  void g.api.saveSettings({preventDefault() {}});
  assert.equal(g.requests.length, 1);
  assert.equal('claude_approval_wait_seconds' in JSON.parse(g.requests[0].options.body), false);
});

test('config validator accepts the wait only as an integer in range', () => {
  const f = fixture();
  assert.equal(f.api.validSettings(config()), true);
  const {claude_approval_wait_seconds, ...older} = config();
  assert.equal(f.api.validSettings(older), true);
  for (const good of [60, 900, 3600]) assert.equal(f.api.validSettings(config({claude_approval_wait_seconds: good})), true);
  for (const bad of [59, 3601, 900.5, '900', null, true, NaN, Infinity, [900], -1]) assert.equal(f.api.validSettings(config({claude_approval_wait_seconds: bad})), false, String(bad));
});

test('automatic confirmation required for Claude projects too', async () => {
  const f = fixture();
  f.api.setProvider(claudeInfo);
  f.api.setSettings(config());
  f.api.setWorkspace(workspace([]));
  f.api.render();
  const select = f.nodes.get('project-approval-settings').querySelectorAll('select')[0];
  select.value = 'automatic';
  void f.api.saveSettings({preventDefault() {}});
  assert.equal(f.requests.length, 0);
  assert.match(f.nodes.get('settings-error').textContent, /Confirm the broad effect of automatic approvals/);
  f.nodes.get('confirm-project-automatic').checked = true;
  void f.api.saveSettings({preventDefault() {}});
  assert.equal(f.requests.length, 1);
});

test('Claude automatic wording names the covered tools and the limits', () => {
  const help = html.match(/<p id="claude-automatic-help"[^>]*>([^<]*)<\/p>/)[1];
  for (const tool of ['Bash', 'Write', 'Edit', 'NotebookEdit']) assert.ok(help.includes(tool), tool);
  assert.ok(help.includes('one call at a time'));
  assert.ok(help.includes('requests with secret-like text, web, MCP and other tools always wait for you'));
  assert.ok(html.includes('I understand the broad effect and enable automatic approvals for the projects selected above.'));
});

test('denied-calls line adds bounded code and tool records without request text', () => {
  const f = fixture();
  f.api.setProvider(claudeInfo);
  const task = (claude) => ({provider: 'claude', claude});
  assert.equal(f.api.deniedLine(task({denied_count: 2, denied_tools: ['Bash', 'Edit']})), '2 tool calls were denied: Bash, Edit');
  const line = f.api.deniedLine(task({denied_count: 1, denied_tools: ['Bash'], hook_denials: [
    {code: 'claude_hook_turn_inactive', tool_name: 'Bash'},
    {code: 'claude_hook_limit', tool_name: 'Write'},
    {code: 'claude_hook_session_unknown', tool_name: 'Edit'},
    {code: 'claude_hook_turn_inactive', tool_name: 'bad name with spaces'},
    {code: 'rm -rf', tool_name: 'Bash'},
    {code: 'claude_hook_limit', tool_name: 'x', extra: 'SECRET_TEXT', tool_input: 'SECRET_TEXT'},
  ]}));
  assert.ok(line.startsWith('1 tool call was denied: Bash'));
  assert.ok(line.includes('Bash (asked after the turn ended)'));
  assert.ok(line.includes('Write (too many approvals were waiting)'));
  assert.ok(line.includes('Edit (asked before the session was known)'));
  assert.ok(!line.includes('bad name') && !line.includes('rm -rf') && !line.includes('SECRET_TEXT'));
  const many = Array.from({length: 40}, (_, i) => ({code: 'claude_hook_limit', tool_name: 'T' + i}));
  assert.ok(f.api.deniedLine(task({denied_count: 1, denied_tools: [], hook_denials: many})).split('T').length <= 22);
  assert.equal(f.api.deniedLine(task({denied_count: 0, denied_tools: [], hook_denials: many})), '');
});
