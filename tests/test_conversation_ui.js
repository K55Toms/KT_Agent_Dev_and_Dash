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
      this.scrollTop=0;this.clientHeight=100;
      this.attributes = {}; this.value = ''; this._text = '';
      this.classList = {toggle() {}};
      this.elements = new Proxy({}, {get: (target, key) => target[key] ||= new Element('input')});
    }
    get offsetTop(){return this.parentElement?.children.indexOf(this)*100||0;}
    get offsetHeight(){return 100;}
    get scrollHeight(){return this.children.length*100;}
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
    setSelectionRange(start,end=start,direction='none'){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;}
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
    activeElement: null, scrollingElement:{scrollTop:640}, body: new Element('body'), hidden: false,
    getElementById(id) {return nodes.get(id)||[...nodes.values()].flatMap(e=>e.querySelectorAll('*')).find(e=>e.id===id);},
    createElement(tag) {return new Element(tag);}, addEventListener() {},
    querySelector(selector) {if (!classes.has(selector)) classes.set(selector, new Element()); return classes.get(selector);},
    querySelectorAll(selector) {return selector === 'dialog' ? dialogs : selector === '[data-view]' ? views : [];},
  };
  const requests = [];
  const response = data => ({ok: true, json: async () => data});
  function fetch(url, options) {
    if (url.includes('/outputs')||url.includes('/review')||url.includes('/dismiss-attention')||url.includes('/conversation')||url.includes('/message')||url.includes('/respond')) return new Promise((resolve,reject)=>requests.push({url,options,resolve:data=>resolve(response(data)),fail:(data,status=403)=>resolve({ok:false,status,json:async()=>data}),reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={document, fetch, setInterval() {}, console,Event:class Event{constructor(type){this.type=type;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.conversationTest={loadConversation,renderConversation,renderAttention,openApprovalReview,openOutputs,showAllAttention,queueRender(){render=()=>renderAttention(selectedTasks(),selectedApprovals(selectedTasks()).filter(a=>a.status==="pending"));},selectConversation,setWorkspace(value){state=value;},setData(value){conversationData=value;renderConversation();},ready(){conversationId="task";state={connection:{status:"connected"},tasks:[{id:"task",status:"running"}],approvals:[]};stale=false;refresh=async()=>{};}};'),runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, settle, api:runtime.conversationTest};
}


function data(turn='turn-1',questions=[]) {return {task_id:'task',turn_id:turn,messages:[],questions,can_send:true,send_mode:'steer',agents:{}};}
function composer(f){const form=f.nodes.get('conversation-content').querySelector('.conversation-composer');return {form,input:form.querySelector('textarea'),send:form.querySelector('button')};}
const transcript=(count=8)=>({...data(),messages:Array.from({length:count},(_,i)=>({id:`message-${i}`,kind:'system',text:`Synthetic passage ${i}`}))});

test('metadata retains the actual message DOM; append preserves reader anchor and page, bottom readers follow',()=>{
  const f=fixture();f.api.ready();f.api.setData(transcript());
  const log=f.nodes.get('conversation-content').querySelector('.conversation-log'),passage=log.children[3];log.scrollTop=325;
  f.api.setData({...transcript(),turn_id:'new metadata'});
  assert.equal(f.nodes.get('conversation-content').querySelector('.conversation-log'),log);assert.equal(log.children[3],passage);assert.equal(log.scrollTop,325);
  f.api.setData(transcript(9));assert.equal(log.scrollTop,325);assert.equal(f.document.scrollingElement.scrollTop,640);
  let jump=f.nodes.get('conversation-content').querySelectorAll('button').find(b=>b.textContent==='Jump to latest');assert.equal(jump.hidden,false);
  jump.click();assert.equal(log.scrollTop,900);assert.equal(jump.hidden,true);
  log.scrollTop=800;f.api.setData(transcript(10));assert.equal(log.scrollTop,1000);
});

test('retained-history trimming keeps the visible passage and relative offset',()=>{
  const f=fixture();f.api.ready();f.api.setData(transcript());const log=f.nodes.get('conversation-content').querySelector('.conversation-log');log.scrollTop=325;
  const trimmed=transcript();trimmed.messages=trimmed.messages.slice(2);f.api.setData(trimmed);
  assert.equal(log.scrollTop,125);assert.match(log.children[1].textContent,/passage 3/);
});

test('task switching starts a fresh log and does not carry another task draft or scroll',async()=>{
  const f=fixture();f.api.ready();f.api.setData(transcript());composer(f).input.value='First task draft';
  f.nodes.get('conversation-content').querySelector('.conversation-log').scrollTop=325;
  f.nodes.get('conversation-task').value='second';f.api.selectConversation();
  f.requests.at(-1).resolve({...transcript(),task_id:'second'});await f.settle();
  assert.equal(f.nodes.get('conversation-content').querySelector('.conversation-log').scrollTop,0);assert.equal(composer(f).input.value,'');
});

test('attention counts filtered and omitted items and explicit show-all clears every inherited filter',()=>{
  const f=fixture();f.api.ready();
  const tasks=Array.from({length:6},(_,i)=>({id:`task-${i}`,title:`Task ${i}`,project_id:i%2?'other':'project',status:i<3?'failed':'unknown',role:'role'}));
  const approvals=tasks.map((t,i)=>({id:`decision-${i}`,task_id:t.id,status:'pending',kind:i===0?'question':'command',summary:`Decision ${i}`}));
  f.api.setWorkspace({tasks,approvals,questions:[],connection:{status:'connected'}});
  f.api.renderAttention(tasks.slice(0,2),approvals.slice(0,2));let target=f.nodes.get('attention-list');assert.match(target.textContent,/2 of 6 outstanding decisions/);assert.match(target.textContent,/Answer needed/);
  f.api.queueRender();for(const id of ['project-filter','search','status-filter','role-filter'])f.nodes.get(id).value='inherited';
  target.querySelector('button').click();for(const id of ['project-filter','search','status-filter','role-filter'])assert.equal(f.nodes.get(id).value,'');
  assert.equal(target.querySelectorAll('article').length,12);assert.match(target.textContent,/Showing 6 of 6 matching decisions and 6 of 6 matching notices/);
});

test('historical output association requires explicit task confirmation and preserves a failed draft',async()=>{
  const f=fixture();f.api.ready();f.api.setWorkspace({connection:{status:'connected'},projects:[],roles:[],tasks:[{id:'task',title:'Task',turn_id:'expected-turn',can_attach_output:true}],approvals:[]});
  f.api.openOutputs('task');const form=f.nodes.get('outputs-content').querySelector('form'),[path,confirm]=form.querySelectorAll('input');path.value='review.md';
  await submit(form);assert.equal(f.requests.length,0);confirm.checked=true;
  const pending=submit(form);assert.deepEqual(JSON.parse(f.requests.at(-1).options.body),{path:'review.md',expected_turn_id:'expected-turn',confirmed:true});
  f.requests.at(-1).reject(new Error('Synthetic checked-file rejection'));await pending;assert.equal(path.value,'review.md');assert.match(form.textContent,/Nothing retries automatically/);
});

test('unsupported request uses honest blocked modal without review IO or approval remedies',async()=>{
  const f=fixture();f.api.ready();const approval={id:'unsupported',task_id:'task',kind:'unsupported_input',status:'pending'};
  f.api.setWorkspace({connection:{status:'connected'},projects:[],roles:[],tasks:[{id:'task',status:'running'}],approvals:[approval]});
  await f.api.openApprovalReview(approval);assert.equal(f.requests.length,0);
  assert.match(f.nodes.get('approval-review-status').textContent,/unsupported and cannot be approved/);
  for(const id of ['approve-request','configure-project-approvals','approval-guidance-section','retry-approval-review','sensitive-reveal-section','decline-reviewed-request'])assert.equal(f.nodes.get(id).hidden,true,id);
  assert.equal(f.nodes.get('stop-reviewed-run').disabled,false);
});

test('Outputs opens only registered task report and withholds changed, missing and late content',async()=>{
  const f=fixture();f.api.ready();const output={id:'report',path:'report.md',title:'Synthetic report'};
  f.api.setWorkspace({connection:{status:'connected'},projects:[],roles:[],tasks:[{id:'task',title:'Task',outputs:[output]}],approvals:[]});
  f.api.openOutputs('task');const target=f.nodes.get('outputs-content');
  target.querySelector('button').click();assert.equal(f.requests.at(-1).url,'/api/tasks/task/outputs/report');
  f.requests.at(-1).resolve({task_id:'task',...output,state:'available',content:'Literal <script>report</script>',line_count:1});await f.settle();
  assert.equal(target.querySelector('pre').textContent,'Literal <script>report</script>');assert.equal(target.querySelector('pre').hidden,false);
  target.querySelector('button').click();f.requests.at(-1).resolve({task_id:'task',...output,state:'changed'});await f.settle();assert.equal(target.querySelector('pre').hidden,true);assert.match(target.textContent,/changed since/);
  target.querySelector('button').click();f.requests.at(-1).reject(new Error('Report is missing'));await f.settle();assert.match(target.textContent,/Report is missing/);
  target.querySelector('button').click();f.nodes.get('outputs-dialog').close();f.requests.at(-1).resolve({task_id:'task',...output,state:'available',content:'Late content'});await f.settle();assert.equal(target.querySelector('pre').textContent,'');
});
test('filtered-empty attention accounts for decisions outside the filters',()=>{
  const f=fixture();f.api.ready();f.api.setWorkspace({tasks:[],approvals:[{id:'elsewhere',task_id:'other',kind:'command',status:'pending'}],questions:[]});
  f.api.renderAttention([],[]);const text=f.nodes.get('attention-list').textContent;
  assert.match(text,/0 of 1 outstanding decisions/);assert.match(text,/Nothing matches the current filters/);assert.doesNotMatch(text,/Nothing waiting on you/);
});
test('output preview reports missing, blocked and scanner-unavailable states without content',async()=>{
  const f=fixture();f.api.ready();f.api.setWorkspace({tasks:[{id:'task',title:'Task',outputs:[{id:'report',path:'report.md'}]}],projects:[]});
  f.api.openOutputs('task');const target=f.nodes.get('outputs-content');
  for(const [state,status,label] of [['missing',404,'Report missing'],['blocked',403,'Report blocked'],['unavailable',503,'Report checks unavailable']]){
    target.querySelector('button').click();f.requests.at(-1).fail({state,error:'Synthetic withheld output'},status);await f.settle();
    assert.ok(target.textContent.includes(label));assert.equal(target.querySelector('pre').hidden,true);assert.equal(target.querySelector('pre').textContent,'');
  }
});
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
  before.value='Synthetic guidance still being edited';before.focus();before.setSelectionRange(11,20,'backward');
  const polling=f.api.loadConversation();f.requests.at(-1).resolve({...data('turn-2'),messages:[{kind:'system',text:'Synthetic new recorded event'}]});await polling;
  const after=composer(f).input;assert.notEqual(after,before);assert.equal(after.value,'Synthetic guidance still being edited');
  assert.equal(f.document.activeElement,after);assert.equal(after.selectionStart,11);assert.equal(after.selectionEnd,20);assert.equal(after.selectionDirection,'backward');assert.equal(after.disabled,false);
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
