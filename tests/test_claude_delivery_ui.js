'use strict';
// Plan 5 Task 7: Claude delivery wording. Shipped-script tests with a DOM double and synthetic HTTP (fixture copied from test_delivery_ui.js), not browser evidence.
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const {test}=require('node:test');
const vm=require('node:vm');
const {randomUUID}=require('node:crypto');
const base=path.join(__dirname,'..','dashboard','static');
const html=readFileSync(path.join(base,'index.html'),'utf8');
const script=readFileSync(path.join(base,'app.js'),'utf8');
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
    if (url.includes('/delivery')||url.includes('/check-plan')) return new Promise((resolve,reject)=>requests.push({url,options,resolve:data=>resolve(response(data)),fail:(status,message,extra={})=>resolve({ok:false,status,json:async()=>({error:message,...extra})}),reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={document, fetch, setInterval() {}, console,crypto:{randomUUID},Event:class Event{constructor(type){this.type=type;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.activityTest={renderDetail,openTask,loadDelivery,renderDelivery,setWorkspace(value){state=value;stale=false;},setStale(value){stale=value;}};'),runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, settle, api:runtime.activityTest};
}

function workspace(){return {connection:{status:'connected'},projects:[{id:'project',name:'Project'}],roles:[{id:'backend_developer',label:'Backend Developer'},{id:'qa_engineer',label:'QA Engineer'},{id:'code_quality_reviewer',label:'Code Quality Reviewer'}],approvals:[],delegated_activities:[],tasks:[{id:'subject',project_id:'project',title:'Implement feature',role:'backend_developer',status:'completed',thread_id:'subject-thread',turn_id:'subject-turn',created_at:'2026-10-25T09:00:00Z',updated_at:'2026-10-25T10:00:00Z'}]};}
function data(overrides={}){return {task_id:'subject',status:'awaiting_checks',snapshot_digest:'a'.repeat(64),policy_digest:'c'.repeat(64),plan_version:1,check_operation:null,review_operation:null,reason_codes:[],actions:{run_checks:true,start_review:false,review_decision:false},...overrides};}
function plan(version=1,commands=['python3 -m unittest']){return {project_id:'project',version,commands:commands.map((command,index)=>({id:'check-'+index,label:'Check '+(index+1),command})),approved_at:'2026-10-25T10:00:00Z'};}
function control(f,text){const result=f.nodes.get('task-detail').querySelectorAll('button').find(b=>b.textContent===text);assert.ok(result,'Missing control '+text);return result;}
function field(f,key){const result=f.nodes.get('task-detail').querySelectorAll('input,textarea').find(e=>e.dataset.deliveryFocus===key);assert.ok(result,'Missing field '+key);return result;}
async function opened(f,delivery=data(),approvedPlan=plan()){f.api.setWorkspace(workspace());f.api.openTask('subject');await f.settle();await resolveRefresh(f,delivery,approvedPlan);}
async function resolveRefresh(f,delivery,approvedPlan=plan()){const getDelivery=f.requests.find(r=>!r.answered&&r.url.endsWith('/delivery'));const getPlan=f.requests.find(r=>!r.answered&&r.url.endsWith('/check-plan')&&r.options.method==='GET');assert.ok(getDelivery);assert.ok(getPlan);getDelivery.answered=getPlan.answered=true;getDelivery.resolve(delivery);getPlan.resolve(approvedPlan);await f.settle();}
function mutation(f,suffix){const item=f.requests.find(r=>!r.answered&&r.url.endsWith(suffix)&&r.options.method==='POST');assert.ok(item,'Missing POST '+suffix);return item;}
function confirmRun(f){const confirmation=field(f,'confirm-run');confirmation.checked=true;confirmation.emit('change');}

const PONYTAIL_ROW=/Ponytail policy: Not applicable for Claude/;
function claudeWorkspace(){const state=workspace();state.tasks[0].provider='claude';state.tasks[0].delivery_available=true;return state;}

test('a Claude subject shows the Ponytail row as not applicable and never as passed',async()=>{
  const f=fixture();f.api.setWorkspace(claudeWorkspace());f.api.openTask('subject');await f.settle();
  await resolveRefresh(f,data({ponytail:'not_applicable'}));
  const text=f.nodes.get('task-detail').textContent;
  assert.match(text,PONYTAIL_ROW);assert.match(text,/not counted as passed/);
  assert.match(text,/Checks run as a Claude QA Engineer run in this project/);
  assert.doesNotMatch(text,/Checks run through Codex/);
  assert.match(text,/Awaiting checks/);
});

test('a ready Claude subject still shows Ponytail as not applicable beside ready',async()=>{
  const f=fixture();f.api.setWorkspace(claudeWorkspace());f.api.openTask('subject');await f.settle();
  await resolveRefresh(f,data({ponytail:'not_applicable',status:'ready',actions:{run_checks:false,start_review:false,review_decision:false}}));
  const text=f.nodes.get('task-detail').textContent;
  assert.match(text,/Ready for delivery/);assert.match(text,PONYTAIL_ROW);assert.match(text,/not counted as passed/);
});

test('a Codex subject keeps the Codex wording and has no Ponytail row',async()=>{
  const f=fixture();await opened(f);
  const text=f.nodes.get('task-detail').textContent;
  assert.doesNotMatch(text,PONYTAIL_ROW);
  assert.match(text,/Checks run through Codex with its existing sandbox and approval rules\./);
  assert.doesNotMatch(text,/Claude QA Engineer/);
});

test('the not-enforced notice has Claude wording only for a Claude subject',async()=>{
  const claude=fixture();claude.api.setWorkspace(claudeWorkspace());claude.api.openTask('subject');await claude.settle();
  await resolveRefresh(claude,data({status:'not_enforced'}));
  const claudeText=claude.nodes.get('task-detail').textContent;
  assert.match(claudeText,/This run was started before delivery readiness was available for Claude and cannot earn it\./);
  assert.doesNotMatch(claudeText,/launch policy/);
  const codex=fixture();await opened(codex,data({status:'not_enforced'}));
  const codexText=codex.nodes.get('task-detail').textContent;
  assert.match(codexText,/must pass the launch policy before it can earn delivery readiness/);
  assert.doesNotMatch(codexText,/started before delivery readiness was available/);
});
