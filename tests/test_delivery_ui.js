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

test('complete approved checks and independent review journey stays separate from native completion',async()=>{
  const f=fixture();await opened(f,data({plan_version:0,actions:{run_checks:false,start_review:false,review_decision:false}}),plan(0,[]));
  assert.match(f.nodes.get('task-detail').textContent,/Completed/);
  assert.match(f.nodes.get('task-detail').textContent,/Awaiting checks/);
  let commands=field(f,'commands');commands.value='python3 -m unittest\nnode --test tests/example.js';commands.emit('input');
  let approval=field(f,'approve-plan');approval.checked=true;approval.emit('change');
  assert.equal(control(f,'Save approved checks').disabled,false);control(f,'Save approved checks').click();await f.settle();
  const save=mutation(f,'/check-plan');assert.deepEqual(JSON.parse(save.options.body),{expected_version:0,commands:['python3 -m unittest','node --test tests/example.js'],confirmed:true});save.answered=true;save.resolve(plan(1));await f.settle();await resolveRefresh(f,data(),plan());
  assert.equal(control(f,'Run approved checks').disabled,true);confirmRun(f);assert.equal(control(f,'Run approved checks').disabled,false);control(f,'Run approved checks').click();await f.settle();
  const checks=mutation(f,'/delivery/checks'),checkBody=JSON.parse(checks.options.body);assert.equal(checkBody.expected_snapshot,'a'.repeat(64));assert.equal(checkBody.expected_plan_version,1);assert.match(checkBody.operation_id,/^[a-f0-9]{32}$/);assert.equal(checkBody.confirmed,true);checks.answered=true;checks.resolve(data());await f.settle();
  const passed=data({status:'awaiting_review',check_operation:{id:checkBody.operation_id,task_id:'qa-task',status:'completed',passed_checks:1,required_checks:1},actions:{run_checks:true,start_review:true,review_decision:false}});await resolveRefresh(f,passed);
  assert.ok(control(f,'Open checks conversation'));confirmRun(f);control(f,'Start independent review').click();await f.settle();
  const review=mutation(f,'/delivery/reviews'),reviewBody=JSON.parse(review.options.body);assert.equal(reviewBody.check_operation_id,checkBody.operation_id);review.answered=true;review.resolve(data());await f.settle();
  const reviewed={...passed,status:'awaiting_review',review_operation:{id:reviewBody.operation_id,task_id:'review-task',status:'completed'},actions:{run_checks:true,start_review:false,review_decision:true}};await resolveRefresh(f,reviewed);
  control(f,'Read independent review').click();await f.settle();const preview=f.requests.find(r=>!r.answered&&r.url.endsWith('/reviews/'+reviewBody.operation_id));assert.ok(preview);preview.answered=true;preview.resolve({review_id:reviewBody.operation_id,snapshot_digest:'a'.repeat(64),review_digest:'review-digest',receipt_id:'receipt',current:true,messages:[{id:'message',text:'<script>literal review</script>\nNo findings in these changes.'}]});await f.settle();
  assert.match(f.nodes.get('task-detail').textContent,/<script>literal review<\/script>/);assert.equal(control(f,'Accept review and mark delivery ready').disabled,false);control(f,'Accept review and mark delivery ready').click();await f.settle();
  const decision=mutation(f,'/review-decision');assert.deepEqual(JSON.parse(decision.options.body),{review_id:reviewBody.operation_id,receipt_id:'receipt',review_digest:'review-digest',expected_snapshot:'a'.repeat(64),decision:'accept',confirmed:true});decision.answered=true;decision.resolve(data());await f.settle();await resolveRefresh(f,{...reviewed,status:'ready',actions:{run_checks:true,start_review:false,review_decision:false}});
  assert.match(f.nodes.get('task-detail').textContent,/Ready for delivery/);assert.equal(f.nodes.get('task-dialog').open,true);
});

test('changed snapshot removes reviewed authority and retains edited checks through refresh',async()=>{
  const f=fixture();const reviewed=data({status:'awaiting_review',review_operation:{id:'review',task_id:'review-task',status:'completed'},actions:{run_checks:false,start_review:false,review_decision:true}});await opened(f,reviewed);
  control(f,'Read independent review').click();await f.settle();const preview=f.requests.find(r=>r.url.endsWith('/reviews/review'));preview.answered=true;preview.resolve({review_id:'review',snapshot_digest:'a'.repeat(64),review_digest:'digest',receipt_id:'receipt',current:true,messages:[{text:'Checked review'}]});await f.settle();assert.equal(control(f,'Accept review and mark delivery ready').disabled,false);
  const commands=field(f,'commands');commands.value='python3 -m unittest tests.changed';commands.selectionStart=9;commands.selectionEnd=12;commands.selectionDirection='backward';commands.focus();commands.emit('input');
  assert.equal(f.document.activeElement.dataset.deliveryFocus,'commands');assert.equal(field(f,'commands').value,'python3 -m unittest tests.changed');assert.ok(!f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Accept review and mark delivery ready'));
  f.api.loadDelivery();await f.settle();await resolveRefresh(f,data({status:'stale',snapshot_digest:'b'.repeat(64),actions:{run_checks:true,start_review:false,review_decision:false}}));
  assert.equal(field(f,'commands').value,'python3 -m unittest tests.changed');assert.equal(control(f,'Run approved checks').disabled,true);assert.match(f.nodes.get('task-detail').textContent,/Evidence needs refreshing/);
});

test('lost checks acknowledgement reconciles original operation without a repeated POST',async()=>{
  const f=fixture();await opened(f);confirmRun(f);control(f,'Run approved checks').click();await f.settle();const post=mutation(f,'/delivery/checks'),body=JSON.parse(post.options.body);post.answered=true;post.reject(new Error('Acknowledgement lost'));await f.settle();
  await resolveRefresh(f,data());assert.equal(control(f,'Run approved checks').disabled,true);assert.match(f.nodes.get('task-detail').textContent,/awaiting reconciliation|still uncertain/);
  f.api.loadDelivery();await f.settle();await resolveRefresh(f,data({status:'checks_running',check_operation:{id:body.operation_id,task_id:'qa',status:'running',passed_checks:0,required_checks:1},actions:{run_checks:false,start_review:false,review_decision:false}}));
  assert.ok(control(f,'Open checks conversation'));assert.equal(f.requests.filter(r=>r.options.method==='POST'&&r.url.endsWith('/delivery/checks')).length,1);assert.doesNotMatch(f.nodes.get('task-detail').textContent,/awaiting reconciliation/);
});

test('review failure and stale dashboard never enable acceptance or dispatch',async()=>{
  const f=fixture();await opened(f,data({review_operation:{id:'review',status:'completed'},actions:{run_checks:true,start_review:false,review_decision:true}}));control(f,'Read independent review').click();await f.settle();const preview=f.requests.find(r=>r.url.endsWith('/reviews/review'));preview.answered=true;preview.fail(409,'Review is stale');await f.settle();assert.ok(!f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Accept review and mark delivery ready'));
  f.api.setStale(true);f.api.renderDelivery();assert.equal(control(f,'Run approved checks').disabled,true);assert.equal(control(f,'Read independent review').disabled,true);
});

 test('late delivery response cannot replace a different task dialog',async()=>{
  const f=fixture();const state=workspace();state.tasks.push({id:'other',project_id:'project',title:'Other task',role:'backend_developer',status:'completed'});f.api.setWorkspace(state);f.api.openTask('subject');await f.settle();const old=f.requests.filter(r=>!r.answered);f.api.openTask('other');await f.settle();old.forEach(r=>{r.answered=true;r.resolve(r.url.endsWith('/delivery')?data():plan());});await f.settle();assert.equal(f.nodes.get('task-dialog-title').textContent,'Other task');assert.doesNotMatch(f.nodes.get('task-detail').textContent,/Awaiting checks/);
});

test('lost plan-save acknowledgement preserves draft and reconciles only matching saved commands',async()=>{
  const f=fixture();await opened(f);let commands=field(f,'commands');commands.value='python3 -m unittest tests.focused';commands.emit('input');let approve=field(f,'approve-plan');approve.checked=true;approve.emit('change');control(f,'Save approved checks').click();await f.settle();
  const post=mutation(f,'/check-plan');post.answered=true;post.reject(new Error('Save acknowledgement lost'));await f.settle();await resolveRefresh(f,data(),plan());
  assert.equal(control(f,'Save approved checks').disabled,true);assert.equal(field(f,'commands').value,'python3 -m unittest tests.focused');
  f.api.loadDelivery();await f.settle();await resolveRefresh(f,data({plan_version:2}),plan(2,['python3 -m unittest tests.focused']));
  assert.equal(field(f,'commands').value,'python3 -m unittest tests.focused');assert.doesNotMatch(f.nodes.get('task-detail').textContent,/awaiting reconciliation/);assert.equal(f.requests.filter(r=>r.options.method==='POST'&&r.url.endsWith('/check-plan')).length,1);
});

test('lost review decision acknowledgement reconciles ready without granting twice',async()=>{
  const f=fixture(),reviewed=data({status:'awaiting_review',check_operation:{id:'check',task_id:'qa',status:'completed',passed_checks:1,required_checks:1},review_operation:{id:'review',task_id:'reviewer',status:'completed'},actions:{run_checks:false,start_review:false,review_decision:true}});await opened(f,reviewed);
  control(f,'Read independent review').click();await f.settle();const preview=f.requests.find(r=>r.url.endsWith('/reviews/review'));preview.answered=true;preview.resolve({review_id:'review',snapshot_digest:'a'.repeat(64),review_digest:'digest',receipt_id:'receipt',current:true,messages:[{text:'Independent findings reviewed.'}]});await f.settle();
  control(f,'Accept review and mark delivery ready').click();await f.settle();const post=mutation(f,'/review-decision');post.answered=true;post.reject(new Error('Decision acknowledgement lost'));await f.settle();await resolveRefresh(f,reviewed);
  assert.match(f.nodes.get('task-detail').textContent,/awaiting reconciliation/);assert.ok(!f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Accept review and mark delivery ready'));
  f.api.loadDelivery();await f.settle();const accepted=JSON.parse(post.options.body);await resolveRefresh(f,{...reviewed,status:'ready',review_operation:{...reviewed.review_operation,decision_ack:{decision:accepted.decision,receipt_id:accepted.receipt_id,review_digest:accepted.review_digest,expected_snapshot:accepted.expected_snapshot}},actions:{run_checks:false,start_review:false,review_decision:false}});
  assert.match(f.nodes.get('task-detail').textContent,/Ready for delivery/);assert.doesNotMatch(f.nodes.get('task-detail').textContent,/awaiting reconciliation/);assert.equal(f.requests.filter(r=>r.url.endsWith('/review-decision')).length,1);
});

test('malformed authority and cross-project check plan responses keep all delivery actions unavailable',async()=>{
  for(const [delivery,approvedPlan] of [[data({snapshot_digest:null}),plan()],[data(),{...plan(),project_id:'other'}]]){
    const f=fixture();await opened(f,delivery,approvedPlan);assert.match(f.nodes.get('task-detail').textContent,/incomplete/);assert.ok(!f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Run approved checks'));
  }
});

test('recorded decision acknowledgement reconciles after source changes without restoring ready authority',async()=>{
  const f=fixture(),reviewed=data({status:'awaiting_review',check_operation:{id:'check',task_id:'qa',status:'completed',passed_checks:1,required_checks:1},review_operation:{id:'review',task_id:'reviewer',status:'completed'},actions:{run_checks:false,start_review:false,review_decision:true}});await opened(f,reviewed);
  control(f,'Read independent review').click();await f.settle();const preview=f.requests.find(r=>r.url.endsWith('/reviews/review'));preview.answered=true;preview.resolve({review_id:'review',snapshot_digest:'a'.repeat(64),review_digest:'digest',receipt_id:'receipt',current:true,messages:[{text:'Independent findings reviewed.'}]});await f.settle();
  control(f,'Accept review and mark delivery ready').click();await f.settle();const post=mutation(f,'/review-decision'),accepted=JSON.parse(post.options.body);post.answered=true;post.reject(new Error('Decision acknowledgement lost'));await f.settle();
  await resolveRefresh(f,{...reviewed,status:'stale',snapshot_digest:'b'.repeat(64),review_operation:{...reviewed.review_operation,decision_ack:{decision:accepted.decision,receipt_id:accepted.receipt_id,review_digest:accepted.review_digest,expected_snapshot:accepted.expected_snapshot}},actions:{run_checks:true,start_review:false,review_decision:false}});
  assert.match(f.nodes.get('task-detail').textContent,/Evidence needs refreshing/);assert.doesNotMatch(f.nodes.get('task-detail').textContent,/awaiting reconciliation|still uncertain/);assert.ok(!f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Accept review and mark delivery ready'));
  assert.equal(control(f,'Run approved checks').disabled,true);confirmRun(f);assert.equal(control(f,'Run approved checks').disabled,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/review-decision')).length,1);
});

test('a different recorded decision identity cannot reconcile an uncertain decision',async()=>{
  for(const changed of ['decision','receipt_id','review_digest','expected_snapshot','review_id']){
    const f=fixture(),reviewed=data({status:'awaiting_review',review_operation:{id:'review',task_id:'reviewer',status:'completed'},actions:{run_checks:false,start_review:false,review_decision:true}});await opened(f,reviewed);
    control(f,'Read independent review').click();await f.settle();const preview=f.requests.find(r=>r.url.endsWith('/reviews/review'));preview.answered=true;preview.resolve({review_id:'review',snapshot_digest:'a'.repeat(64),review_digest:'digest',receipt_id:'receipt',current:true,messages:[{text:'Independent findings reviewed.'}]});await f.settle();
    control(f,'Accept review and mark delivery ready').click();await f.settle();const post=mutation(f,'/review-decision'),accepted=JSON.parse(post.options.body);post.answered=true;post.reject(new Error('Decision acknowledgement lost'));await f.settle();
    const ack={decision:accepted.decision,receipt_id:accepted.receipt_id,review_digest:accepted.review_digest,expected_snapshot:accepted.expected_snapshot};if(changed!=='review_id')ack[changed]='different';
    await resolveRefresh(f,{...reviewed,status:'stale',snapshot_digest:'b'.repeat(64),review_operation:{...reviewed.review_operation,id:changed==='review_id'?'different':'review',decision_ack:ack},actions:{run_checks:true,start_review:false,review_decision:false}});
    assert.match(f.nodes.get('task-detail').textContent,/awaiting reconciliation|still uncertain/);assert.equal(control(f,'Run approved checks').disabled,true);assert.equal(f.requests.filter(r=>r.url.endsWith('/review-decision')).length,1);
  }
});

test('coordinating tasks expose delivery only with the backend availability flag',async()=>{
  for(const available of [true,false,'true',undefined]){
    const f=fixture(),state=workspace();state.tasks[0].role='chief_of_staff';state.tasks[0].delivery_available=available;f.api.setWorkspace(state);f.api.openTask('subject');await f.settle();
    if(available===true){
      await resolveRefresh(f,data());assert.match(f.nodes.get('task-detail').textContent,/Delivery readiness/);assert.match(f.nodes.get('task-detail').textContent,/Awaiting checks/);assert.ok(control(f,'Save approved checks'));assert.match(f.nodes.get('task-detail').textContent,/Completed/);
    }else{
      assert.doesNotMatch(f.nodes.get('task-detail').textContent,/Delivery readiness/);assert.equal(f.requests.filter(r=>r.url.endsWith('/delivery')||r.url.endsWith('/check-plan')).length,0);
    }
  }
});

test('legacy implementation tasks keep the not-enforced explanation without enabling delivery work',async()=>{
  const f=fixture(),state=workspace();state.tasks[0].delivery_available=false;f.api.setWorkspace(state);f.api.openTask('subject');await f.settle();
  await resolveRefresh(f,data({status:'not_enforced',snapshot_digest:null,policy_digest:null,plan_version:0,actions:{run_checks:false,start_review:false,review_decision:false}}),plan(0,[]));
  assert.match(f.nodes.get('task-detail').textContent,/This run has no enforced delivery evidence/);assert.equal(control(f,'Run approved checks').disabled,true);assert.equal(control(f,'Start independent review').disabled,true);
});

test('definitive preflight rejection releases pending state and preserves the edited check plan',async()=>{
  const f=fixture();await opened(f);let commands=field(f,'commands');commands.value='python3 -m unittest tests.focused';commands.emit('input');let approval=field(f,'approve-plan');approval.checked=true;approval.emit('change');control(f,'Save approved checks').click();await f.settle();
  const post=mutation(f,'/check-plan');post.answered=true;post.fail(503,'Preflight is unavailable; no work started.',{not_started:true});await f.settle();await resolveRefresh(f,data(),plan());
  assert.equal(field(f,'commands').value,'python3 -m unittest tests.focused');assert.equal(field(f,'commands').disabled,false);assert.equal(field(f,'approve-plan').checked,false);assert.ok(!f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Retry original request'));assert.doesNotMatch(f.nodes.get('task-detail').textContent,/awaiting reconciliation/);
  assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1);assert.equal(control(f,'Save approved checks').disabled,true);
});

test('explicit retry reuses the original frozen checks request and never runs automatically',async()=>{
  const f=fixture();await opened(f);confirmRun(f);control(f,'Run approved checks').click();await f.settle();const original=mutation(f,'/delivery/checks'),body=JSON.parse(original.options.body);original.answered=true;original.reject(new Error('Network acknowledgement unavailable'));await f.settle();await resolveRefresh(f,data());
  assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1);assert.equal(field(f,'commands').disabled,true);assert.equal(control(f,'Run approved checks').disabled,true);assert.equal(control(f,'Retry original request').disabled,false);
  f.api.loadDelivery();await f.settle();await resolveRefresh(f,data());assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1);
  const retryButton=control(f,'Retry original request');retryButton.click();retryButton.click();await f.settle();const retry=mutation(f,'/delivery/checks');assert.equal(retry.url,original.url);assert.equal(retry.options.body,original.options.body);assert.equal(JSON.parse(retry.options.body).operation_id,body.operation_id);assert.equal(f.requests.filter(r=>r.options.method==='POST').length,2);
  retry.answered=true;retry.resolve(data());await f.settle();await resolveRefresh(f,data({status:'checks_running',check_operation:{id:body.operation_id,task_id:'qa-task',status:'running',passed_checks:0,required_checks:1},actions:{run_checks:false,start_review:false,review_decision:false}}));assert.ok(!f.nodes.get('task-detail').querySelectorAll('button').some(b=>b.textContent==='Retry original request'));assert.ok(control(f,'Open checks conversation'));
});

test('uncertain failures require a literal not-started marker and explicit retries stay disabled on stale or disconnected data',async()=>{
  const f=fixture();await opened(f);confirmRun(f);control(f,'Run approved checks').click();await f.settle();const original=mutation(f,'/delivery/checks');original.answered=true;original.fail(503,'Dispatch outcome is unknown.',{not_started:'true'});await f.settle();await resolveRefresh(f,data());assert.ok(control(f,'Retry original request'));assert.equal(control(f,'Run approved checks').disabled,true);
  f.api.setStale(true);f.api.renderDelivery();assert.equal(control(f,'Retry original request').disabled,true);control(f,'Retry original request').click();await f.settle();assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1);
  const state=workspace();state.connection.status='disconnected';f.api.setWorkspace(state);f.api.renderDelivery();assert.equal(control(f,'Retry original request').disabled,true);control(f,'Retry original request').click();await f.settle();assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1);
});

test('closing and reopening an uncertain request never retries it or replaces its frozen payload',async()=>{
  const f=fixture();await opened(f);confirmRun(f);control(f,'Run approved checks').click();await f.settle();const original=mutation(f,'/delivery/checks');original.answered=true;original.reject(new Error('Network acknowledgement unavailable'));await f.settle();await resolveRefresh(f,data());
  f.nodes.get('task-dialog').close();await f.settle();assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1);
  f.api.openTask('subject');await f.settle();await resolveRefresh(f,data());assert.equal(f.requests.filter(r=>r.options.method==='POST').length,1);assert.equal(control(f,'Retry original request').disabled,false);assert.equal(field(f,'commands').disabled,true);
  control(f,'Retry original request').click();await f.settle();const retry=mutation(f,'/delivery/checks');assert.equal(retry.url,original.url);assert.equal(retry.options.body,original.options.body);
});
