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
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.conversationTest={loadConversation,renderConversation,renderAttention,setWorkspace(value){state=value;},setData(value){conversationData=value;renderConversation();},ready(){conversationId="task";state={connection:{status:"connected"},tasks:[{id:"task",status:"running"}],approvals:[]};stale=false;refresh=async()=>{};}};'),runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, settle, api:runtime.conversationTest};
}


function data(turn='turn-1',questions=[]) {return {task_id:'task',turn_id:turn,messages:[],questions,can_send:true,send_mode:'steer',agents:{}};}
function composer(f){const form=f.nodes.get('conversation-content').querySelector('.conversation-composer');return {form,input:form.querySelector('textarea'),send:form.querySelector('button')};}
const submit=form=>form.emit('submit',{preventDefault(){}})[0];

test('conversation accepts three successive prompts and captures each fresh expected turn',async()=>{
  const f=fixture();f.api.ready();f.api.setData(data());
  for(let index=1;index<=3;index++){
    const {form,input,send}=composer(f);input.value=`Synthetic guidance ${index}`;
    const pending=submit(form);assert.equal(send.disabled,true);
    const post=f.requests.at(-1);assert.equal(JSON.parse(post.options.body).expected_turn_id,`turn-${index}`);
    post.resolve({status:'sent'});await f.settle();
    const poll=f.requests.at(-1);assert.match(poll.url,/conversation$/);poll.resolve(data(`turn-${index+1}`));await pending;
    assert.equal(composer(f).send.disabled,false);assert.equal(composer(f).input.value,'');
  }
  assert.equal(f.requests.filter(r=>r.url.endsWith('/message')).length,3);
});

test('successful conversation polling retains the unsent draft, keyboard focus and caret position',async()=>{
  const f=fixture();f.api.ready();f.api.setData(data());const before=composer(f).input;
  before.value='Synthetic guidance still being edited';before.focus();before.setSelectionRange(11,11);
  const polling=f.api.loadConversation();f.requests.at(-1).resolve({...data('turn-2'),messages:[{kind:'system',text:'Synthetic new recorded event'}]});await polling;
  const after=composer(f).input;assert.notEqual(after,before);assert.equal(after.value,'Synthetic guidance still being edited');
  assert.equal(f.document.activeElement,after);assert.equal(after.selectionStart,11);assert.equal(after.disabled,false);
  assert.equal(f.requests.filter(r=>r.url.endsWith('/message')).length,0);
});

test('failed conversation refresh keeps the unsent draft and restores sending after explicit refresh',async()=>{
  const f=fixture();f.api.ready();f.api.setData(data());composer(f).input.value='Synthetic draft to retain';
  const loading=f.api.loadConversation();f.requests.at(-1).reject(new Error('Synthetic offline'));await loading;
  assert.equal(composer(f).input.value,'Synthetic draft to retain');assert.equal(composer(f).send.disabled,true);
  const retry=f.api.loadConversation();f.requests.at(-1).resolve(data('turn-2'));await retry;
  assert.equal(composer(f).input.value,'Synthetic draft to retain');assert.equal(composer(f).send.disabled,false);
});

test('sending failure retains text and successful refresh allows a deliberate retry with current turn',async()=>{
  const f=fixture();f.api.ready();f.api.setData(data());const first=composer(f);first.input.value='Synthetic retained message';
  const pending=submit(first.form);f.requests.at(-1).reject(new Error('Synthetic request rejected'));await f.settle();
  f.requests.at(-1).resolve(data('turn-2'));await pending;
  const current=composer(f);assert.equal(current.input.value,'Synthetic retained message');assert.equal(current.send.disabled,false);
  assert.match(current.form.querySelector('.form-error').textContent,/will not retry automatically/);
  const retry=submit(current.form);assert.equal(JSON.parse(f.requests.at(-1).options.body).expected_turn_id,'turn-2');
  f.requests.at(-1).resolve({status:'sent'});await f.settle();f.requests.at(-1).resolve(data('turn-3'));await retry;
});

test('pending question can be answered, followed by a new question and further guidance',async()=>{
  const f=fixture();f.api.ready();
  const question=id=>({id,status:'pending',questions:[{id:`${id}-field`,question:'Synthetic advisory question',options:[]}]});
  for(let index=1;index<=2;index++){
    f.api.setData(data(`turn-${index}`,[question(`question-${index}`)]));
    const form=f.nodes.get('conversation-content').querySelector('.question-card');form.querySelector('textarea').value='Synthetic answer';
    const pending=submit(form);const count=f.requests.length;
    composer(f).input.value='Concurrent guidance';await submit(composer(f).form);assert.equal(f.requests.length,count);
    f.requests.at(-1).resolve({status:'resolved'});await f.settle();f.requests.at(-1).resolve(data(`turn-${index+1}`));await pending;
    assert.equal(composer(f).send.disabled,false);
  }
});

test('a blocked composer explains the actual runtime reason',()=>{
  const f=fixture();f.api.ready();f.api.setData({...data(),can_send:false,blocked_reason:'Answer the pending question or interrupt the run'});
  assert.match(composer(f).form.textContent,/Answer the pending question/);
});


test('pending native requests are directly reviewable from a blocked conversation',async()=>{
  const f=fixture();f.api.ready();f.api.setWorkspace({connection:{status:'connected'},projects:[],roles:[],tasks:[{id:'task'}],approvals:[{id:'approval',task_id:'task',status:'pending',kind:'command',summary:'Synthetic native decision',available_decisions:['accept','decline']}]});
  f.api.setData({...data(),can_send:false,blocked_reason:'Resolve the pending approval'});
  const panel=f.nodes.get('conversation-content').querySelector('.conversation-decisions');assert.match(panel.textContent,/Synthetic native decision/);
  panel.querySelector('button').click();assert.equal(f.requests.at(-1).url,'/api/approvals/approval/review');
  const dialog=f.nodes.get('approval-review-dialog');assert.equal(dialog.open,true);assert.equal(f.nodes.get('approve-request').disabled,true);
  const context={command:'/usr/bin/true',cwd:'/synthetic/project',reason:'Synthetic scoped review'};f.requests.at(-1).resolve({id:'approval',task_id:'task',kind:'command',review_id:'synthetic-review-receipt',context});await f.settle();
  assert.equal(dialog.open,true);assert.equal(f.nodes.get('approval-review-context').textContent,JSON.stringify(context,null,2));assert.equal(f.nodes.get('approve-request').disabled,false);
  assert.equal(f.requests.filter(r=>r.url.endsWith('/message')).length,0);
});

test('dismiss acknowledges the exact notice while preserving task history and pending decisions',async()=>{
  const f=fixture();f.api.ready();const task={id:'task',status:'failed',title:'Synthetic old failure',attention_version:'version-1',active_children:0};
  f.api.setWorkspace({connection:{status:'connected'},tasks:[task],approvals:[]});f.api.renderAttention([task],[]);
  const notice=f.nodes.get('attention-list').querySelector('article');const dismiss=notice.querySelectorAll('button').find(b=>b.textContent==='Dismiss notice');
  const pending=dismiss.click()[0];assert.deepEqual(JSON.parse(f.requests.at(-1).options.body),{version:'version-1'});assert.equal(dismiss.disabled,true);
  f.requests.at(-1).resolve({task_id:'task',attention_version:'version-1',attention_dismissed:true});await pending;
  assert.equal(task.status,'failed');assert.equal(task.attention_dismissed,true);assert.equal(f.nodes.get('attention-list').querySelectorAll('article').length,0);
  f.api.renderAttention([task],[{id:'pending',task_id:'task',summary:'Synthetic pending request'}]);
  assert.match(f.nodes.get('attention-list').textContent,/Synthetic pending request/);assert.doesNotMatch(f.nodes.get('attention-list').textContent,/Dismiss notice/);
  const newFailure={...task,attention_version:'version-2',attention_dismissed:false};f.api.renderAttention([newFailure],[]);
  assert.match(f.nodes.get('attention-list').textContent,/Synthetic old failure/);
});

test('an unconfirmed dismissal does not hide a failure, and active child work cannot be dismissed',async()=>{
  const f=fixture();f.api.ready();const task={id:'task',status:'unknown',title:'Synthetic failure',attention_version:'version-1',active_children:0};
  f.api.setWorkspace({connection:{status:'connected'},tasks:[task],approvals:[]});f.api.renderAttention([task],[]);
  const notice=f.nodes.get('attention-list').querySelector('article');const dismiss=notice.querySelectorAll('button').find(b=>b.textContent==='Dismiss notice');
  const pending=dismiss.click()[0];f.requests.at(-1).resolve({task_id:'other',attention_version:'version-1',attention_dismissed:true});await pending;
  assert.match(notice.textContent,/dismissal was not confirmed/);assert.equal(task.attention_dismissed,undefined);assert.equal(dismiss.disabled,false);
  f.api.renderAttention([{...task,active_children:1}],[]);assert.doesNotMatch(f.nodes.get('attention-list').textContent,/Dismiss notice/);
});


test('conversation exposes recovery by backend eligibility even when parent completed',()=>{
 const f=fixture();f.api.ready();f.api.setWorkspace({connection:{status:'connected'},tasks:[{id:'task',status:'completed',recovery_available:true}],approvals:[]});
 f.api.setData({...data(),can_send:false,recovery_available:true});
 assert.ok(f.nodes.get('conversation-content').querySelectorAll('button').some(b=>b.textContent==='Recover task'));assert.match(f.nodes.get('conversation-content').textContent,/delegated work needs recovery checks/);
 f.api.setData({...data(),can_send:false,recovery_available:false});assert.equal(f.nodes.get('conversation-content').querySelectorAll('button').some(b=>b.textContent==='Recover task'),false);
});
