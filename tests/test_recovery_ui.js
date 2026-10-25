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

function fixture({clipboardFails=false}={}) {
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
    getAttribute(key) {return this.attributes[key] ?? null;}
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
    setSelectionRange(start,end=start,direction="none"){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;}
    select(){this.selected=true;}
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
  const requests = [], copied=[];
  const response = data => ({ok: true, json: async () => data});
  function fetch(url, options) {
    if (url.includes('/recovery')||url.includes('/interrupt')||url.includes('/review')||url.includes('/dismiss-attention')||url.includes('/conversation')||url.includes('/message')||url.includes('/respond')) return new Promise((resolve,reject)=>requests.push({url,options,resolve:data=>resolve(response(data)),reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={navigator:{clipboard:{writeText:async text=>{if(clipboardFails)throw new Error("Clipboard denied");copied.push(text);}}},document, URL, crypto:{randomUUID}, fetch, setInterval() {}, console,Event:class Event{constructor(type){this.type=type;}}};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.conversationTest={openRecovery,loadRecovery,loadRecoveryAuth,recoveryAuthAction,renderRecovery,recoveryOperation,setHandoff(value,age=0){recoveryHandoff=value;recoveryHandoffCheckedAt=Date.now()-age;renderRecovery();},setTask(value){state.tasks[0]={...state.tasks[0],...value};renderRecovery();},setEvidence(value){recoveryEvidence=value;renderRecovery();},setConnection(value){state.connection.status=value;renderRecovery();},setData(value){recoveryData=value;renderRecovery();},setChat(value){recoveryChat=value;renderRecovery();},draft(){return recoveryDraft();},ready(){recoveryId="task";recoveryFresh=true;state={connection:{status:"connected"},projects:[{id:"p",name:"Project",path:"/project"}],roles:[{id:"chief_of_staff",label:"Coordinator"}],tasks:[{id:"task",project_id:"p",status:"unknown"}],approvals:[]};stale=false;refresh=async()=>{};}};'),runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, copied, settle, api:runtime.conversationTest};
}


function summary(overrides={}) {return {task_id:'task',revision:1,state:'checked',checked_at:'2026-10-19T09:00:00Z',coverage:'partial',execution_clearance:false,children:{count:1,unresolved:1},observations:[],reason_codes:['old_work_unresolved'],receipt_id:'receipt',assessment:null,plan:null,operation:null,actions:{check:true,assess:true,review_plan:true,continue:false},capabilities:{assessment:true,new_linked:true,same_thread:false},...overrides};}
function action(f,text){return f.nodes.get('recovery-content').querySelectorAll('button').find(b=>b.textContent===text);}
function field(f,key){return f.nodes.get('recovery-content').querySelectorAll('textarea,select').find(e=>e.dataset.recoveryField===key);}

test('unknown work permits assessment but cannot continue from idle or partial evidence',()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());
 assert.equal(action(f,'Start assessment conversation').disabled,false);
 assert.equal(action(f,'Approve and continue development'),undefined);
 assert.match(f.nodes.get('recovery-content').textContent,/Idle or no recent events/);
 f.api.setData(summary({capabilities:{assessment:false}}));
 assert.equal(action(f,'Start assessment conversation').disabled,true);
 assert.match(f.nodes.get('recovery-content').textContent,/capability is not verified/);
});

test('editing a reviewed instruction invalidates continuation immediately and retains draft on refresh',()=>{
 const f=fixture();f.api.ready();const data=summary({assessment:{task_id:'assessment',status:'completed'},plan:{id:'plan',version:2,digest:'digest',instruction:'Inspect and fix',role:'chief_of_staff',target_strategy:'new_linked',effective_approval_mode:'manual'},actions:{check:true,review_plan:true,continue:true}});f.api.setData(data);
 assert.equal(action(f,'Approve and continue development').disabled,false);
 const input=field(f,'instruction');input.value='Different work';input.emit('input');
 assert.equal(action(f,'Approve and continue development').disabled,true);
 f.api.setData(data);assert.equal(field(f,'instruction').value,'Different work');
 assert.equal(action(f,'Approve and continue development').disabled,true);
});

test('assessment sends only an explicitly entered question with captured turn identity',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary({assessment:{task_id:'assessment',status:'completed'}}));f.api.setChat({can_send:true,turn_id:'current-turn',messages:[]});
 const input=field(f,'followup');input.value='What remains uncertain?';input.emit('input');
 action(f,'Send question').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/assessment/message'));assert.ok(sent);
 assert.deepEqual(JSON.parse(sent.options.body),{text:'What remains uncertain?',expected_turn_id:'current-turn'});
 assert.equal(f.requests.filter(r=>r.url.includes('/continue')).length,0);
 sent.reject(new Error('Stale turn'));await f.settle();
 assert.equal(f.api.draft().followup,'What remains uncertain?');
 assert.match(f.nodes.get('recovery-error').textContent,/Nothing will resend automatically/);
});

test('lost dispatch retains operation identity and does not retry automatically',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());
 const input=field(f,'question');input.value='Assess checked evidence';input.emit('input');
 const operation=f.api.recoveryOperation('assess');assert.match(operation,/^[0-9a-f]{32}$/);action(f,'Start assessment conversation').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/recovery/assess'));assert.ok(sent);
 const body=JSON.parse(sent.options.body);assert.equal(body.operation_id,operation);assert.equal(body.text,'Assess checked evidence');assert.deepEqual(body.selected_message_ids,[]);assert.equal(body.confirmed,true);
 sent.reject(new Error('Connection lost'));await f.settle();
 assert.equal(f.api.recoveryOperation('assess'),operation);
 assert.equal(f.requests.filter(r=>r.url.endsWith('/recovery/assess')).length,1);
 assert.equal(f.api.draft().question,'Assess checked evidence');
});

test('human annotation records evidence without starting work or relabelling native state',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary({actions:{check:true},capabilities:{assessment:false,new_linked:false,same_thread:false}}));
 const note=field(f,'note');note.value='Reviewed local changes; old execution still uncertain.';note.emit('input');
 const disposition=field(f,'disposition');disposition.value='reviewed';disposition.emit('change');
 action(f,'Save assessment note').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/recovery/disposition'));assert.ok(sent);
 assert.deepEqual(JSON.parse(sent.options.body),{expected_revision:1,disposition:'reviewed',note:'Reviewed local changes; old execution still uncertain.',confirmed:true});
 assert.equal(f.requests.filter(r=>/\/(assess|continue|message)$/.test(r.url)).length,0);
 assert.match(f.nodes.get('recovery-content').textContent,/does not change the native outcome/);
});

test('cancel decision distinguishes prepared dispatch from uncertain dispatched work',()=>{
 const f=fixture();f.api.ready();f.api.setData(summary({operation:{id:'op',kind:'continue',status:'prepared'},actions:{cancel:true}}));assert.ok(action(f,'Cancel before dispatch'));
 f.api.setData(summary({operation:{id:'op',kind:'continue',status:'delivery_unknown'},actions:{cancel:true}}));assert.ok(action(f,'Request stop and reconcile'));assert.equal(action(f,'Cancel before dispatch'),undefined);
});

test('continuation requires its own click and sends exactly the reviewed plan binding',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary({assessment:{task_id:'assessment',status:'reviewable'},plan:{id:'plan-v3',version:3,digest:'reviewed-digest',instruction:'Fresh checked work',role:'chief_of_staff',target_strategy:'new_linked',effective_approval_mode:'manual'},actions:{check:true,review_plan:true,continue:true}}));
 assert.equal(f.requests.length,0);
 action(f,'Approve and continue development').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/recovery/continue'));assert.ok(sent);
 const body=JSON.parse(sent.options.body);assert.equal(body.plan_id,'plan-v3');assert.equal(body.plan_digest,'reviewed-digest');assert.equal(body.assessment_task_id,'assessment');assert.equal(body.confirmed,true);assert.equal(body.receipt_id,'receipt');assert.equal(body.instruction,undefined);
 assert.equal(action(f,'Approve and continue development').disabled,true);
});

test('changing the chosen role disables approval before saving a new plan',()=>{
 const f=fixture();f.api.ready();f.api.setData(summary({assessment:{task_id:'assessment',status:'reviewable'},plan:{id:'plan',version:1,digest:'digest',instruction:'Fresh work',role:'chief_of_staff',target_strategy:'new_linked'},actions:{continue:true}}));
 const select=field(f,'role');select.value='technical_architect';select.emit('change');assert.equal(action(f,'Approve and continue development').disabled,true);assert.equal(f.api.draft().dirty,true);
});

test('metadata refresh failure retains a typed question and disables model dispatch',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());const input=field(f,'question');input.value='Keep this question';input.emit('input');
 const pending=f.api.loadRecovery();await f.settle();const check=f.requests.find(r=>r.url.endsWith('/recovery'));assert.ok(check);check.reject(new Error('Disconnected'));await pending;
 assert.equal(field(f,'question').value,'Keep this question');assert.equal(action(f,'Start assessment conversation').disabled,true);assert.match(f.nodes.get('recovery-error').textContent,/Drafts are retained/);
});

test('a real async recovery refresh re-enables permitted actions after loading',async()=>{
 const f=fixture();f.api.ready();const pending=f.api.loadRecovery();await f.settle();
 f.requests.find(r=>r.url==='/api/recovery-auth').resolve({state:'signed_out',authenticated:false,plan_enabled:false,generation:1});
 f.requests.find(r=>r.url.endsWith('/task/recovery')).resolve(summary());await f.settle();
 f.requests.find(r=>r.url.endsWith('/task/conversation')).resolve({messages:[]});await pending;
 assert.equal(action(f,'Start assessment conversation').disabled,false);
 assert.ok(action(f,'Connect ChatGPT for assessment'));
 assert.equal(f.requests.filter(r=>r.url.endsWith('/assess')).length,0);
});

test('sign-in status exposes explicit connection choice without starting model work',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());
 const pending=f.api.loadRecoveryAuth();await f.settle();
 f.requests.find(r=>r.url==='/api/recovery-auth').resolve({state:'plan_unavailable',authenticated:true,plan_enabled:false,generation:2});await pending;f.api.renderRecovery();
 assert.match(f.nodes.get('recovery-content').textContent,/has not granted eligible ChatGPT plan access/);
 assert.ok(action(f,'Connect ChatGPT for assessment'));
 assert.equal(f.requests.filter(r=>r.options?.method==='POST').length,0);
});

test('sign-in requires an explicit OpenAI link and never dispatches assessment work',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());
 const pending=f.api.recoveryAuthAction('start');await f.settle();
 const start=f.requests.find(r=>r.url==='/api/recovery-auth/start');assert.ok(start);
 start.resolve({authorization_url:'https://auth.openai.com/api/accounts/authorize?state=synthetic'});await f.settle();
 f.requests.find(r=>r.url==='/api/recovery-auth').resolve({state:'signing_in',authenticated:false,plan_enabled:false,generation:2});await f.settle();
 const link=f.nodes.get('recovery-content').querySelectorAll('a').find(a=>a.textContent==='Continue with ChatGPT');assert.ok(link);assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');
 assert.equal(f.requests.filter(r=>/\/(assess|continue|message)$/.test(r.url)).length,0);
 f.requests.find(r=>r.url.endsWith('/task/recovery')).resolve(summary());await f.settle();
 f.requests.find(r=>r.url.endsWith('/task/conversation')).resolve({messages:[]});await pending;
});

test('sign-in rejects a substituted external destination',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());
 const pending=f.api.recoveryAuthAction('start');await f.settle();
 f.requests.find(r=>r.url==='/api/recovery-auth/start').resolve({authorization_url:'https://example.invalid/api/accounts/authorize'});await f.settle();
 assert.match(f.nodes.get('recovery-error').textContent,/Unsupported sign-in destination/);
 f.requests.find(r=>r.url==='/api/recovery-auth').resolve({state:'error',authenticated:false,plan_enabled:false,generation:2});await f.settle();
 assert.equal(f.nodes.get('recovery-content').querySelectorAll('a').some(a=>a.textContent==='Continue with ChatGPT'),false);
 f.requests.find(r=>r.url.endsWith('/task/recovery')).resolve(summary());await f.settle();
 f.requests.find(r=>r.url.endsWith('/task/conversation')).resolve({messages:[]});await pending;
});

test('unconfirmed remote revocation is visible without claiming remote requests stopped',async()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());
 const pending=f.api.loadRecoveryAuth();await f.settle();
 f.requests.find(r=>r.url==='/api/recovery-auth').resolve({state:'signed_out',authenticated:false,plan_enabled:false,generation:3,remote_revocation_confirmed:false});await pending;f.api.renderRecovery();
 assert.match(f.nodes.get('recovery-content').textContent,/OpenAI revocation was not confirmed/);
 assert.match(f.nodes.get('recovery-content').textContent,/already sent may continue remotely/);
});


test('native connection loss permits checked text assessment but never development continuation',()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());f.api.setConnection('disconnected');
 assert.equal(action(f,'Start assessment conversation').disabled,false);
 f.api.setData(summary({assessment:{task_id:'assessment',status:'reviewable'},plan:{id:'plan',version:1,digest:'digest',instruction:'Reviewed work',role:'chief_of_staff',target_strategy:'new_linked'},actions:{assess:false,review_plan:true,continue:true}}));
 assert.equal(action(f,'Approve and continue development').disabled,true);
});

test('disabled recovery actions expose linked persistent explanations',()=>{
 const f=fixture();f.api.ready();f.api.setData(summary({capabilities:{assessment:false}}));
 const start=action(f,'Start assessment conversation');
 assert.match(start.getAttribute('aria-describedby'),/recovery-assessment-limit/);
 assert.match(f.document.getElementById('recovery-assessment-limit').textContent,/Connect ChatGPT/);
 f.api.setData(summary({assessment:{task_id:'assessment',status:'reviewable'},actions:{continue:false}}));
 const approve=action(f,'Approve and continue development');
 assert.match(approve.getAttribute('aria-describedby'),/recovery-continuation-limit/);
 assert.match(f.document.getElementById('recovery-continuation-limit').textContent,/Continuation is blocked/);
});


function handoffSummary(overrides={}) {return summary({handoff:{id:'handoff',version:2,status:'needs_review'},actions:{check:true,handoff_prepare:true,handoff_response:true,handoff_accept:true,continue:false},capabilities:{assessment:false,assessment_handoff:true,new_linked:false},...overrides});}
function handoffPacket(overrides={}) {return {task_id:'task',handoff_id:'handoff',version:2,packet_text:'Checked evidence only',packet_digest:'packet-digest',snapshot_digest:'snapshot-digest',stale:false,response:{response_id:'reply',response_version:1,response_digest:'reply-digest',text:'Assess carefully <script>never execute</script>',status:'needs_review',review_id:'review'},...overrides};}

test('handoff is available without sign-in and preparing it cannot start model or native work',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary({handoff:null}));f.api.setConnection('disconnected');
 assert.equal(action(f,'Prepare checked handoff packet').disabled,false);
 action(f,'Prepare checked handoff packet').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/recovery/handoffs'));assert.ok(sent);
 const body=JSON.parse(sent.options.body);assert.equal(body.expected_revision,1);assert.equal(body.confirmed,true);assert.deepEqual(body.selected_message_ids,[]);assert.match(body.text,/What can we verify/);
 assert.equal(f.requests.filter(r=>/\/(assess|continue|message)$/.test(r.url)||r.url==='/api/recovery-auth/start').length,0);
});

test('copy only uses the checked preview and never navigates or sends it to a chat',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 assert.equal(f.copied.length,0);action(f,'Copy checked packet').click();await f.settle();
 const preview=f.requests.find(r=>r.url.endsWith('/handoffs/handoff'));assert.ok(preview);assert.equal(f.copied.length,0);preview.resolve(handoffPacket());await f.settle();assert.deepEqual(f.copied,['Checked evidence only']);assert.equal(f.requests.filter(r=>r.options?.method==='POST').length,0);
 const question=field(f,'question');question.value='Changed question';question.emit('input');assert.equal(action(f,'Copy checked packet').disabled,true);
});

test('returned assessment requires scanner preview and a separate explicit acceptance',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 assert.equal(f.requests.length,0);assert.match(f.nodes.get('recovery-content').textContent,/<script>never execute<\/script>/);
 action(f,'Accept reviewed assessment').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/handoffs/handoff/accept'));assert.ok(sent);
 const body=JSON.parse(sent.options.body);assert.equal(body.expected_revision,1);assert.equal(body.expected_handoff_version,2);assert.equal(body.packet_digest,'packet-digest');assert.equal(body.response_id,'reply');assert.equal(body.response_digest,'reply-digest');assert.equal(body.response_version,1);assert.equal(body.review_id,'review');assert.equal(body.confirmed,true);
 assert.equal(f.requests.filter(r=>/\/(assess|continue|message)$/.test(r.url)).length,0);
});

test('pasted edits invalidate acceptance immediately and failed preview preserves the draft',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 const input=field(f,'handoffReply');input.value='New return that still needs checking';input.emit('input');assert.equal(action(f,'Accept reviewed assessment').disabled,true);
 action(f,'Check and preview returned assessment').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/handoffs/handoff/responses'));assert.ok(sent);assert.equal(JSON.parse(sent.options.body).text,input.value);
 sent.reject(new Error('Scanner unavailable'));await f.settle();assert.equal(f.api.draft().handoffReply,input.value);assert.match(f.nodes.get('recovery-error').textContent,/Nothing is resent automatically/);
});

test('stale and expired handoff reviews cannot be accepted',()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket({stale:true}));
 assert.equal(action(f,'Copy checked packet').disabled,true);assert.equal(action(f,'Accept reviewed assessment').disabled,true);assert.match(f.nodes.get('recovery-content').textContent,/packet is stale/);
 f.api.setHandoff(handoffPacket(),56000);assert.equal(action(f,'Accept reviewed assessment').disabled,true);
});

test('accepted handoff exposes separate continuation plan without native chat or automatic approval',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary({assessment:{task_id:'handoff',source:'handoff',status:'reviewable'},actions:{check:true,handoff_prepare:true,review_plan:true,continue:false}}));f.api.setHandoff(handoffPacket());
 assert.ok(action(f,'Create continuation plan'));assert.equal(action(f,'Approve and continue development').disabled,true);assert.equal(action(f,'Send question'),undefined);assert.equal(action(f,'Open assessment conversation'),undefined);assert.equal(f.requests.length,0);
 const pending=f.api.loadRecovery();await f.settle();f.requests.find(r=>r.url==='/api/recovery-auth').resolve({state:'signed_out',authenticated:false,plan_enabled:false});
 f.requests.find(r=>r.url.endsWith('/task/recovery')).resolve(handoffSummary({assessment:{task_id:'handoff',source:'handoff',status:'reviewable'}}));await f.settle();f.requests.find(r=>r.url.endsWith('/task/conversation')).resolve({messages:[]});await f.settle();
 assert.equal(f.requests.some(r=>r.url.includes('/handoff/conversation')),false);f.requests.find(r=>r.url.endsWith('/handoffs/handoff')).resolve(handoffPacket());await pending;
 assert.equal(action(f,'Prepare next assessment round').disabled,false);
});


test('copy rescans and scanner failure withholds even a previously visible packet',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 action(f,'Copy checked packet').click();await f.settle();f.requests.find(r=>r.url.endsWith('/handoffs/handoff')).reject(new Error('Scanner unavailable'));await f.settle();
 assert.equal(f.copied.length,0);assert.match(f.nodes.get('recovery-error').textContent,/Nothing was copied/);assert.equal(action(f,'Copy checked packet'),undefined);
});

test('clipboard denial offers focused manual selection of the freshly checked bytes',async()=>{
 const f=fixture({clipboardFails:true});f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 action(f,'Copy checked packet').click();await f.settle();f.requests.find(r=>r.url.endsWith('/handoffs/handoff')).resolve(handoffPacket());await f.settle();
 const text=f.document.getElementById('recovery-handoff-packet');assert.equal(text.value,'Checked evidence only');assert.equal(text.selected,true);assert.equal(f.document.activeElement,text);assert.equal(f.copied.length,0);assert.match(f.nodes.get('recovery-error').textContent,/Select and copy/);
});

test('next handoff round uses an explicit new question and keeps continuation separate',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary({assessment:{task_id:'handoff',source:'handoff',status:'reviewable'}}));f.api.setHandoff(handoffPacket());
 const question=field(f,'question');question.value='What evidence should I verify next?';question.emit('input');action(f,'Prepare next assessment round').click();await f.settle();
 const sent=f.requests.find(r=>r.url.endsWith('/recovery/handoffs'));assert.ok(sent);assert.equal(JSON.parse(sent.options.body).text,question.value);assert.equal(f.requests.filter(r=>/\/(continue|message|assess)$/.test(r.url)).length,0);
});


test('shared question and handoff precede optional connected assessment controls',()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary({handoff:null}));
 const main=f.nodes.get('recovery-content').querySelectorAll('.recovery-main')[0];
 const sections=main.children;
 assert.equal(sections[0].className,'recovery-packet');assert.equal(sections[1].className,'recovery-handoff');assert.equal(sections[2].className,'recovery-signin');
 assert.ok(sections[0].querySelectorAll('textarea').some(e=>e.dataset.recoveryField==='question'));
 assert.equal(sections[0].textContent.includes('Configured model:'),false);
 assert.ok(sections[2].querySelectorAll('button').some(e=>e.textContent==='Start assessment conversation'));
 assert.match(sections[2].textContent,/Configured model:/);
});

async function finishHandoffRefresh(f,data,packet=handoffPacket()) {
 await f.settle();
 f.requests.filter(r=>r.url==='/api/recovery-auth').at(-1)?.resolve({state:'signed_out',authenticated:false,plan_enabled:false});
 f.requests.filter(r=>r.url.endsWith('/task/recovery')).at(-1).resolve(data);await f.settle();
 f.requests.filter(r=>r.url.endsWith('/task/conversation')).at(-1).resolve({messages:[]});await f.settle();
 if(data.handoff){f.requests.filter(r=>r.url.endsWith(`/handoffs/${data.handoff.id}`)).at(-1).resolve(packet);await f.settle();}
}

for(const kind of ['prepare','response','accept'])test(`lost ${kind} acknowledgement reconciles the frozen request, preserves edits and permits a fresh round`,async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 if(kind==='response'){const reply=field(f,'handoffReply');reply.value='Original return';reply.emit('input');}
 const labels={prepare:'Prepare next assessment round',response:'Check and preview returned assessment',accept:'Accept reviewed assessment'};
 action(f,labels[kind]).click();await f.settle();
 const original=f.requests.find(r=>r.options?.method==='POST'),body=original.options.body,url=original.url;
 original.reject(new Error('Acknowledgement lost'));
 const newer=handoffSummary({revision:9,handoff:{id:'handoff',version:3,status:kind==='accept'?'accepted':'needs_review'}}),newPacket=handoffPacket({version:3,response:{...handoffPacket().response,review_id:'newer-review'}});
 await finishHandoffRefresh(f,newer,newPacket);
 const question=field(f,'question');question.value='Edited next question';question.emit('input');
 const reply=field(f,'handoffReply');reply.value='Edited next reply';reply.emit('input');
 assert.equal(action(f,'Prepare next assessment round').disabled,true);
 assert.equal(f.requests.filter(r=>r.options?.method==='POST').length,1);
 action(f,'Reconcile previous handoff action').click();await f.settle();
 const replay=f.requests.filter(r=>r.options?.method==='POST').at(-1);assert.equal(replay.url,url);assert.equal(replay.options.body,body);
 replay.resolve(newer);await finishHandoffRefresh(f,newer,newPacket);
 assert.equal(f.api.draft().pendingHandoff,undefined);assert.equal(field(f,'question').value,'Edited next question');assert.equal(field(f,'handoffReply').value,'Edited next reply');
 assert.equal(action(f,'Prepare next assessment round').disabled,false);
 action(f,'Prepare next assessment round').click();await f.settle();
 const next=JSON.parse(f.requests.filter(r=>r.options?.method==='POST').at(-1).options.body);assert.notEqual(next.operation_id,JSON.parse(body).operation_id);assert.equal(next.expected_revision,9);assert.equal(next.text,'Edited next question');
});

test('a definite scanner rejection releases the failed request so an edited reply gets a new operation',async()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 const reply=field(f,'handoffReply');reply.value='Rejected synthetic input';reply.emit('input');action(f,'Check and preview returned assessment').click();await f.settle();
 const first=f.requests.find(r=>r.options?.method==='POST');first.reject(Object.assign(new Error('Content check rejected the return'),{status:400}));await finishHandoffRefresh(f,handoffSummary());
 assert.equal(f.api.draft().pendingHandoff,undefined);assert.equal(action(f,'Reconcile previous handoff action'),undefined);assert.equal(field(f,'handoffReply').value,'Rejected synthetic input');
 const edited=field(f,'handoffReply');edited.value='Revised checked assessment';edited.emit('input');action(f,'Check and preview returned assessment').click();await f.settle();
 const second=f.requests.filter(r=>r.options?.method==='POST').at(-1);assert.notEqual(JSON.parse(first.options.body).operation_id,JSON.parse(second.options.body).operation_id);assert.equal(JSON.parse(second.options.body).text,'Revised checked assessment');
});


test('terminal parent status remains visible while delegated work needs recovery',()=>{
 const f=fixture();f.api.ready();f.api.setData(summary());f.api.setTask({status:'completed'});
 assert.equal(f.nodes.get('recovery-content').querySelectorAll('.badge')[0].textContent,'Completed');
 assert.match(f.nodes.get('recovery-content').textContent,/Delegated work or recovery evidence remains unresolved/);
 assert.equal(f.nodes.get('recovery-content').textContent.includes('original task’s outcome remains unknown'),false);
});

test('unchanged poll preserves focused handoff button without retaining old action authority',async()=>{
 const f=fixture();f.api.ready();const data=handoffSummary();f.api.setData(data);f.api.setHandoff(handoffPacket());
 action(f,'Accept reviewed assessment').focus();const previous=f.document.activeElement;
 const pending=f.api.loadRecovery();await finishHandoffRefresh(f,data);await pending;
 const current=action(f,'Accept reviewed assessment');assert.notEqual(current,previous);assert.equal(f.document.activeElement,current);assert.equal(current.disabled,false);
 f.api.setData(handoffSummary({actions:{check:true,handoff_accept:false}}));
 assert.equal(action(f,'Accept reviewed assessment').disabled,true);assert.equal(f.document.activeElement,f.nodes.get('recovery-title'));
});

test('all recovery buttons and checked message boxes retain keyboard position on rerender',()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 for(const control of f.nodes.get('recovery-content').querySelectorAll('button').filter(e=>!e.disabled)){
  const key=control.dataset.recoveryFocus;f.nodes.get('recovery-content').querySelectorAll('button').find(e=>e.dataset.recoveryFocus===key).focus();f.api.renderRecovery();
  assert.equal(f.document.activeElement.dataset.recoveryFocus,key);assert.ok(f.nodes.get('recovery-content').contains(f.document.activeElement));
 }
 f.api.setEvidence([{id:'message-one',kind:'user',text:'Checked message'}]);
 const check=f.nodes.get('recovery-content').querySelectorAll('input')[0];check.checked=true;check.emit('change');check.focus();f.api.renderRecovery();
 assert.equal(f.document.activeElement.dataset.recoveryFocus,'message:message-one');assert.equal(f.document.activeElement.checked,true);
});

test('handoff draft retains selection range and direction through polling render',()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());
 const input=field(f,'handoffReply');input.value='Edited assessment for review';input.emit('input');input.focus();input.setSelectionRange(3,12,'backward');
 f.api.renderRecovery();const current=field(f,'handoffReply');assert.equal(f.document.activeElement,current);assert.equal(current.value,input.value);assert.equal(current.selectionStart,3);assert.equal(current.selectionEnd,12);assert.equal(current.selectionDirection,'backward');assert.equal(action(f,'Accept reviewed assessment').disabled,true);
});


test('removed action returns focus to recovery heading and changed continuation gate stays disabled',()=>{
 const f=fixture();f.api.ready();f.api.setData(handoffSummary());f.api.setHandoff(handoffPacket());action(f,'Copy checked packet').focus();f.api.setHandoff(null);
 assert.equal(f.document.activeElement,f.nodes.get('recovery-title'));
 const data=summary({assessment:{task_id:'handoff',source:'handoff',status:'reviewable'},plan:{id:'plan',version:1,digest:'digest',instruction:'Reviewed work',role:'chief_of_staff',target_strategy:'new_linked'},actions:{check:true,continue:true}});
 f.api.setData(data);action(f,'Approve and continue development').focus();f.api.setData({...data,actions:{check:true,continue:false}});
 assert.equal(action(f,'Approve and continue development').disabled,true);assert.equal(f.document.activeElement,f.nodes.get('recovery-title'));assert.equal(f.requests.length,0);
});
