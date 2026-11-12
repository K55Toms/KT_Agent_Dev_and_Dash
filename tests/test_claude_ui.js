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
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.providerTest={renderTeam,teamSubtitle,updateView,setView(value){view=value;},setTeam(value){teamSnapshot=value;teamRenderSignature="";},render,renderTasks,renderDetail,renderCosts,loadProvider,setWorkspace(value){state=value;stale=false;detailSignature="";},setConversation(value){conversationId="root";conversationData=value;renderConversation();}};'), runtime);
  const settle = async () => {for (let i = 0; i < 12; i++) await Promise.resolve();};
  return {document, nodes, requests, providerCalls, settle, api: runtime.providerTest};
}


const claudeInfo = {provider: 'claude', configured: true, capabilities: {provider: 'claude', guidance_while_running: 'no', subagent_questions: 'no', plan: 'unconfirmed', recovery: 'no', assessment: 'no', approval_alternative: 'no'}};
const USAGE = {total_tokens: 1234, input_tokens: 1000, cached_input_tokens: 100, output_tokens: 134, reasoning_output_tokens: 0};
const usdCost = (usd, source = 'Claude Code result.total_cost_usd (list price)') => ({basis: 'estimated', unit: 'usd-estimate', usd, credits: null, source, pricing_date: null});
const CLAUDE_PRICING = {unit: 'usd-estimate', source: 'Claude Code client-side list-price estimate', speed_basis: 'Not a billed amount; the subscription login is not billed per call'};
const codexCost = {basis: 'estimated', credits: 12.5, source: 'Codex rates', pricing_date: '2026-10-16'};

function claudeTask(id, overrides = {}) {
  return {id, project_id: 'p1', title: 'Task ' + id, role: 'chief_of_staff', status: 'completed', model: 'm', provider: 'claude',
    created_at: '2026-10-18T09:00:00Z', updated_at: '2026-10-18T09:30:00Z', usage: USAGE, cost: usdCost(0.25), ...overrides};
}
function workspace(tasks, extra = {}) {
  return {connection: {status: 'connected', detail: '', last_event_at: null, server_version: null},
    projects: [{id: 'p1', name: 'Project One'}], roles: [{id: 'chief_of_staff', label: 'Chief of Staff', model: 'm', reasoning: 'high'}],
    approvals: [], pricing: CLAUDE_PRICING, tasks, ...extra};
}
async function ready(provider, state) {
  const f = fixture(provider);
  await f.settle();
  f.api.setWorkspace(state);
  f.api.render();
  return f;
}
const text = (f, id) => f.nodes.get(id).textContent;
const metricValue = (f, label) => {
  const box = f.nodes.get('metrics').children.find(c => c.textContent.startsWith(label));
  return {value: box.children[1].textContent, note: box.children[2].textContent};
};

test('test_usd_estimate_is_summed_and_labelled', async () => {
  const f = await ready(claudeInfo, workspace([claudeTask('a', {cost: usdCost(0.25)}), claudeTask('b', {cost: usdCost(0.5)}), claudeTask('c', {cost: null, usage: null})]));
  const m = metricValue(f, 'Execution estimate');
  assert.equal(m.value, '≈ $0.7500');
  assert.equal(m.note, 'Estimated USD (list price) · 1 unknown run');
});

test('test_mixed_units_show_mixed_basis', async () => {
  const f = await ready(claudeInfo, workspace([claudeTask('a'), claudeTask('b', {provider: undefined, cost: codexCost})]));
  const m = metricValue(f, 'Execution estimate');
  assert.equal(m.value, 'Mixed basis');
  assert.ok(!m.note.includes('USD (list price)'));
  const g = await ready(claudeInfo, workspace([claudeTask('a'), claudeTask('b', {cost: usdCost(1, 'Other source')})]));
  assert.equal(metricValue(g, 'Execution estimate').value, 'Mixed basis');
});

test('test_plan_and_usage_text_name_the_provider', async () => {
  const f = await ready(claudeInfo, workspace([claudeTask('a', {usage: null, cost: null, status: 'completed', plan: []})]));
  f.api.renderDetail('a');
  const detail = text(f, 'task-detail');
  assert.ok(detail.includes('No plan steps have been reported by Claude.'));
  assert.ok(detail.includes('Usage has not been observed. Cost remains unknown until Claude reports a result.'));
  assert.ok(!detail.includes('Codex'));
  const empty = await ready(claudeInfo, workspace([]));
  empty.api.renderCosts([]);
  assert.ok(text(empty, 'cost-list').includes('Usage will appear when Claude reports it'));
});

test('test_denied_notice_renders_as_text', async () => {
  const payload = '<img src=x onerror=alert(1)>';
  const diagnostics = [{stage: 'execution', code: 'claude_calls_denied', at: '2026-10-18T09:10:00Z',
    message: 'Some tool calls were denied. ' + payload, action: 'Review ' + payload}];
  const f = await ready(claudeInfo, workspace([claudeTask('a', {diagnostics})]));
  f.api.renderDetail('a');
  const detail = text(f, 'task-detail');
  assert.ok(detail.includes('Some tool calls were denied. ' + payload));
  assert.ok(detail.includes('claude_calls_denied'));
  const all = f.nodes.get('task-detail').querySelectorAll('*');
  assert.ok(!all.some(e => e.tagName === 'IMG'));
});

test('test_stop_enabled_for_active_claude_task', async () => {
  const stopOf = f => f.nodes.get('task-detail').querySelectorAll('button').find(b => b.textContent === 'Stop run');
  const f = await ready(claudeInfo, workspace([claudeTask('a', {status: 'running', cost: null, usage: null})]));
  f.api.renderDetail('a');
  assert.equal(stopOf(f).disabled, false);
  const down = workspace([claudeTask('a', {status: 'running', cost: null, usage: null})]);
  down.connection.status = 'disconnected';
  const g = await ready(claudeInfo, down);
  g.api.renderDetail('a');
  assert.equal(stopOf(g).disabled, true);
});

test('test_codex_wording_unchanged_without_provider_endpoint', async () => {
  const codexTask = {id: 'x', project_id: 'p1', title: 'Codex task', role: 'chief_of_staff', status: 'completed', model: 'm', plan: [], usage: null, cost: null,
    created_at: '2026-10-18T09:00:00Z', updated_at: '2026-10-18T09:30:00Z', diagnostics: [{stage: 'thread_start', code: 'x', at: '2026-10-18T09:00:00Z', message: 'm'}]};
  const state = workspace([codexTask], {pricing: {source: 'https://learn.chatgpt.com/docs/pricing', pricing_date: '2026-10-16', unit: 'credits', speed_basis: 's'}});
  const f = await ready('absent', state);
  f.api.renderDetail('x');
  const detail = text(f, 'task-detail');
  assert.ok(detail.includes('No plan steps have been reported by Codex.'));
  assert.ok(detail.includes('Usage has not been observed. Cost remains unknown without a supported model and pricing basis.'));
  assert.ok(detail.includes('Create Codex thread'));
  f.api.renderCosts([codexTask]);
  assert.ok(text(f, 'pricing-note').startsWith('Standard-speed workspace credit estimates are not verified charges or invoices.'));
  assert.ok(text(f, 'cost-list').includes('CREDIT ESTIMATE'));
  f.api.renderCosts([]);
  assert.ok(text(f, 'cost-list').includes('Usage will appear when Codex reports it for a dashboard-managed run.'));
  const priced = {...codexTask, cost: codexCost, usage: USAGE};
  f.api.setWorkspace({...state, tasks: [priced]}); f.api.render();
  assert.equal(metricValue(f, 'Execution estimate').value, '≈ 12.5');
  f.api.renderCosts([priced]);
  assert.ok(text(f, 'cost-list').includes('≈ 12.5 credits'));
  assert.ok(text(f, 'cost-list').includes('Estimated · Standard speed'));
});

test('test_diagnostic_stage_labels_follow_provider', async () => {
  const diagnostics = [{stage: 'launch', code: 'claude_launch_invalid', at: '2026-10-18T09:00:00Z', message: 'm'},
    {stage: 'thread_start', code: 'y', at: '2026-10-18T09:00:00Z', message: 'm'}, {stage: 'transport', code: 'claude_restart_unknown', at: '2026-10-18T09:00:00Z', message: 'm'}];
  const f = await ready(claudeInfo, workspace([claudeTask('a', {diagnostics}), claudeTask('b', {provider: undefined, diagnostics})]));
  f.api.renderDetail('a');
  const claude = text(f, 'task-detail');
  assert.ok(claude.includes('Launch Claude Code') && claude.includes('Claude Code process'));
  assert.ok(!claude.includes('Create Codex thread') && !claude.includes('App Server connection'));
  f.api.renderDetail('b');
  assert.ok(text(f, 'task-detail').includes('Create Codex thread'));
});

test('test_costs_table_for_claude_task', async () => {
  const state = workspace([claudeTask('a')]);
  const f = await ready(claudeInfo, state);
  f.api.renderCosts(state.tasks);
  const table = text(f, 'cost-list');
  assert.ok(table.includes('≈ $0.2500'));
  assert.ok(table.includes('Estimated · list price'));
  assert.ok(table.includes('Claude Code result.total_cost_usd (list price)'));
  assert.ok(table.includes('1,234') || table.includes('1234'));
  assert.ok(!table.includes('credits'));
  const note = f.nodes.get('pricing-note');
  assert.ok(note.textContent.includes('not verified charges or invoices'));
  assert.ok(note.textContent.includes('Not a billed amount; the subscription login is not billed per call'));
  assert.ok(!note.querySelectorAll('*').some(e => e.tagName === 'A'));
});

test('test_provider_specific_static_text', async () => {
  const origEffect = html.match(/<p id="delete-run-effect">([^<]*)<\/p>/)[1];
  for (const provider of [claudeInfo, 'absent']) {
    const f = await ready(provider, workspace([]));
    const claude = provider !== 'absent';
    const notice = text(f, 'run-dialog-notice'), effect = text(f, 'delete-run-effect');
    if (claude) {
      assert.ok(notice.includes('Claude runs use the default permission mode; when Claude needs permission it asks for your approval in this dashboard, and calls you do not approve are denied. How long it waits can be set in Settings.'));
      assert.ok(!notice.includes('Codex'));
      assert.equal(effect, 'Removes this run\'s dashboard record: its conversation, outputs, delegates and approvals. Claude keeps its own local session history. This frees the project for a new run. If this run is marked "may still be running", deleting it does not stop it, so two runs could work in the same project.');
    } else {
      assert.equal(notice, '');  // untouched: the static Codex markup stays as shipped
      assert.ok(!effect.includes('Claude'));
    }
  }
  const codex = await ready({provider: 'codex', configured: true, capabilities: {provider: 'codex'}}, workspace([]));
  assert.ok(!text(codex, 'delete-run-effect').includes('Claude'));
  assert.ok(!text(codex, 'run-dialog-notice').includes('Claude'));
  assert.ok(origEffect.includes('Codex native history'));
});

test('test_submit_connection_message_follows_provider', async () => {
  for (const [provider, name] of [[claudeInfo, 'Claude'], ['absent', 'Codex']]) {
    const down = workspace([]); down.connection.status = 'disconnected';
    const f = await ready(provider, down);
    const form = f.nodes.get('run-form');
    const error = new (f.nodes.get('run-form').constructor)('p');
    form.querySelector = sel => sel === '.form-error' ? error : (sel === '[type="submit"]' ? new error.constructor('button') : null);
    form.reportValidity = () => true;
    form.closest = () => form;
    const event = {preventDefault() {}, currentTarget: form};
    await Promise.all(form.emit('submit', event));
    assert.equal(error.textContent, `Refresh the workspace and restore the ${name} connection before starting a run.`);
  }
});

test('test_denied_count_and_names_render_safely', async () => {
  const mk = (claude, extra = {}) => claudeTask('a', {claude, ...extra});
  const show = async task => { const f = await ready(claudeInfo, workspace([task])); f.api.renderDetail('a'); return text(f, 'task-detail'); };
  let d = await show(mk({denied_count: 3, denied_tools: ['Bash', '<img src=x>', 'mcp__srv:tool.x', 7]}));
  assert.ok(d.includes('3 tool calls were denied: Bash, mcp__srv:tool.x'));
  assert.ok(!d.includes('<img'));
  d = await show(mk({denied_count: 1, denied_tools: []}));
  assert.ok(d.includes('1 tool call was denied'));
  assert.ok(!d.includes('1 tool call was denied:'));
  for (const bad of [-1, 1.5, '2', 1e6, NaN, null]) {
    d = await show(mk({denied_count: bad, denied_tools: ['Bash']}));
    assert.ok(!d.includes('denied:') && !/tool calls? w/.test(d), String(bad));
  }
  d = await show(mk({denied_count: 30, denied_tools: Array.from({length: 30}, (_, i) => 'T' + i)}));
  assert.ok(d.includes('T19') && !d.includes('T20'));
  d = await show(claudeTask('a', {provider: undefined, claude: {denied_count: 2, denied_tools: ['Bash']}}));
  assert.ok(!d.includes('were denied'));
});

test('test_malformed_usd_is_not_summed', async () => {
  const bad = [NaN, Infinity, -1, '0.5', undefined];
  for (const usd of bad) {
    const f = await ready(claudeInfo, workspace([claudeTask('a', {cost: {...usdCost(0), usd}})]));
    assert.equal(metricValue(f, 'Execution estimate').value, 'Unknown', String(usd));
    f.api.renderCosts(f.api && [claudeTask('a', {cost: {...usdCost(0), usd}})]);
    assert.ok(text(f, 'cost-list').includes('Unknown'));
    assert.ok(!text(f, 'cost-list').includes('$'));
  }
  const noUnit = await ready(claudeInfo, workspace([claudeTask('a', {cost: {...usdCost(0.5), unit: undefined}})]));
  assert.equal(metricValue(noUnit, 'Execution estimate').value, 'Unknown');
  const huge = await ready(claudeInfo, workspace([claudeTask('a', {cost: usdCost(1e308)}), claudeTask('b', {cost: usdCost(1e308)})]));
  assert.equal(metricValue(huge, 'Execution estimate').value, 'Unknown');
  const big = await ready(claudeInfo, workspace([claudeTask('a', {cost: usdCost(5e9)})]));
  assert.equal(metricValue(big, 'Execution estimate').value, '≥ $1,000,000,000');
  big.api.renderCosts([claudeTask('a', {cost: usdCost(1e308)})]);
  assert.ok(text(big, 'cost-list').includes('≥ $1,000,000,000') && !text(big, 'cost-list').includes('e+'));
});

test('test_cost_with_usd_and_credits_is_not_mixed_with_itself', async () => {
  const both = {...usdCost(0.25), credits: 3};
  const f = await ready(claudeInfo, workspace([claudeTask('a', {cost: both}), claudeTask('b', {cost: both})]));
  const m = metricValue(f, 'Execution estimate');
  assert.equal(m.value, '≈ $0.5000');
});

test('test_pricing_note_flags_other_basis_only_when_present', async () => {
  const codexTask = claudeTask('x', {provider: undefined, cost: codexCost});
  const claudeOnly = await ready(claudeInfo, workspace([claudeTask('a')]));
  claudeOnly.api.renderCosts([claudeTask('a')]);
  assert.ok(!text(claudeOnly, 'pricing-note').includes('different basis'));
  const mixed = await ready(claudeInfo, workspace([claudeTask('a'), codexTask]));
  mixed.api.renderCosts([claudeTask('a'), codexTask]);
  assert.ok(text(mixed, 'pricing-note').endsWith('Some tasks use a different basis.'));
  const codexState = workspace([codexTask], {pricing: {source: 'https://learn.chatgpt.com/docs/pricing', pricing_date: '2026-10-16', unit: 'credits'}});
  const c = await ready('absent', codexState);
  c.api.renderCosts([codexTask]);
  assert.ok(!text(c, 'pricing-note').includes('different basis'));
  c.api.renderCosts([codexTask, claudeTask('a')]);
  assert.ok(text(c, 'pricing-note').includes('Some tasks use a different basis.'));
});

const teamMember = (extra = {}) => ({id: 'backend_developer', name: 'Kira Voss', role: 'Backend Developer', description: 'd', portrait: '/team-portraits/backend_developer.svg',
  model: 'm', reasoning: 'high', last_task: null, activities: [], ...extra});
const allText = el => el.textContent;

test('test_team_panel_has_no_reward_area_for_claude', async () => {
  const f = await ready(claudeInfo, workspace([claudeTask('a')]));
  f.api.setTeam({members: [teamMember()], awards: [], rewards: false});
  f.api.renderTeam();
  const grid = allText(f.nodes.get('team-grid'));
  assert.match(grid, /Kira Voss/);
  assert.doesNotMatch(grid, /Rebel coins|Agent of the Week/);
  assert.equal(f.nodes.get('team-awards-section').hidden, true);
  assert.equal(f.nodes.get('team-awards').children.length, 0);
});

test('test_team_panel_lists_an_unnamed_delegate_under_its_parent_role', async () => {
  const f = await ready(claudeInfo, workspace([claudeTask('a')]));
  const activity = {id: 'c1', parent_task_id: 'a', project_id: 'p1', role: null, title: 'Unattributed delegated task', status: 'completed',
    source: 'delegated', unnamed_delegate: true, updated_at: '2026-10-18T09:30:00Z'};
  f.api.setTeam({members: [teamMember({activities: [activity]})], awards: [], rewards: false});
  f.api.renderTeam();
  assert.match(allText(f.nodes.get('team-grid')), /Unnamed delegate/);
});

test('test_team_panel_still_renders_rewards_for_codex', async () => {
  const f = await ready({provider: 'codex', configured: true, capabilities: {provider: 'codex'}}, workspace([]));
  const award = {id: 'x', recipient_id: 'backend_developer', kind: 'agent_of_week', coins: 5, reason: 'Good work', issued_at: '2026-10-18T09:30:00Z', source_task: 'zz'};
  f.api.setTeam({members: [teamMember({coins: 5, agent_of_week: true})], awards: [award]});
  f.api.renderTeam();
  const grid = allText(f.nodes.get('team-grid'));
  assert.match(grid, /5 Rebel coins/);
  assert.match(grid, /Agent of the Week/);
  assert.equal(f.nodes.get('team-awards-section').hidden, false);
  assert.match(allText(f.nodes.get('team-awards')), /Good work/);
});

test('test_team_subtitle_drops_the_celebrate_part_without_rewards_and_keeps_it_for_codex', async () => {
  const withoutRewards = 'Meet the agents and review their latest recorded work.';
  const withRewards = 'Meet the agents, review their latest recorded work and celebrate contributions.';
  const claude = await ready(claudeInfo, workspace([]));
  assert.equal(claude.api.teamSubtitle(), withoutRewards);   // before the team answer arrives, from the provider
  claude.api.setView('team'); claude.api.updateView();
  assert.equal(claude.nodes.get('page-subtitle').textContent, withoutRewards);
  claude.api.setTeam({members: [teamMember()], awards: [], rewards: false});
  assert.equal(claude.api.teamSubtitle(), withoutRewards);
  const codex = await ready({provider: 'codex', configured: true, capabilities: {provider: 'codex'}}, workspace([]));
  assert.equal(codex.api.teamSubtitle(), withRewards);
  codex.api.setView('team'); codex.api.updateView();
  assert.equal(codex.nodes.get('page-subtitle').textContent, withRewards);
  codex.api.setTeam({members: [teamMember({coins: 5})], awards: []});
  assert.equal(codex.api.teamSubtitle(), withRewards);
});
