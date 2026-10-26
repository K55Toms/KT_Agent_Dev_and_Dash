'use strict';
// Shipped-script interaction tests with a DOM double and synthetic HTTP, not browser/native evidence.
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
    get options() {return this.children;}
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
      const id=button[1].match(/id="([^"]+)"/);if(id&&nodes.has(id[1])){const existing=nodes.get(id[1]);if(button[1].includes('data-close'))existing.setAttribute('data-close','');dialog.append(existing);continue;}
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
    if (url.endsWith('/delete')||url==='/api/state') return new Promise((resolve,reject)=>requests.push({url,options,resolve:data=>resolve(response(data)),fail:(status,message)=>resolve({ok:false,status,json:async()=>({error:message})}),reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={document, fetch, Option:class Option extends Element{constructor(label,value){super('option');this.textContent=label;this.value=value;}}, setInterval() {}, console,crypto:{randomUUID},Event:class Event{constructor(type){this.type=type;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.activityTest={renderDetail,openTask,openRunDeletion,confirmRunDeletion,renderRunDeletion,renderRecovery,refresh,getState(){return state;},setWorkspace(value){state=value;stale=false;},setRecovery(id){recoveryId=id;recoveryData=null;},setStale(value){stale=value;}};'),runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, settle, api:runtime.activityTest};
}

function workspace(overrides={}){return {connection:{status:'connected'},projects:[{id:'project',name:'Project'}],roles:[{id:'chief_of_staff',label:'Chief of Staff'}],approvals:[],delegated_activities:[],tasks:[{id:'subject',project_id:'project',title:'Old unknown run',role:'chief_of_staff',status:'unknown',can_delete:true,deletion_version:'a'.repeat(64),active_children:0,created_at:'2026-10-25T09:00:00Z',updated_at:'2026-10-25T10:00:00Z',...overrides}]};}
function opened(overrides={}){const f=fixture();f.api.setWorkspace(workspace(overrides));f.api.openTask('subject');return f;}
function confirm(f){f.nodes.get('delete-run-acknowledge').checked=true;f.nodes.get('delete-run-acknowledge').emit('change');return f.nodes.get('delete-run-confirm').click();}
function deleteControl(f,target='task-detail'){return f.nodes.get(target).querySelectorAll('button').find(b=>b.textContent==='Delete run');}

test('unknown run exposes direct delete with explicit confirmation and cancel sends nothing',()=>{
 const f=opened();assert.equal(deleteControl(f).disabled,false);deleteControl(f).click();
 assert.equal(f.nodes.get('delete-run-dialog').open,true);assert.equal(f.document.activeElement,f.nodes.get('delete-run-cancel'));
 assert.equal(f.nodes.get('delete-run-confirm').disabled,true);assert.match(f.nodes.get('delete-run-name').textContent,/Old unknown run.*subject/);
 f.nodes.get('delete-run-cancel').click();assert.equal(f.nodes.get('delete-run-dialog').open,false);assert.equal(f.requests.length,0);assert.equal(f.api.getState().tasks.length,1);
});
test('unknown deletion is available in recovery without an assessment receipt',()=>{
 const f=opened();f.api.setRecovery('subject');f.api.renderRecovery();assert.equal(deleteControl(f,'recovery-content').disabled,false);deleteControl(f,'recovery-content').click();assert.equal(f.nodes.get('delete-run-dialog').open,true);
});
test('active or unavailable deletion explains blocker and sends nothing',()=>{
 for(const overrides of [{status:'running',can_delete:false,deletion_blocker:'Stop the run first.'},{can_delete:undefined,deletion_version:undefined}]){
  const f=opened(overrides);assert.equal(deleteControl(f).disabled,true);f.api.openRunDeletion('subject');assert.equal(f.nodes.get('delete-run-dialog').open,false);assert.equal(f.requests.length,0);
 }
});
test('confirmed deletion sends exact version once and removes local task after server confirmation',async()=>{
 const f=opened();deleteControl(f).click();confirm(f);await f.settle();
 const request=f.requests.find(r=>r.url.endsWith('/delete'));assert.deepEqual(JSON.parse(request.options.body),{expected_version:'a'.repeat(64),confirmed:true});assert.equal(f.nodes.get('delete-run-confirm').disabled,true);
 f.nodes.get('delete-run-confirm').click();assert.equal(f.requests.filter(r=>r.url.endsWith('/delete')).length,1);
 request.resolve({task_id:'subject',deleted:true});await f.settle();assert.equal(f.api.getState().tasks.length,0);assert.equal(f.nodes.get('delete-run-dialog').open,false);assert.equal(f.nodes.get('task-dialog').open,false);assert.equal(f.document.activeElement,f.nodes.get('main'));
});
test('changed version invalidates reviewed confirmation before mutation',()=>{
 const f=opened();deleteControl(f).click();f.api.setWorkspace(workspace({deletion_version:'b'.repeat(64)}));confirm(f);assert.equal(f.nodes.get('delete-run-confirm').disabled,true);assert.match(f.nodes.get('delete-run-status').textContent,/changed/);assert.equal(f.requests.length,0);
});
test('server rejection keeps run and displays error',async()=>{
 const f=opened();deleteControl(f).click();confirm(f);await f.settle();f.requests.find(r=>r.url.endsWith('/delete')).fail(409,'Run changed. Refresh and review again.');await f.settle();assert.equal(f.api.getState().tasks.length,1);assert.equal(f.nodes.get('delete-run-dialog').open,true);assert.match(f.nodes.get('delete-run-error').textContent,/Run changed/);
});
test('uncertain outcome cannot be resent after close and reopen; fresh absence reconciles it',async()=>{
 const f=opened();deleteControl(f).click();confirm(f);await f.settle();f.requests.find(r=>r.url.endsWith('/delete')).reject(new Error('Network interrupted'));await f.settle();
 assert.equal(f.nodes.get('delete-run-confirm').disabled,true);assert.equal(f.nodes.get('delete-run-refresh').hidden,false);f.nodes.get('delete-run-cancel').click();f.api.openRunDeletion('subject');confirm(f);assert.equal(f.requests.filter(r=>r.url.endsWith('/delete')).length,1);
 f.nodes.get('delete-run-refresh').click();await f.settle();const state=f.requests.find(r=>r.url==='/api/state');state.resolve({...workspace(),tasks:[]});await f.settle();assert.equal(f.nodes.get('delete-run-dialog').open,false);assert.equal(f.api.getState().tasks.length,0);
});

test('completed automatic refresh leaves uncertain status check available',async()=>{
 const f=opened();deleteControl(f).click();confirm(f);await f.settle();f.requests.find(r=>r.url.endsWith('/delete')).reject(new Error('Network interrupted'));await f.settle();
 const pending=f.api.refresh();await f.settle();f.requests.find(r=>r.url==='/api/state').resolve(workspace());await pending;
 assert.equal(f.nodes.get('delete-run-dialog').open,true);assert.equal(f.nodes.get('delete-run-refresh').disabled,false);assert.equal(f.nodes.get('delete-run-confirm').disabled,true);
});

for(const failure of ['service failure','network uncertainty'])test(`${failure} reconciles an existing run into a fresh explicit deletion decision`,async()=>{
 const f=opened();deleteControl(f).click();confirm(f);await f.settle();const first=f.requests.find(r=>r.url.endsWith('/delete'));
 if(failure==='service failure')first.fail(503,'Storage unavailable. Nothing was removed.');else first.reject(new Error('Connection interrupted'));
 await f.settle();assert.equal(f.nodes.get('delete-run-confirm').disabled,true);
 f.nodes.get('delete-run-refresh').click();await f.settle();f.requests.find(r=>r.url==='/api/state').resolve(workspace({deletion_version:'b'.repeat(64)}));await f.settle();
 assert.equal(f.requests.filter(r=>r.url.endsWith('/delete')).length,1);assert.equal(f.nodes.get('delete-run-acknowledge').checked,false);assert.equal(f.nodes.get('delete-run-acknowledge').disabled,false);assert.equal(f.nodes.get('delete-run-confirm').disabled,true);assert.equal(f.nodes.get('delete-run-refresh').hidden,true);
 confirm(f);await f.settle();const deletes=f.requests.filter(r=>r.url.endsWith('/delete'));assert.equal(deletes.length,2);assert.deepEqual(JSON.parse(deletes[1].options.body),{expected_version:'b'.repeat(64),confirmed:true});
});

test('cancel after recovery polling restores focus to the replacement Delete control',()=>{
 const f=opened();f.api.setRecovery('subject');f.nodes.get('recovery-dialog').showModal();f.api.renderRecovery();
 const original=deleteControl(f,'recovery-content');original.click();assert.equal(f.nodes.get('delete-run-dialog').returnFocus,original);
 f.api.renderRecovery();original.isConnected=false;const replacement=deleteControl(f,'recovery-content');assert.notEqual(original,replacement);
 f.nodes.get('delete-run-cancel').click();assert.equal(f.nodes.get('delete-run-dialog').open,false);assert.equal(f.document.activeElement,replacement);assert.equal(f.requests.length,0);
});
