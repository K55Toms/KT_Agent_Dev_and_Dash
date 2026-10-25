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
  function fetch(url, options) {
    if (url.includes('/review')||url.includes('/dismiss-attention')||url.includes('/conversation')||url.includes('/message')||url.includes('/respond')) return new Promise((resolve,reject)=>requests.push({url,options,resolve:data=>resolve(response(data)),reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={document, fetch, setInterval() {}, console,Event:class Event{constructor(type){this.type=type;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.activityTest={renderTasks,renderTeam,renderDetail,openTask,updateView,setWorkspace(value){state=value;stale=false;},setTeam(value){teamSnapshot=value;},setView(value){view=value;updateView();},setStale(value){stale=value;}};'),runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, settle, api:runtime.activityTest};
}

function workspace(){
  return {connection:{status:'connected'},projects:[{id:'p1',name:'Project One'},{id:'p2',name:'Project Two'}],roles:[{id:'chief_of_staff',label:'Chief of Staff'},{id:'frontend_developer',label:'Frontend Developer'},{id:'qa_engineer',label:'QA Engineer'}],approvals:[],
    tasks:[{id:'root',project_id:'p1',title:'Build feature',role:'chief_of_staff',status:'completed',thread_id:'root-thread',created_at:'2026-10-18T09:00:00Z',updated_at:'2026-10-18T09:30:00Z'},{id:'other',project_id:'p2',title:'Other project work',role:'frontend_developer',status:'running'}],
    delegated_activities:[{id:'child',parent_task_id:'root',project_id:'p1',thread_id:'child-thread',parent_thread_id:'root-thread',role:'frontend_developer',title:'Implement feature',status:'running',created_at:'2026-10-18T09:05:00Z',updated_at:'2026-10-18T09:25:00Z'},
      {id:'nested',parent_task_id:'root',project_id:'p1',thread_id:'nested-thread',parent_thread_id:'child-thread',role:'qa_engineer',title:'Check feature',status:'queued',created_at:'2026-10-18T09:10:00Z',updated_at:'2026-10-18T09:20:00Z'}]};
}
function team(state){return {members:[{id:'frontend_developer',name:'Synthetic Crew',role:'Frontend Developer',coins:0,activities:[{...state.tasks[1],source:'direct'},...state.delegated_activities.filter(a=>a.role==='frontend_developer').map(a=>({...a,source:'delegated'}))]}],awards:[]};}

test('Overview activity opens task detail with delegated statuses and nested lineage',()=>{
  const f=fixture(),state=workspace();f.api.setWorkspace(state);f.api.renderTasks(state.tasks);
  assert.match(f.nodes.get('task-list').textContent,/2 delegated activities · 1 running · 1 queued/);
  f.nodes.get('task-list').querySelectorAll('button').find(b=>b.textContent==='Build feature').click();
  assert.equal(f.nodes.get('task-dialog').open,true);
  const detail=f.nodes.get('task-detail');assert.match(detail.textContent,/Delegated activity/);assert.match(detail.textContent,/Implement featureRunningFrontend Developer/);assert.match(detail.textContent,/Check featureQueuedQA Engineer/);
  const entries=detail.querySelectorAll('.delegated-activity');assert.equal(entries.length,2);assert.equal(entries[1].parentElement.parentElement,entries[0]);
  assert.match(entries[1].textContent,/Delegated by: Frontend Developer/);assert.match(entries[0].textContent,/Created .*Updated/);
  assert.ok(detail.querySelectorAll('button').some(b=>b.textContent==='Open coordinating conversation'));
});

test('delegation polling refreshes an unchanged parent task and preserves conversation focus',()=>{
  const f=fixture(),state=workspace();f.api.setWorkspace(state);f.api.openTask('root');
  let detail=f.nodes.get('task-detail');const conversation=detail.querySelectorAll('button').find(b=>b.textContent==='Open coordinating conversation');conversation.focus();
  state.delegated_activities[0].status='completed';f.api.renderDetail('root');
  const entry=detail.querySelectorAll('.delegated-activity')[0];assert.match(entry.textContent,/Implement featureCompleted/);assert.equal(f.document.activeElement.textContent,'Open coordinating conversation');assert.notEqual(f.document.activeElement,conversation);
  state.delegated_activities=[];f.api.renderDetail('root');assert.match(detail.textContent,/No delegated activity has been observed/);assert.doesNotMatch(detail.textContent,/Implement feature/);
  f.api.setStale(true);f.api.renderDetail('root');assert.match(detail.textContent,/Status may be stale/);
});

test('Team lists all direct and delegated activities and navigates to coordinating task',()=>{
  const f=fixture(),state=workspace();f.api.setWorkspace(state);f.api.setTeam(team(state));f.api.renderTeam();
  const grid=f.nodes.get('team-grid');assert.match(grid.textContent,/RECORDED ACTIVITY · 2/);assert.match(grid.textContent,/Other project work/);assert.match(grid.textContent,/Direct · Project Two/);assert.match(grid.textContent,/Implement feature/);assert.match(grid.textContent,/Delegated · Project One/);assert.match(grid.textContent,/Coordinating task: Build feature/);
  grid.querySelectorAll('button').find(b=>b.textContent==='Implement feature').click();assert.equal(f.nodes.get('task-dialog-title').textContent,'Build feature');assert.match(f.nodes.get('task-detail').textContent,/Check feature/);
});

test('Team project filter isolates activity and displays explicit empty state',()=>{
  const f=fixture(),state=workspace();f.api.setWorkspace(state);f.api.setTeam(team(state));
  f.nodes.get('project-filter').value='p1';f.api.setView('team');const grid=f.nodes.get('team-grid');assert.match(grid.textContent,/RECORDED ACTIVITY · 1/);assert.match(grid.textContent,/Implement feature/);assert.doesNotMatch(grid.textContent,/Other project work|Project Two/);
  f.nodes.get('project-filter').value='missing';f.api.renderTeam();assert.match(grid.textContent,/No observed activity in this project/);assert.doesNotMatch(grid.textContent,/Implement feature/);
});

test('delegated content is literal and cross-project records cannot appear in task details',()=>{
  const f=fixture(),state=workspace();state.delegated_activities[0].title='<img src=x onerror=alert(1)>';
  state.delegated_activities.push({...state.delegated_activities[0],id:'wrong-project',project_id:'p2',title:'Foreign assignment'});
  f.api.setWorkspace(state);f.api.openTask('root');const detail=f.nodes.get('task-detail');assert.match(detail.textContent,/<img src=x onerror=alert\(1\)>/);assert.equal(detail.querySelectorAll('img').length,0);assert.doesNotMatch(detail.textContent,/Foreign assignment/);
});

test('missing lineage and cycles remain visible without recursion failure',()=>{
  const f=fixture(),state=workspace();state.delegated_activities[0].parent_thread_id='nested-thread';state.delegated_activities.push({...state.delegated_activities[0],id:'legacy',thread_id:null,parent_thread_id:null,title:'Older observed assignment'});
  f.api.setWorkspace(state);f.api.openTask('root');assert.equal(f.nodes.get('task-detail').querySelectorAll('.delegated-activity').length,3);assert.match(f.nodes.get('task-detail').textContent,/Older observed assignment/);assert.match(f.nodes.get('task-detail').textContent,/Delegated by: Parent agent not recorded/);
});


test('task detail offers backend-authorized recovery for completed parent and hides it for ineligible tasks',()=>{
 const f=fixture(),state=workspace();state.tasks[0].recovery_available=true;state.delegated_activities[0].status='unknown';f.api.setWorkspace(state);f.api.renderDetail('root');
 assert.ok(f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Recover task'));assert.equal(f.nodes.get('task-detail').querySelectorAll('.badge')[0].textContent,'Completed');
 state.tasks[0].recovery_available=false;f.api.renderDetail('root');assert.equal(f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Recover task'),false);
 state.tasks[0].status='unknown';f.api.renderDetail('root');assert.equal(f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Recover task'),false);
});

test('unknown-role child and parent remain visible without fabricated role labels',()=>{
 const f=fixture(),state=workspace();state.delegated_activities[0].role=null;state.delegated_activities[0].title='Unattributed delegated task';f.api.setWorkspace(state);f.api.renderDetail('root');
 assert.match(f.nodes.get('task-detail').textContent,/Unattributed delegated task/);assert.match(f.nodes.get('task-detail').textContent,/Delegated by: Role not recorded/);assert.equal(f.nodes.get('task-detail').textContent.includes('Delegated by: null'),false);
});
