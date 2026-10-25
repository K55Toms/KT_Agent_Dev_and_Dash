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
    if ((url==='/api/config'&&options.body) || url.includes('/review') || url.includes('/sensitive-review') || url.includes('/respond') || url.includes('/alternative') || url.endsWith('/message')) return new Promise((resolve, reject) => requests.push({url, options, resolve: data => resolve(response(data)), fail: data=>resolve({ok:false,json:async()=>data}), reject}));
    // Avoid unrelated settings/state rendering and all external IO.
    return new Promise(() => {});
  }
  const runtime={document, fetch, setInterval() {}, console};
  vm.runInNewContext(script.replace('loadSettings();refresh();', 'globalThis.approvalTest={saveSettings,revealSensitiveRequest,continueApprovalGuidance,openApprovalContinuation,approvalDecisionDescription,requestApprovalAlternative,conversationAgentName,conversationMessageHeading,conversationAgentIdentifiers,selectedProjectApprovalModes,confirmProjectApprovalModes,validSettings,setSettings(value){settings=value;settingsBusy=false;renderProjectApprovalSettings(true);},openApprovalReview,retryApprovalReview,respondReviewedApproval,setWorkspace(value,fresh=true){state=value;stale=!fresh;checkApprovalReview();}};loadSettings();refresh();'), runtime);
  const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  return {document, nodes, requests, settle, api:runtime.approvalTest};
}


const approval={id:'synthetic-request',task_id:'synthetic-task',kind:'command',status:'pending',resolution_mode:'decline',available_decisions:['decline'],summary:'Synthetic command request'};
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
    assert.match(f.nodes.get('approval-review-status').textContent,/could not be loaded/);
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


test('fixed review diagnostics expose a GET-only retry without granting or replaying',async()=>{
  const f=ready();let pending=f.api.openApprovalReview(approval);
  f.requests[0].fail({error:'The review scanner is unavailable.',code:'scanner_unavailable',action:'Restore the scanner and try review again.',retryable:true});await pending;
  assert.equal(f.nodes.get('approve-request').disabled,true);
  assert.match(f.nodes.get('approval-review-diagnostic').textContent,/scanner_unavailable.*Restore the scanner/);
  assert.equal(f.nodes.get('retry-approval-review').hidden,false);
  assert.equal(f.nodes.get('retry-approval-review').disabled,false);
  assert.equal(f.requests.length,1,'no automatic retry');
  pending=f.api.retryApprovalReview();
  assert.equal(f.requests[1].url,f.requests[0].url);assert.equal(f.requests[1].options.method,'GET');
  assert.equal(f.nodes.get('approval-review-error').textContent,'');
  assert.equal(f.nodes.get('approval-review-diagnostic').textContent,'');
  f.requests[1].resolve(result());await pending;
  assert.equal(f.nodes.get('approve-request').disabled,false);
  assert.equal(f.nodes.get('retry-approval-review').hidden,true);assert.equal(f.requests.length,2);
});

test('unsupported and no-longer-live requests cannot use retry as a grant shortcut',async()=>{
  for(const retryable of [false,true]){
    const f=ready();const pending=f.api.openApprovalReview(approval);
    f.requests[0].fail({error:'Synthetic review cannot be displayed.',code:retryable?'context_missing':'unsupported_shape',action:'Synthetic fixed guidance.',retryable});await pending;
    assert.equal(f.nodes.get('retry-approval-review').hidden,!retryable);
    f.api.setWorkspace(workspace(),false);
    assert.equal(f.nodes.get('retry-approval-review').disabled,true);
    await f.api.retryApprovalReview();assert.equal(f.requests.length,1);
    assert.equal(f.nodes.get('approve-request').disabled,true);
  }
});

test('native callback distinguishes requested subcommand from parent context without changing either',async()=>{
  const f=ready();const pending=f.api.openApprovalReview(approval);
  const context={approvalId:'synthetic-callback',command:'printf "<script>requested</script>"',cwd:'/synthetic/project',parentItemContext:{command:'synthetic-parent.sh && printf parent',cwd:'/synthetic/project'}};
  f.requests[0].resolve(result(context));await pending;
  const panel=f.nodes.get('approval-command-context');
  assert.equal(panel.hidden,false);
  assert.match(panel.textContent,/Requested subcommand/);
  assert.match(panel.textContent,/Parent command \(context only\)/);
  const commands=panel.querySelectorAll('pre');
  assert.equal(commands[0].textContent,context.command);assert.equal(commands[0].children.length,0);
  assert.equal(commands[1].textContent,context.parentItemContext.command);
  assert.equal(f.nodes.get('approval-review-context').textContent,JSON.stringify(context,null,2));
  f.api.setWorkspace(workspace(),false);assert.equal(panel.textContent,'');assert.equal(panel.hidden,true);
});


test('project automatic approval is opt-in with broad confirmation and can be revoked',()=>{
  const f=ready(),id='a'.repeat(32);f.api.setWorkspace(workspace({projects:[{id,name:'Synthetic approval project'}]}));
  const config={sensitive_review_enabled:true,theme:'hybrid',dashboard_name:'Synthetic dashboard',github_username:'synthetic',github_visibility:'private',logo_path:'/brand-logo.png',project_approval_modes:{}};
  assert.equal(f.api.validSettings(config),true);assert.equal(f.api.validSettings({...config,project_approval_modes:{[id]:'unsafe'}}),false);
  f.api.setSettings(config);const select=f.nodes.get('project-approval-settings').querySelectorAll('select')[0];
  assert.equal(select.value,'manual');select.value='automatic';const modes=f.api.selectedProjectApprovalModes();
  assert.equal(modes[id],'automatic');assert.throws(()=>f.api.confirmProjectApprovalModes(modes),/Confirm the broad effect/);
  f.nodes.get('confirm-project-automatic').checked=true;assert.doesNotThrow(()=>f.api.confirmProjectApprovalModes(modes));
  f.api.setSettings({...config,project_approval_modes:{[id]:'automatic'}});
  const revoke=f.nodes.get('project-approval-settings').querySelectorAll('select')[0];assert.equal(revoke.value,'automatic');
  assert.throws(()=>f.api.confirmProjectApprovalModes(f.api.selectedProjectApprovalModes()),/Confirm the broad effect/,'a stale loaded automatic mode still requires fresh confirmation');revoke.value='manual';
  const manual=f.api.selectedProjectApprovalModes();assert.equal(manual[id],'manual');assert.doesNotThrow(()=>f.api.confirmProjectApprovalModes(manual));
  assert.match(html,/does not limit the operating-system effects/);assert.match(html,/Select Manual and save to revoke/);
  assert.equal(f.requests.length,0,'editing settings alone grants nothing');
});


test('conversation uses verified human names with identifiers in secondary details',()=>{
  const f=ready(),sender=randomUUID(),receiver=randomUUID();
  const agents={[sender]:{role_id:'chief_of_staff',name:'Mara Vale'},[receiver]:{role_id:'backend_developer',name:'Kira Voss'}};
  const message={kind:'interagent',sender,receivers:[receiver]};
  assert.equal(f.api.conversationMessageHeading(message,agents),'Mara Vale → Kira Voss');
  const secondary=f.api.conversationAgentIdentifiers(message);assert.equal(secondary.tagName,'DETAILS');
  assert.match(secondary.textContent,new RegExp(sender));assert.match(secondary.textContent,new RegExp(receiver));
  assert.equal(f.api.conversationMessageHeading(message,{}),'Unknown agent → Unknown agent');
  assert.equal(f.api.conversationMessageHeading(message,{[sender]:{name:'Unverified nickname'}}),'Unknown agent → Unknown agent');
  assert.equal(f.api.conversationMessageHeading({kind:'user',sender,receivers:[]},agents),'You');
  assert.equal(f.api.conversationMessageHeading({kind:'system',sender,receivers:[]},agents),'System');
});


test('approval chat delivers explicit guidance with a decline, never an accept or automatic retry',async()=>{
  for(const text of ['', 'Please split the blocked command into separate reviewable actions.']){
    const f=ready();const requestApproval={...approval,can_request_alternative:true};f.api.setWorkspace(workspace({approvals:[requestApproval]}));
    const loading=f.api.openApprovalReview(requestApproval);f.requests[0].fail({error:'Synthetic context missing.',code:'command_missing',action:'Ask for a reviewable alternative.',retryable:true,can_request_alternative:true});await loading;
    assert.equal(f.nodes.get('approval-guidance-section').hidden,false);assert.equal(f.nodes.get('request-approval-alternative').disabled,false);
    f.nodes.get('approval-guidance').value=text;void f.api.requestApprovalAlternative();
    assert.match(f.requests[1].url,/\/alternative$/);assert.equal(f.requests[1].options.method,'POST');
    assert.deepEqual(JSON.parse(f.requests[1].options.body),{text});
    assert.equal(f.nodes.get('approve-request').disabled,true);assert.equal(f.nodes.get('decline-reviewed-request').disabled,true);
    assert.equal(f.nodes.get('request-approval-alternative').disabled,true);
    await f.api.requestApprovalAlternative();assert.equal(f.requests.length,2,'double-submit blocked');
    f.requests[1].resolve({guidance_sent:true,request_declined:true});await f.settle();
    assert.match(f.nodes.get('approval-review-status').textContent,/Guidance queued with Codex.*request was declined.*no approval was granted/);
    assert.equal(f.nodes.get('approval-guidance').value,'');assert.equal(f.requests.length,2);
  }
});

test('chat eligibility from checked review diagnostic is honored but stale requests cannot send',async()=>{
  const f=ready();const loading=f.api.openApprovalReview(approval);f.requests[0].fail({error:'Synthetic unsupported context.',code:'unsupported_shape',action:'Send guidance.',retryable:false,can_request_alternative:true});await loading;
  assert.equal(f.nodes.get('request-approval-alternative').hidden,false);assert.equal(f.nodes.get('request-approval-alternative').disabled,false);
  f.api.setWorkspace(workspace(),false);assert.equal(f.nodes.get('request-approval-alternative').disabled,true);
  await f.api.requestApprovalAlternative();assert.equal(f.requests.length,1);
});

test('uncertain guidance delivery is visible and cannot resend itself or enable approval',async()=>{
  const f=ready();const eligible={...approval,can_request_alternative:true};f.api.setWorkspace(workspace({approvals:[eligible]}));
  const loading=f.api.openApprovalReview(eligible);f.requests[0].resolve(result());await loading;
  f.nodes.get('approval-guidance').value='Synthetic guidance to revise the request.';void f.api.requestApprovalAlternative();
  f.requests[1].reject(new Error('Synthetic delivery uncertain.'));await f.settle();
  assert.match(f.nodes.get('approval-review-error').textContent,/No automatic retry/);assert.equal(f.nodes.get('approve-request').disabled,true);
  assert.equal(f.nodes.get('request-approval-alternative').disabled,true);await f.api.requestApprovalAlternative();assert.equal(f.requests.length,2);
  assert.equal(f.nodes.get('approval-guidance').value,'Synthetic guidance to revise the request.');
});


test('guidance queued after original resolution reports partial success without resending or claiming a decline',async()=>{
  const f=ready();const eligible={...approval,can_request_alternative:true};f.api.setWorkspace(workspace({approvals:[eligible]}));
  const loading=f.api.openApprovalReview(eligible);f.requests[0].resolve(result());await loading;
  f.nodes.get('approval-guidance').value='Synthetic guidance.';void f.api.requestApprovalAlternative();
  f.requests[1].resolve({guidance_sent:true,request_declined:false});await f.settle();
  assert.match(f.nodes.get('approval-review-status').textContent,/Guidance was queued.*already resolved.*no decline was sent/);
  assert.match(f.nodes.get('approval-review-status').textContent,/will not resend guidance automatically/);
  assert.equal(f.nodes.get('approval-guidance').value,'');assert.equal(f.nodes.get('approve-request').disabled,true);
  await f.api.requestApprovalAlternative();assert.equal(f.requests.length,2);
});

test('oversized approval guidance is rejected locally using the backend limit',async()=>{
  const f=ready();const eligible={...approval,can_request_alternative:true};f.api.setWorkspace(workspace({approvals:[eligible]}));
  const loading=f.api.openApprovalReview(eligible);f.requests[0].resolve(result());await loading;
  f.nodes.get('approval-guidance').value='x'.repeat(12001);await f.api.requestApprovalAlternative();
  assert.match(f.nodes.get('approval-review-error').textContent,/12,000/);assert.equal(f.requests.length,1);
  assert.match(html,/id="approval-guidance"[^>]*maxlength="12000"/);
});


test('approval audit distinguishes automatic policy decisions from human and guidance decisions',()=>{
  const f=ready(),at='2026-10-18T12:00:00Z';
  assert.match(f.api.approvalDecisionDescription({value:'accept',source:'project_policy',at}),/Approved automatically by this project’s policy/);
  assert.match(f.api.approvalDecisionDescription({value:'accept',source:'human',at}),/Approved once by you/);
  assert.match(f.api.approvalDecisionDescription({value:'accept',source:'human_sensitive_review',at}),/Approved once by you after sensitive request review/);
  assert.match(f.api.approvalDecisionDescription({value:'decline',source:'human',at}),/Declined by you/);
  assert.match(f.api.approvalDecisionDescription({value:'decline',source:'human_guidance',at}),/Declined after guidance was queued with Codex/);
  assert.match(f.api.approvalDecisionDescription({value:'cancel',source:'human_guidance',at}),/Cancellation requested after guidance was queued/);
  assert.equal(f.api.approvalDecisionDescription({value:'accept',source:'human_guidance',at}),null);
  assert.equal(f.api.approvalDecisionDescription({value:'accept',source:'unknown',at}),null);
});


async function cancelFixture({rootTask=true}={}) {
  const f=ready();const eligible={...approval,can_request_alternative:true,resolution_mode:'cancel',available_decisions:[]};
  const task={...workspace().tasks[0],thread_id:'synthetic-root-thread',turn_id:'synthetic-original-turn'};
  f.api.setWorkspace(workspace({tasks:[task],approvals:[eligible]}));
  const loading=f.api.openApprovalReview(eligible);f.requests[0].resolve(result());await loading;
  assert.equal(f.nodes.get('decline-reviewed-request').hidden,true,'a nonexistent decline choice is not offered');
  assert.match(f.nodes.get('request-approval-alternative').textContent,/cancel this attempt/);
  assert.match(f.nodes.get('approval-alternative-notice').textContent,/cancellation.*turn.*may be discarded/);
  f.nodes.get('approval-guidance').value='Please use a bounded alternative.';void f.api.requestApprovalAlternative();
  assert.deepEqual(JSON.parse(f.requests[1].options.body),{text:'Please use a bounded alternative.',mode:'cancel'});
  f.requests[1].resolve({guidance_sent:true,request_declined:false,cancel_sent:true,origin_thread_id:rootTask?task.thread_id:'synthetic-child-thread',origin_turn_id:task.turn_id,root_task:rootTask});await f.settle();
  return {f,eligible,task};
}

test('cancel is explicit and only an observed interruption permits a second-click guidance turn',async()=>{
  const {f,eligible,task}=await cancelFixture();
  assert.match(f.nodes.get('approval-review-status').textContent,/cancellation was requested/);
  assert.equal(f.nodes.get('continue-approval-guidance').disabled,true);
  assert.equal(f.nodes.get('continuation-guidance').textContent,'Please use a bounded alternative.');
  await f.api.continueApprovalGuidance();assert.equal(f.requests.length,2,'no premature or automatic turn');
  f.api.setWorkspace(workspace({tasks:[{...task,status:'interrupted'}],approvals:[{...eligible,status:'resolved'}]}));
  assert.equal(f.nodes.get('continue-approval-guidance').disabled,false);void f.api.continueApprovalGuidance();
  assert.match(f.requests[2].url,/\/tasks\/synthetic-task\/message$/);
  assert.deepEqual(JSON.parse(f.requests[2].options.body),{text:'Please use a bounded alternative.',expected_turn_id:task.turn_id});
  await f.api.continueApprovalGuidance();assert.equal(f.requests.length,3,'second click cannot duplicate turn');
  f.requests[2].resolve({});await f.settle();
  assert.match(f.nodes.get('approval-review-status').textContent,/A new turn was requested/);
  assert.doesNotMatch(f.nodes.get('approval-review-status').textContent,/No replacement turn has started/);
  f.api.setWorkspace(workspace({tasks:[{...task,status:'running',turn_id:'synthetic-new-turn'}],approvals:[{...eligible,status:'resolved'}]}));
  assert.match(f.nodes.get('approval-review-status').textContent,/A new turn was requested/);
  assert.doesNotMatch(f.nodes.get('continuation-status').textContent,/no longer matches/);
});

test('cancel continuation requires original root thread and turn, fresh connection and no active children',async()=>{
  for(const changes of [{turn_id:'synthetic-new-turn'},{thread_id:'different-thread'},{active_children:1}]){
    const {f,eligible,task}=await cancelFixture();
    f.api.setWorkspace(workspace({tasks:[{...task,status:'interrupted',...changes}],approvals:[{...eligible,status:'resolved'}]}));
    assert.equal(f.nodes.get('continue-approval-guidance').disabled,true);await f.api.continueApprovalGuidance();assert.equal(f.requests.length,2);
  }
  const {f,eligible,task}=await cancelFixture();f.api.setWorkspace(workspace({tasks:[{...task,status:'interrupted'}],approvals:[{...eligible,status:'resolved'}]}),false);
  assert.equal(f.nodes.get('continue-approval-guidance').disabled,true);await f.api.continueApprovalGuidance();assert.equal(f.requests.length,2);
});

test('a cancelled child cannot be silently resumed as the coordinating root agent',async()=>{
  const {f,eligible,task}=await cancelFixture({rootTask:false});
  f.api.setWorkspace(workspace({tasks:[{...task,status:'interrupted'}],approvals:[{...eligible,status:'resolved'}]}));
  assert.equal(f.nodes.get('continue-approval-guidance').hidden,true);
  assert.match(f.nodes.get('continuation-status').textContent,/belongs to a child agent.*cannot resume that child/);
  await f.api.continueApprovalGuidance();assert.equal(f.requests.length,2);
});

test('retained cancellation guidance can be reopened without resending and uncertain continuation stays explicit',async()=>{
  const {f,eligible,task}=await cancelFixture();
  f.nodes.get('approval-review-dialog').close();f.api.openApprovalContinuation(approval.id);
  assert.equal(f.nodes.get('continuation-guidance').textContent,'Please use a bounded alternative.');
  assert.match(f.nodes.get('approval-review-task').textContent,/Synthetic task/);
  assert.match(f.nodes.get('continuation-origin').textContent,/synthetic-original-turn/);
  assert.equal(f.requests.length,2);
  f.api.setWorkspace(workspace({tasks:[{...task,status:'interrupted'}],approvals:[{...eligible,status:'resolved'}]}));
  void f.api.continueApprovalGuidance();f.requests[2].reject(new Error('Synthetic unconfirmed new turn.'));await f.settle();
  assert.match(f.nodes.get('approval-review-status').textContent,/could not be confirmed/);
  assert.doesNotMatch(f.nodes.get('approval-review-status').textContent,/No replacement turn has started/);
  assert.equal(f.nodes.get('continue-approval-guidance').disabled,true);await f.api.continueApprovalGuidance();assert.equal(f.requests.length,3);
});


test('sensitive reveal requires eligible findings and explicit local confirmation, then separate one-time risk confirmation',async()=>{
  const f=ready();const loading=f.api.openApprovalReview(approval);
  f.requests[0].fail({error:'Synthetic finding withheld.',code:'scanner_blocked',can_sensitive_review:true});await loading;
  assert.equal(f.nodes.get('sensitive-reveal-section').hidden,false);
  await f.api.revealSensitiveRequest();assert.equal(f.requests.length,1);
  f.nodes.get('confirm-sensitive-reveal').checked=true;f.nodes.get('confirm-sensitive-reveal').emit('change');
  assert.equal(f.nodes.get('reveal-sensitive-request').disabled,false);
  const revealing=f.api.revealSensitiveRequest();assert.match(f.requests[1].url,/\/sensitive-review$/);
  assert.deepEqual(JSON.parse(f.requests[1].options.body),{confirmed:true});
  const revealed={...result({command:'printf "<synthetic-sensitive-content>"',cwd:'/synthetic/project'}),sensitive_review:true};
  f.requests[1].resolve(revealed);await revealing;
  assert.equal(f.nodes.get('sensitive-review-badge').hidden,false);
  assert.equal(f.nodes.get('approval-review-context').textContent,JSON.stringify(revealed.context,null,2));
  assert.equal(f.nodes.get('approve-request').disabled,true);
  await f.api.respondReviewedApproval('accept');assert.equal(f.requests.length,2);
  f.nodes.get('confirm-sensitive-approve').checked=true;f.nodes.get('confirm-sensitive-approve').emit('change');
  assert.equal(f.nodes.get('approve-request').disabled,false);
  void f.api.respondReviewedApproval('accept');
  assert.deepEqual(JSON.parse(f.requests[2].options.body),{decision:'accept',review_id:revealed.review_id,sensitive_confirmed:true});
  f.requests[2].resolve({});await f.settle();
  assert.equal(f.nodes.get('approval-review-context').textContent,'');
  assert.equal(f.nodes.get('confirm-sensitive-approve').checked,false);
});

test('scanner failures and unsupported contexts cannot enable sensitive reveal, even with an inconsistent flag',async()=>{
  for(const code of ['scanner_unavailable','scanner_failed','command_missing','unsupported_shape']){
    const f=ready();const pending=f.api.openApprovalReview(approval);
    f.requests[0].fail({error:'Synthetic failure.',code,can_sensitive_review:true});await pending;
    f.nodes.get('confirm-sensitive-reveal').checked=true;await f.api.revealSensitiveRequest();
    assert.equal(f.nodes.get('sensitive-reveal-section').hidden,true);assert.equal(f.requests.length,1);
  }
});

test('sensitive response identity swaps and late responses never reveal content or enable approval',async()=>{
  for(const variant of ['swap','close','stale','disconnect']){
    const f=ready();const pending=f.api.openApprovalReview(approval);
    f.requests[0].fail({error:'Synthetic finding.',code:'scanner_blocked',can_sensitive_review:true});await pending;
    f.nodes.get('confirm-sensitive-reveal').checked=true;const revealing=f.api.revealSensitiveRequest();
    if(variant==='close')f.nodes.get('approval-review-dialog').close();
    if(variant==='stale')f.api.setWorkspace(workspace(),false);
    if(variant==='disconnect')f.api.setWorkspace(workspace({connection:{status:'disconnected'}}));
    f.requests[1].resolve({...result(),sensitive_review:true,...(variant==='swap'?{id:'different'}:{})});await revealing;
    assert.equal(f.nodes.get('approval-review-context').textContent,'');assert.equal(f.nodes.get('approve-request').disabled,true);
    assert.equal(f.nodes.get('confirm-sensitive-reveal').checked,false);
  }
});

test('normal GET reviews cannot supply privileged receipts and settings require the seventh boolean field',async()=>{
  const f=ready();const loading=f.api.openApprovalReview(approval);f.requests[0].resolve({...result(),sensitive_review:true});await loading;
  assert.equal(f.nodes.get('approve-request').disabled,true);assert.equal(f.nodes.get('approval-review-context').textContent,'');
  const config={theme:'hybrid',dashboard_name:'Synthetic',github_username:'synthetic',github_visibility:'private',logo_path:'/brand-logo.png',project_approval_modes:{},sensitive_review_enabled:false};
  assert.equal(f.api.validSettings(config),true);assert.equal(f.api.validSettings({...config,sensitive_review_enabled:'true'}),false);
  const {sensitive_review_enabled,...old}=config;assert.equal(f.api.validSettings(old),false);
});


test('saving settings sends all seven fields and preserves existing project approval modes',async()=>{
  const f=ready(),id='a'.repeat(32),config={theme:'hybrid',dashboard_name:'Synthetic',github_username:'synthetic',github_visibility:'private',logo_path:'/brand-logo.png',project_approval_modes:{[id]:'automatic'},sensitive_review_enabled:true};
  f.api.setSettings(config);const form=f.nodes.get('settings-form');form.reportValidity=()=>true;
  for(const field of ['theme','dashboard_name','github_username','github_visibility'])form.elements[field].value=config[field];
  form.elements.logo_choice.value='default';f.nodes.get('confirm-project-automatic').checked=true;
  f.nodes.get('sensitive-review-enabled').checked=false;
  const saving=f.api.saveSettings({preventDefault(){}});
  assert.equal(f.requests.length,1);assert.deepEqual(JSON.parse(f.requests[0].options.body),{...config,sensitive_review_enabled:false,project_approval_modes:{...config.project_approval_modes,'synthetic-project':'manual'}});
  f.requests[0].reject(new Error('Synthetic save failure.'));await saving;
  assert.match(f.nodes.get('settings-status').textContent,/not confirmed/);
});

test('a revealed sensitive review clears all content and confirmation after loss of live ownership',async()=>{
  const f=ready();const opening=f.api.openApprovalReview(approval);f.requests[0].fail({error:'Synthetic finding.',code:'scanner_blocked',can_sensitive_review:true});await opening;
  f.nodes.get('confirm-sensitive-reveal').checked=true;const revealing=f.api.revealSensitiveRequest();f.requests[1].resolve({...result(),sensitive_review:true});await revealing;
  f.nodes.get('confirm-sensitive-approve').checked=true;f.api.setWorkspace(workspace(),false);
  assert.equal(f.nodes.get('approval-review-context').textContent,'');assert.equal(f.nodes.get('approval-command-context').textContent,'');
  assert.equal(f.nodes.get('confirm-sensitive-approve').checked,false);assert.equal(f.nodes.get('sensitive-review-badge').hidden,true);
  await f.api.respondReviewedApproval('accept');assert.equal(f.requests.length,2);
});
