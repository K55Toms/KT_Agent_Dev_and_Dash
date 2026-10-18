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
  const requests = [];
  const response = data => ({ok: true, json: async () => data});
  function fetch(url, options) {
    if (url.includes('/review') || url.includes('/respond')) return new Promise((resolve, reject) => requests.push({url, options, resolve: data => resolve(response(data)), reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={document, fetch, setInterval() {}, console};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.approvalTest={openApprovalReview,respondReviewedApproval,setWorkspace(value,fresh=true){state=value;stale=!fresh;checkApprovalReview();}};loadSettings();refresh();'), runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, settle, api:runtime.approvalTest};
}


const approval={id:'synthetic-request',task_id:'synthetic-task',kind:'command',status:'pending',available_decisions:['decline'],summary:'Synthetic command request'};
function workspace(overrides={}) {return {connection:{status:'connected'},projects:[{id:'synthetic-project',name:'Synthetic project'}],tasks:[{id:approval.task_id,title:'Synthetic task',project_id:'synthetic-project',role:'chief_of_staff',status:'waiting_approval'}],roles:[],approvals:[{...approval}],...overrides};}
function ready() {const f=fixture();f.api.setWorkspace(workspace());return f;}
function result(context={command:'printf "<script>literal</script>"',cwd:'/synthetic/project',reason:null,additionalPermissions:null}) {return {id:approval.id,task_id:approval.task_id,kind:approval.kind,review_id:randomUUID(),context};}

test('approval requires complete exact-identity review and sends its receipt only on an explicit click', async()=>{
  const f=ready();const pending=f.api.openApprovalReview(approval);
  assert.equal(f.nodes.get('approve-request').disabled,true);
  assert.equal(f.nodes.get('approval-review-context').hidden,true);
  assert.equal(f.requests.length,1);assert.match(f.requests[0].url,/\/review$/);
  const review=result();f.requests[0].resolve(review);await pending;
  assert.equal(f.nodes.get('approve-request').disabled,false);
  assert.equal(f.nodes.get('approval-review-context').textContent,JSON.stringify(review.context,null,2));
  assert.equal(f.nodes.get('approval-review-context').children.length,0);
  assert.equal(f.requests.length,1);
  const sending=f.api.respondReviewedApproval('accept');
  assert.equal(f.nodes.get('approve-request').disabled,true);
  assert.deepEqual(JSON.parse(f.requests[1].options.body),{decision:'accept',review_id:review.review_id});
  f.requests[1].resolve({status:'resolved'});
  // refresh intentionally never resolves in this isolated fixture; successful native decision closes first.
  await f.settle();assert.equal(f.nodes.get('approval-review-dialog').open,false);
  void sending;
});

test('unavailable, unsafe, malformed and wrong-request reviews never enable approval',async()=>{
  for(const value of [null,{...result(),id:'different'}, {...result(),task_id:'different'}, {...result(),kind:'file_change'}, {...result(),review_id:''}, {...result(),context:{}}, {...result(),context:'incomplete'}]){
    const f=ready();const pending=f.api.openApprovalReview(approval);f.requests[0].resolve(value);await pending;
    assert.equal(f.nodes.get('approve-request').disabled,true);assert.equal(f.nodes.get('approval-review-context').textContent,'');
    assert.match(f.nodes.get('approval-review-status').textContent,/unavailable/);
  }
  const f=ready();const pending=f.api.openApprovalReview(approval);f.requests[0].reject(new Error('Synthetic withheld context'));await pending;
  assert.equal(f.nodes.get('approve-request').disabled,true);assert.match(f.nodes.get('approval-review-error').textContent,/withheld/);
});

test('stale data, disconnection and resolved requests clear the review and prevent grants',async()=>{
  for(const update of [f=>f.api.setWorkspace(workspace(),false),f=>f.api.setWorkspace(workspace({connection:{status:'disconnected'}})),f=>f.api.setWorkspace(workspace({approvals:[{...approval,status:'resolved'}]})),f=>f.api.setWorkspace(workspace({approvals:[{...approval,kind:'file_change'}]})),f=>f.api.setWorkspace(workspace({approvals:[{...approval,reason:'Synthetic changed request'}]}))]){
    const f=ready();const pending=f.api.openApprovalReview(approval);f.requests[0].resolve(result());await pending;
    update(f);assert.equal(f.nodes.get('approve-request').disabled,true);assert.equal(f.nodes.get('approval-review-context').textContent,'');
    await f.api.respondReviewedApproval('accept');assert.equal(f.requests.length,1);
    f.api.setWorkspace(workspace());await f.api.respondReviewedApproval('accept');assert.equal(f.requests.length,1,'reconnection does not revive receipt');
  }
});

test('closing or invalidating during loading rejects late review responses and restores focus',async()=>{
  for(const close of [true,false]){
    const f=ready();const origin=f.document.createElement('button');origin.focus();const pending=f.api.openApprovalReview(approval);
    if(close)f.nodes.get('approval-review-dialog').close();else f.api.setWorkspace(workspace(),false);
    f.requests[0].resolve(result());await pending;
    assert.equal(f.nodes.get('approve-request').disabled,true);assert.equal(f.nodes.get('approval-review-context').textContent,'');
    if(close)assert.equal(f.document.activeElement,origin);
  }
});

test('a failed grant cannot be automatically retried or reused',async()=>{
  const f=ready();const pending=f.api.openApprovalReview(approval);f.requests[0].resolve(result());await pending;
  void f.api.respondReviewedApproval('accept');f.requests[1].reject(new Error('Synthetic expired review'));await f.settle();
  assert.equal(f.nodes.get('approve-request').disabled,true);assert.match(f.nodes.get('approval-review-error').textContent,/No automatic retry/);
  assert.equal(f.requests.length,2);
});

test('full large file diffs stay literal and untruncated',async()=>{
  const f=ready();const file={...approval,kind:'file_change'};f.api.setWorkspace(workspace({approvals:[file]}));
  const pending=f.api.openApprovalReview(file);const context={changes:[{path:'/synthetic/file',kind:'update',diff:'<img src=x>\n'.repeat(10000)}],grantRoot:null};
  f.requests[0].resolve({...result(context),kind:'file_change'});await pending;
  assert.equal(f.nodes.get('approval-review-context').textContent,JSON.stringify(context,null,2));
  assert.equal(f.nodes.get('approve-request').disabled,false);
  assert.match(html, /id="approval-review-context"[^>]*tabindex="0"/);
});


test('a completed parent with active children retains the stop action during review',async()=>{
  const f=ready();const task={...workspace().tasks[0],status:'completed',active_children:1};
  f.api.setWorkspace(workspace({tasks:[task]}));
  const pending=f.api.openApprovalReview(approval);
  assert.equal(f.nodes.get('stop-reviewed-run').disabled,false);
  assert.equal(f.nodes.get('stop-reviewed-run').textContent,'Stop active agents');
  f.requests[0].resolve(result());await pending;
  f.api.setWorkspace(workspace({tasks:[{...task,active_children:0}]}));
  assert.equal(f.nodes.get('stop-reviewed-run').disabled,true);
});
