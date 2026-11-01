'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  let state = null, view = 'overview', refreshing = false, lastRefresh = null, detailId = null, detailSignature = '', stale = true, preferredRole = 'chief_of_staff';
  let browserProject = null, fileEntries = [], filesLoaded = false, filesRequest = 0, previewRequest = 0, selectedFile = '';
  let gitSnapshot = null, gitLoaded = false, gitRequest = 0, gitCheckedAt = 0, publishPreview = null, publishing = false;
  let settings = null, uploadedLogo = null, settingsBusy = false, creatingRepository = false, repositoryProject = null;
  let teamBusy = false, teamLoaded = false, teamSnapshot = null, teamRenderSignature = '';
  let projectApprovalControls=new Map(), projectApprovalSignature='';
  let agentPromptSequence = 0;
  const approvalContinuations=new Map();let displayedContinuationId=null;
  let approvalReview = null, approvalReviewSequence = 0, approvalReviewSending = false;
  let conversationId = '', conversationSequence = 0, conversationBusy = false, conversationSending = false, conversationData = null, conversationSignature = '';
  let recoveryId='', recoverySequence=0, recoveryBusy=false, recoveryFresh=false, recoveryData=null, recoveryEvidence=[], recoveryChat=null;
  let recoveryHandoff=null, recoveryHandoffCheckedAt=0;
  let recoveryAuth=null, recoveryAuthUrl=null, recoveryAuthBusy=false;
  const recoveryDrafts=new Map(), recoveryOperations=new Map();
  let deliveryId='',deliverySequence=0,deliveryData=null,deliveryPlan=null,deliveryPreview=null,deliveryCheckedAt=0,deliveryPreviewAt=0,deliveryBusy=false,deliveryFresh=false,deliveryError='';
  const deliveryDrafts=new Map(),deliveryPending=new Map(),deliveryParents=new Map();
  const attentionDismissals=new Set();
  let attentionExpanded=false;
  let outputsSequence=0;
  let failureNoticeId = null, submittedTaskId = null;
  let deleteTarget=null,deleteBusy=false;const uncertainDeletions=new Map();
  const active = new Set(['queued', 'running', 'waiting_approval']);
  const reviewableKinds = new Set(['command','file_change','permissions','elicitation','approval_question']);
  const labels = {queued:'Queued', running:'Running', waiting_approval:'Approval needed', completed:'Completed', failed:'Failed', interrupted:'Interrupted', unknown:'Unknown'};
  // Provider (from GET /api/provider, fetched once at load). Until it answers, or if it never does, every
  // label keeps its Codex wording so a server without the endpoint looks exactly as before.
  let providerInfo = null;
  const providerKey = () => ['codex', 'claude', 'none'].includes(providerInfo?.provider) ? providerInfo.provider : 'codex';
  const providerName = () => providerKey() === 'claude' ? 'Claude' : providerKey() === 'none' ? 'the provider' : 'Codex';
  const providerOff = (capability) => providerInfo?.capabilities?.[capability] === 'no';
  const providerLabel = (value) => value === 'claude' ? 'Claude' : String(value);
  const connectionDisabled = (c) => c.status === 'disabled' || providerKey() === 'none';
  const disabledLabel = (c) => providerKey() === 'none' ? 'No provider configured' : providerKey() === 'claude' ? 'Claude backend not implemented yet' : String(c.detail || 'Provider unavailable').replace(/\.$/, '');
  const connectionLabel = (c) => connectionDisabled(c) ? disabledLabel(c) : c.status === 'connected' ? `${providerName()} connected` : c.status === 'connecting' ? `Connecting to ${providerName()}` : `${providerName()} disconnected`;
  const sourceTitle = (c) => connectionDisabled(c) ? (providerKey() === 'none' ? 'No provider configured' : providerKey() === 'claude' ? 'Claude backend' : 'Provider') : `${providerKey() === 'claude' ? 'Claude' : 'Codex App Server'}${c.server_version ? ' · ' + c.server_version : ''}`;
  const requesterFallback = () => providerKey() === 'claude' ? 'Claude' : 'Codex App Server';
  function applyProviderText() {
    const set = (id, value) => { const e = $(id); if (e) e.textContent = value; };
    set('provider-note', providerKey() === 'none' ? 'No provider configured' : `Dashboard-managed ${providerName()} runs`);
    const none = providerKey() === 'none';
    set('completion-note', `Completed means the ${none ? "run's" : providerName()} turn finished. Independent acceptance and release review still apply.`);
    set('run-dialog-title', none ? 'Start a run' : `Start a ${providerName()} run`);
  }
  async function loadProvider() {
    try {
      const info = await request('/api/provider');
      if (!info || !['codex', 'claude', 'none'].includes(info.provider) || !info.capabilities || typeof info.capabilities !== 'object') return;
      providerInfo = info;
    } catch { return; }
    detailSignature = '';
    if (state) render(); else applyProviderText();
  }
  const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = text; return e; };
  const date = (value) => { if (!value) return 'Not observed'; const d = new Date(value); return Number.isNaN(d.getTime()) ? 'Unavailable' : d.toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); };
  const number = (value) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined,{maximumFractionDigits:4}) : 'Unknown';
  const project = (id) => state?.projects.find(p => p.id === id);
  const role = (id) => state?.roles.find(r => r.id === id);
  const badge = (status) => node('span', `badge ${Object.hasOwn(labels,status) ? status : 'unknown'}`, labels[status] || status || 'Unknown');
  const button = (label, action, kind = 'secondary') => { const b = node('button',`button ${kind}`,label); b.type = 'button'; b.addEventListener('click',action); return b; };
  const announce = (message) => { $('announcement').textContent = message; };
  function empty(target, title, description, action) { const box=node('div','empty-state');box.append(node('span','empty-symbol','◇'),node('strong','',title),node('div','',description));if(action)box.append(action);target.append(box); }
  async function request(path, body) {
    const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined, credentials:'same-origin', cache:'no-store'});
    let data; try { data=await response.json(); } catch { throw new Error('The local server returned an unreadable response.'); }
    if(!response.ok) {
      const error=new Error(typeof data?.error==='string' ? data.error : 'The request could not be completed.');error.status=response.status;
      // The server supplies fixed diagnostic categories and guidance, never native error payloads.
      if(typeof data?.code==='string'&&/^[a-z_]{1,80}$/.test(data.code))error.code=data.code;
      if(typeof data?.action==='string')error.action=data.action;
      if(['missing','blocked','unavailable'].includes(data?.state))error.outputState=data.state;
      error.not_started=data?.not_started===true;error.can_sensitive_review=data?.can_sensitive_review===true;error.retryable=data?.retryable===true;error.can_request_alternative=data?.can_request_alternative===true;error.resolution_mode=['decline','cancel'].includes(data?.resolution_mode)?data.resolution_mode:null;throw error;
    }
    return data;
  }
  const themes={hybrid:'Hybrid Night Shift',terminal:'Terminal Ops',rebel:'Rebel Command'};
  function applySettings(config) {
    document.body.dataset.theme=Object.hasOwn(themes,config.theme)?config.theme:'hybrid';
    $('active-theme').textContent=themes[document.body.dataset.theme];
    document.title=`${config.dashboard_name} · Development dashboard`;
    $('brand-name').textContent=config.dashboard_name;$('footer-name').textContent=config.dashboard_name;
    document.querySelector('.brand').setAttribute('aria-label',`${config.dashboard_name} home`);
    document.querySelector('.brand-logo').src=config.logo_path;
  }
  function validSettings(config) {
    return config&&typeof config.sensitive_review_enabled==='boolean'&&config.project_approval_modes&&typeof config.project_approval_modes==='object'&&!Array.isArray(config.project_approval_modes)&&Object.entries(config.project_approval_modes).every(([id,mode])=>/^[a-f0-9]{32}$/.test(id)&&['manual','automatic'].includes(mode))&&Object.hasOwn(themes,config.theme)&&typeof config.dashboard_name==='string'&&typeof config.github_username==='string'&&['public','private'].includes(config.github_visibility)&&(config.logo_path==='/brand-logo.png'||/^\/api\/logo\/[a-f0-9]{64}\.png$/.test(config.logo_path));
  }
  function populateSettings() {
    if(!settings)return;
    const form=$('settings-form');['theme','dashboard_name','github_username','github_visibility'].forEach(k=>form.elements[k].value=settings[k]);
    $('sensitive-review-enabled').checked=settings.sensitive_review_enabled;
    uploadedLogo=settings.logo_path==='/brand-logo.png'?null:settings.logo_path;
    form.elements.logo_choice.value=uploadedLogo?'custom':'default';updateLogoPreview();
    $('logo-upload').value='';renderProjectApprovalSettings(true);form.hidden=false;
  }
  function renderProjectApprovalSettings(force=false) {
    if(!settings)return;
    const projects=state?.projects||[],signature=JSON.stringify(projects.map(p=>[p.id,p.name]));
    if(!force&&signature===projectApprovalSignature)return;
    projectApprovalSignature=signature;projectApprovalControls.clear();
    const target=$('project-approval-settings');target.replaceChildren();$('confirm-project-automatic').checked=false;
    if(!projects.length){target.append(node('p','field-help',state?'Add a project before choosing its approval mode.':'Waiting for the project list…'));return;}
    projects.forEach(p=>{
      const label=node('label','',p.name),select=node('select');select.id=`approval-mode-${p.id}`;select.setAttribute('aria-label',`Approval mode for ${p.name}`);
      [['manual','Manual — review every request'],['automatic','Automatic — future requests in this project']].forEach(([value,text])=>{const option=node('option','',text);option.value=value;select.append(option);});
      select.value=settings.project_approval_modes[p.id]||'manual';select.disabled=settingsBusy;label.append(select);target.append(label);projectApprovalControls.set(p.id,select);
    });
  }
  function selectedProjectApprovalModes() {
    const modes={...settings.project_approval_modes};
    for(const [id,select] of projectApprovalControls){if(!['manual','automatic'].includes(select.value))throw new Error('Select a supported approval mode.');modes[id]=select.value;}
    return modes;
  }
  function confirmProjectApprovalModes(modes) {
    // Every save that enables or retains broad automatic authority needs explicit confirmation.
    const anyAutomatic=Object.values(modes).some(mode=>mode==='automatic');
    if(anyAutomatic&&!$('confirm-project-automatic').checked)throw new Error('Confirm the broad effect of automatic approvals before enabling them.');
  }
  function openProjectApprovalSettings() {
    const targetTaskId=approvalReview?.task_id||approvalContinuations.get(displayedContinuationId)?.task_id;
    const task=state?.tasks.find(t=>t.id===targetTaskId),projectId=task?.project_id;
    $('approval-review-dialog').close();view='settings';updateView();
    (projectApprovalControls.get(projectId)||$('settings-title')).focus();
  }
  function updateLogoPreview() {
    const choice=$('settings-form').elements.logo_choice.value;
    $('settings-logo-preview').src=choice==='custom'&&uploadedLogo?uploadedLogo:'/brand-logo.png';
  }
  function lockSettings(busy) {
    settingsBusy=busy;$('settings-form').querySelectorAll('input,select,button').forEach(el=>el.disabled=busy);$('reload-settings').disabled=busy;
  }
  async function loadSettings() {
    if(settingsBusy)return;lockSettings(true);$('settings-status').textContent='Loading settings…';$('settings-error').textContent='';
    try {const config=await request('/api/config');if(!validSettings(config))throw new Error('The configuration response was incomplete.');settings=config;applySettings(config);populateSettings();$('settings-status').textContent='Settings loaded from config.toml.';}
    catch(error){$('settings-status').textContent=`Settings unavailable. ${error.message} Reload to try again.`;}
    finally{lockSettings(false);}
  }
  async function uploadLogo() {
    const file=$('logo-upload').files[0];if(!file)return;
    $('settings-error').textContent='';
    if(file.size>1024*1024||file.size===0||file.type!=='image/png'){$('settings-error').textContent='Choose a PNG image no larger than 1 MiB.';$('logo-upload').value='';return;}
    lockSettings(true);$('settings-status').textContent='Uploading logo…';
    try {
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
      const result=await request('/api/logo',{image:btoa(binary)});
      if(!/^\/api\/logo\/[a-f0-9]{64}\.png$/.test(result.logo_path))throw new Error('The logo upload response was incomplete.');
      uploadedLogo=result.logo_path;$('settings-form').elements.logo_choice.value='custom';updateLogoPreview();$('settings-status').textContent='Logo uploaded. Save settings to activate it.';
    }catch(error){$('settings-error').textContent=error.message;$('settings-status').textContent='Logo was not activated.';}
    finally{lockSettings(false);$('logo-upload').value='';}
  }
  async function saveSettings(event) {
    event.preventDefault();const form=$('settings-form');if(settingsBusy||!form.reportValidity())return;
    if(form.elements.logo_choice.value==='custom'&&!uploadedLogo){$('settings-error').textContent='Upload a PNG before selecting an uploaded logo.';return;}
    let projectApprovalModes;try{projectApprovalModes=selectedProjectApprovalModes();confirmProjectApprovalModes(projectApprovalModes);}catch(error){$('settings-error').textContent=error.message;return;}
    const body={sensitive_review_enabled:$('sensitive-review-enabled').checked,project_approval_modes:projectApprovalModes,theme:form.elements.theme.value,dashboard_name:form.elements.dashboard_name.value.trim(),logo_path:form.elements.logo_choice.value==='custom'?uploadedLogo:'/brand-logo.png',github_username:form.elements.github_username.value.trim(),github_visibility:form.elements.github_visibility.value};
    if(!body.dashboard_name){$('settings-error').textContent='Enter a dashboard name with more than whitespace.';return;}
    lockSettings(true);$('settings-error').textContent='';$('settings-status').textContent='Saving settings…';
    try{const config=await request('/api/config',body);if(!validSettings(config))throw new Error('Save was not confirmed. Reload settings to check the current configuration.');settings=config;applySettings(config);populateSettings();$('settings-status').textContent='Settings saved and applied.';announce('Workspace settings saved.');}
    catch(error){$('settings-error').textContent=error.message;$('settings-status').textContent='Settings save was not confirmed. Reload to check before retrying.';}
    finally{lockSettings(false);}
  }
  function selectedTasks() { const id=$('project-filter').value, q=$('search').value.trim().toLocaleLowerCase(), status=$('status-filter').value, owner=$('role-filter').value;return state.tasks.filter(t=>(!id||t.project_id===id)&&(!q||String(t.title).toLocaleLowerCase().includes(q))&&(!status||t.status===status)&&(!owner||t.role===owner)); }
  function allDecisions() {
    const questions=(state.questions||[]).filter(q=>q.status==='pending'||q.status==='unavailable').map(q=>({...q,kind:'question',summary:q.status==='pending'?'The agent has a question':'A question needs review',status:'pending'}));
    return [...state.approvals,...questions];
  }
  function delegatedFor(task) {return (state?.delegated_activities||[]).filter(a=>a.parent_task_id===task.id&&a.project_id===task.project_id);}
  function activitySummary(activities) {
    const counts=new Map();activities.forEach(a=>{const label=labels[a.status]||'Unknown';counts.set(label,(counts.get(label)||0)+1);});
    return [...counts].map(([label,count])=>`${count} ${label.toLocaleLowerCase()}`).join(' · ');
  }
  function selectedApprovals(tasks) { const ids=new Set(tasks.map(t=>t.id));return allDecisions().filter(a=>ids.has(a.task_id)); }
  function options(select, items, placeholder) { const old=select.value;select.replaceChildren();if(placeholder)select.append(new Option(placeholder,''));items.forEach(i=>select.append(new Option(i.label,i.id)));if(Array.from(select.options).some(o=>o.value===old))select.value=old; }
  async function refresh(reconcileDeletion=false) {
    if(refreshing)return;refreshing=true;
    try {
      const next=await request('/api/state');
      if(!next || !['projects','tasks','approvals','roles'].every(key=>Array.isArray(next[key])) || !next.connection)throw new Error('The local server returned an incomplete workspace state.');
      const changed=JSON.stringify(next)!==JSON.stringify(state)||!$('load-error').hidden;
      const newlyFailed=next.tasks.find(t=>t.status==='failed'&&(t.id===submittedTaskId||state?.tasks.some(old=>old.id===t.id&&old.status!=='failed')));
      if(newlyFailed){failureNoticeId=newlyFailed.id;if(submittedTaskId===newlyFailed.id)submittedTaskId=null;}
      state=next;stale=false;checkApprovalReview();lastRefresh=new Date();$('load-error').hidden=true;$('loading').hidden=true;$('dashboard-content').hidden=false;
      if(deleteTarget?.uncertain&&!state.tasks.some(t=>t.id===deleteTarget.id))finishRunDeletion(deleteTarget.id);
      if(reconcileDeletion===true&&deleteTarget?.uncertain){const current=state.tasks.find(t=>t.id===deleteTarget.id);if(current){uncertainDeletions.delete(deleteTarget.id);deleteTarget={id:current.id,version:current.deletion_version,uncertain:false};$('delete-run-acknowledge').checked=false;$('delete-run-error').textContent='The run still exists. Review its current state and confirm again to retry deletion.';renderRunDeletion();$('delete-run-acknowledge').focus();}}
      if($('delete-run-dialog').open)renderRunDeletion();
      if(!changed){$('refresh-time').textContent=`Dashboard checked: ${date(lastRefresh)}`;return;}
      options($('project-filter'),state.projects.map(p=>({id:p.id,label:p.name})),'All projects');
      options($('role-filter'),state.roles,'All roles');
      render();
    } catch(error) {
      stale=true;checkApprovalReview();$('load-error').hidden=false;$('load-error-text').textContent=`${state?'Showing the last received data. It may be stale. ':'Could not load the workspace. '}${error.message}`;
      if(!state)$('loading').textContent='Workspace unavailable. Check that the local dashboard server is running, then retry.';
      $('connection-label').textContent='Dashboard data unavailable';$('connection-dot').className='connection-dot';
      // Stale native approvals must not remain actionable.
      document.querySelectorAll('[data-live-action]').forEach(b=>{b.disabled=true;});$('start-run').disabled=true;
      if(detailId&&$('task-dialog').open)renderDetail(detailId);
      if($('delete-run-dialog').open)renderRunDeletion();
    } finally {refreshing=false;if($('delete-run-dialog').open)renderRunDeletion();}
  }
  function metric(label,value,note,icon,emphasis=false) {const box=node('article','metric'),head=node('div','metric-head');head.append(node('span','',label),node('span','metric-icon',icon));box.append(head,node('div','metric-value',String(value)),node('div',`metric-note${emphasis?' emphasis':''}`,note));return box;}
  function render() {
    renderFailureNotice();renderProjectApprovalSettings();
    const tasks=selectedTasks(), approvals=selectedApprovals(tasks), pending=approvals.filter(a=>a.status==='pending');
    $('metrics').replaceChildren();
    const completed=tasks.filter(t=>t.status==='completed').length, running=tasks.filter(t=>active.has(t.status)||t.active_children>0).length;
    const known=tasks.filter(t=>t.cost?.basis==='estimated'&&typeof t.cost.credits==='number'&&Number.isFinite(t.cost.credits));
    const bases=new Set(known.map(t=>JSON.stringify([t.cost.source,t.cost.pricing_date]))), unknown=tasks.length-known.length;
    let amount='Unknown',costNote=tasks.length ? `${unknown} run${unknown===1?'':'s'} with unknown cost` : 'No execution usage observed';
    if(known.length&&bases.size===1){amount=`≈ ${number(known.reduce((sum,t)=>sum+t.cost.credits,0))}`;costNote=`Estimated credits · ${unknown} unknown run${unknown===1?'':'s'}`;}
    else if(bases.size>1){amount='Mixed basis';costNote='See individual estimates below';}
    $('metrics').append(metric('Total tasks',tasks.length,`${state.projects.filter(p=>!$('project-filter').value||p.id===$('project-filter').value).length} registered projects`,'☷'),metric('Active runs',running,`${completed} completed model turns`,'↗',running>0),metric('Human decisions',pending.length,pending.length?'Your input is needed':'No pending requests','◇',pending.length===0),metric('Execution estimate',amount,costNote,'◷'));
    $('nav-approval-count').textContent=String(allDecisions().filter(a=>a.status==='pending').length);
    $('task-count').textContent=`${tasks.length} task${tasks.length===1?'':'s'}`;
    renderTasks(tasks);renderAttention(tasks,pending);renderApprovals(approvals);renderCosts(tasks);
    const c=state.connection;$('connection-dot').className=`connection-dot ${c.status==='connected'?'connected':c.status==='connecting'?'connecting':''}`;
    $('connection-label').textContent=connectionLabel(c);applyProviderText();
    $('source-title').textContent=sourceTitle(c);
    $('source-detail').textContent=c.detail||'Only runs started in this dashboard are tracked. Existing desktop chats are not included.';
    $('source-time').textContent=`Source event: ${date(c.last_event_at)}`;$('refresh-time').textContent=`Dashboard checked: ${date(lastRefresh)}`;
    $('start-run').disabled=Boolean(state.runtime_limit_reached)||stale||!state.projects.length||!state.roles.length||c.status!=='connected'||connectionDisabled(c);
    $('start-run').title=connectionDisabled(c)?(providerKey()==='none'?'No provider configured':String(c.detail||disabledLabel(c))):!state.projects.length?'Add a project first':c.status!=='connected'?`Wait for the ${providerName()} connection`:'';
    if(detailId&&$('task-dialog').open)renderDetail(detailId);
    updateView();
    if(stale){$('connection-label').textContent='Dashboard data unavailable';$('connection-dot').className='connection-dot';document.querySelectorAll('[data-live-action]').forEach(b=>{b.disabled=true;});}
  }
  function renderTasks(tasks) {
    const target=$('task-list');target.replaceChildren();
    if(!tasks.length){empty(target,state.tasks.length?'No matching tasks':state.projects.length?'Ready for your first run':'A clear view of your team’s work',state.tasks.length?'Try a different project, status, role or search.':state.projects.length?'Start a run to see live progress, plans and approval requests.':'Add a local project to begin tracking dashboard-managed Codex runs.',!state.projects.length?button('+ Add project',openProject):undefined);return;}
    const wrap=node('div','table-scroll'),table=node('table'),head=node('thead'),row=node('tr');['TASK / PROJECT','AGENT','STATUS','UPDATED','DETAILS'].forEach(t=>row.append(node('th','',t)));head.append(row);table.append(head);const body=node('tbody');
    [...tasks].sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))).forEach(t=>{
      const r=node('tr','task-row'),title=node('td'),link=button(t.title,()=>openTask(t.id));link.className='task-link';title.append(link,node('span','subtext',project(t.project_id)?.name||'Unknown project'));
      const delegates=delegatedFor(t);if(delegates.length)title.append(node('span','subtext',`${delegates.length} delegated ${delegates.length===1?'activity':'activities'} · ${activitySummary(delegates)}`));
      const owner=node('td','',role(t.role)?.label||t.role);owner.append(node('span','subtext',t.model?`${t.model} · configured`:'Model not recorded'));
      if(t.provider&&t.provider!=='codex')owner.append(node('span','provider-chip',providerLabel(t.provider)));
      const status=node('td');status.append(badge(t.status));if(t.delivery_summary){const summary=t.delivery_summary;status.append(node('span','subtext',summary.checked_at?`Delivery evidence: ${deliveryLabels[summary.status]||'Unverified'} · ${stale?'workspace stale':summary.freshness||'freshness unknown'} · last checked ${date(summary.checked_at)}; verify in details.`:'Delivery evidence not checked.'));if(deliveryEligible(t))status.append(button('Review delivery evidence',()=>{openTask(t.id);$('delivery-heading')?.focus({preventScroll:false});}));}if(t.status==='failed')status.append(node('span','subtext',latestDiagnostic(t)?.message||t.error||'Open details to review this failure.'));
      const details=node('td'),inspect=button(t.status==='failed'?'View failure':'View details',()=>openTask(t.id));inspect.setAttribute('aria-label',`${t.status==='failed'?'View failure':'View details'}: ${t.title}`);details.append(inspect);
      if(t.status==='completed'||t.outputs?.length){const output=button(t.outputs?.length?`Outputs (${t.outputs.length})`:'Outputs',()=>openOutputs(t.id));output.setAttribute('aria-label',`Outputs: ${t.title}`);output.dataset.outputsTask=t.id;details.append(output);}
      r.tabIndex=0;r.setAttribute('aria-label',`${t.title}, ${labels[t.status]||'Unknown'}. Open task details.`);
      r.addEventListener('click',e=>{if(!e.target.closest('button,a'))openTask(t.id);});
      r.addEventListener('keydown',e=>{if(e.target===r&&['Enter',' '].includes(e.key)){e.preventDefault();openTask(t.id);}});
      r.append(title,owner,status,node('td','',date(t.updated_at)),details);body.append(r);
    });table.append(body);wrap.append(table);target.append(wrap);
  }
  function latestDiagnostic(task){return Array.isArray(task?.diagnostics)?task.diagnostics.at(-1):null;}
  function renderFailureNotice(){const task=state?.tasks.find(t=>t.id===failureNoticeId&&t.status==='failed');$('run-failure').hidden=!task;if(task)$('run-failure-text').textContent=`Run failed: ${task.title}. ${latestDiagnostic(task)?.message||task.error||'Review the recorded diagnostics.'}`;}
  function showAllAttention(destination='approvals'){["project-filter","search","status-filter","role-filter"].forEach(id=>$(id).value="");attentionExpanded=true;view=destination;render();announce('Project, search, status and role filters cleared. Showing all projects.');}
  const decisionLabel=a=>a.kind==="question"?"Answer needed":reviewableKinds.has(a.kind)?"Approval needed":"Unsupported request";
  function renderAttention(tasks,pending) {
    const target=$('attention-list');target.replaceChildren();
    const allPending=allDecisions().filter(a=>a.status==="pending"),failures=tasks.filter(t=>["failed","unknown"].includes(t.status)&&!t.attention_dismissed),allFailures=state.tasks.filter(t=>["failed","unknown"].includes(t.status)&&!t.attention_dismissed);
    target.append(node("p","subtext",`${pending.length} of ${allPending.length} outstanding decisions match current filters; ${failures.length} of ${allFailures.length} failed or unknown notices match.`));
    target.append(button("View all outstanding decisions (clears filters)",()=>showAllAttention()),button("Show all failed / unknown notices (clears filters)",()=>showAllAttention('overview')));
    target.append(node("p","subtext",`Showing ${Math.min(pending.length,attentionExpanded?pending.length:3)} of ${pending.length} matching decisions and ${Math.min(failures.length,attentionExpanded?failures.length:2)} of ${failures.length} matching notices.`));
    if(!pending.length&&!failures.length){empty(target,allPending.length||allFailures.length?'Nothing matches the current filters':'Nothing waiting on you',allPending.length||allFailures.length?'Outstanding decisions or notices exist outside these filters. Use Show all to review them.':'New approval requests and interrupted connections will appear here.');return;}
    pending.slice(0,attentionExpanded?pending.length:3).forEach(a=>{const item=node('article','attention-item'),task=tasks.find(t=>t.id===a.task_id);item.append(node("span","badge waiting_approval",decisionLabel(a)),node('h3','',a.summary||'Approval needed'),node('p','',task?.title||'Task'),button(a.kind==='question'?'Answer question':reviewableKinds.has(a.kind)?"Review request":"View blocked request",()=>{if(a.kind==='question'){openConversation(a.task_id);}else{openApprovalReview(a);}}));target.append(item);});
    tasks.filter(t=>['failed','unknown'].includes(t.status)&&!t.attention_dismissed).slice(0,attentionExpanded?tasks.length:2).forEach(t=>{const item=node('article','attention-item');item.append(badge(t.status),node('h3','',t.title),node('p','',t.status==='unknown'?'The run state could not be confirmed. Review the connection before proceeding.':latestDiagnostic(t)?.message||t.error||'The run needs review.'),button(t.status==='failed'?'View failure details':'View task',()=>openTask(t.id)));
      if(t.attention_version&&!(t.active_children>0)&&!pending.some(a=>a.task_id===t.id)){
        const dismiss=button('Dismiss notice',()=>dismissAttention(t,item,dismiss));dismiss.disabled=stale||attentionDismissals.has(t.id);dismiss.dataset.liveAction='true';item.append(dismiss,node('small','subtext','Dismisses this notice only. The task and its history remain available.'));
      }target.append(item);});
  }
  async function dismissAttention(task,item,control){
    if(stale||attentionDismissals.has(task.id))return;
    attentionDismissals.add(task.id);control.disabled=true;
    try{const result=await request(`/api/tasks/${encodeURIComponent(task.id)}/dismiss-attention`,{version:task.attention_version});if(result.task_id!==task.id||result.attention_version!==task.attention_version||result.attention_dismissed!==true)throw new Error('Notice dismissal was not confirmed. Refresh to check its state.');const current=state?.tasks.find(t=>t.id===task.id);if(current?.attention_version===result.attention_version){current.attention_dismissed=true;item.remove();}announce('Notice dismissed. Task history is unchanged.');await refresh();}
    catch(error){item.append(node('p','form-error',error.message));}
    finally{attentionDismissals.delete(task.id);control.disabled=stale;}
  }
  async function perform(buttonElement, path, body, message) {
    if(stale){announce('Refresh workspace data before acting on a live run.');return;}
    buttonElement.disabled=true;
    try {await request(path,body);announce(message);await refresh();}
    catch(error){ const e=node('p','form-error',error.message);buttonElement.parentElement.append(e);buttonElement.disabled=false; }
  }
  function approvalDecisionDescription(decision) {
    if(!decision||typeof decision!=='object')return null;
    const descriptions={human:{accept:'Approved once by you',decline:'Declined by you',cancel:'Cancellation requested by you'},human_sensitive_review:{accept:'Approved once by you after sensitive request review'},project_policy:{accept:'Approved automatically by this project’s policy'},human_guidance:{decline:'Declined after guidance was queued with Codex',cancel:'Cancellation requested after guidance was queued with Codex'}};
    if(!Object.hasOwn(descriptions,decision.source)||!Object.hasOwn(descriptions[decision.source],decision.value))return null;
    return `${descriptions[decision.source][decision.value]} · ${date(decision.at)}`;
  }
  function renderApprovals(approvals) {
    const target=$('approval-list');target.replaceChildren();
    if(!approvals.length){empty(target,'No decisions to review','Native approval requests appear here when a dashboard-managed run asks for permission.');return;}
    [...approvals].sort((a,b)=>(a.status==='pending'?-1:1)-(b.status==='pending'?-1:1)).forEach(a=>{
      const card=node('article','approval-card'),task=state.tasks.find(t=>t.id===a.task_id);card.append(node('span',`badge ${a.status==='pending'?'waiting_approval':''}`,a.status==='pending'?decisionLabel(a):a.status==='resolved'?'Resolved':'Unavailable'),node('h3','',a.summary||'Native approval request'),node('p','',`${project(task?.project_id)?.name||'Unknown project'} · ${task?.title||'Task'} · ${date(a.created_at)}`));
      if(a.kind==='question'){card.append(node('p','','Open the task conversation to review the current question or stop the run.'),button('Open conversation',()=>openConversation(a.task_id)));target.append(card);return;}
      card.append(node('p','',`Requested by: ${a.requester || role(task?.role)?.label || requesterFallback()}`));
      if(approvalContinuations.has(a.id))card.append(button('Review cancellation and guidance',()=>openApprovalContinuation(a.id)));
      const decisionDescription=approvalDecisionDescription(a.decision);if(decisionDescription)card.append(node('p','approval-decision',decisionDescription));
      if(a.reason)card.append(node('p','',a.reason));if(a.scope)card.append(node('div','scope',typeof a.scope==='string'?a.scope:JSON.stringify(a.scope)));
      if(a.status==='pending') {
        if(!reviewableKinds.has(a.kind)){card.append(node("p","conversation-notice","This native request type is unsupported and cannot be approved here."),button("View blocked request",()=>openApprovalReview(a)));target.append(card);return;}
        card.append(node('p','', 'Review the full request before approving. Decisions apply only to this request; no session-wide permissions are granted.'));
        const actions=node('div','approval-actions');
        if(reviewableKinds.has(a.kind)){const review=button('Review request',()=>openApprovalReview(a),'primary');review.setAttribute('aria-haspopup','dialog');review.dataset.liveAction='true';review.disabled=stale||state.connection.status!=='connected';actions.append(review);}
        if((a.available_decisions||[]).includes('decline')){const decline=button('Decline request',()=>perform(decline,`/api/approvals/${encodeURIComponent(a.id)}/respond`,{decision:'decline'},'Request declined.'),'danger');decline.dataset.liveAction='true';decline.disabled=state.connection.status!=='connected';actions.append(decline);}
        if(task&&(active.has(task.status)||task.active_children>0)){const stop=button(task.active_children>0?'Stop active agents':'Stop run',()=>interrupt(task,stop),'secondary');stop.dataset.liveAction='true';stop.disabled=state.connection.status!=='connected';actions.append(stop);}
        if(!(a.available_decisions||[]).includes('decline')){card.append(node('p','', 'Supported agent questions can be answered in the task conversation. Requests without a supported review cannot be approved here.'));if(task)actions.append(button('Open conversation',()=>openConversation(task.id)));}
        card.append(actions);
      } else if(a.status==='unavailable')card.append(node('p','', 'The live request is no longer actionable. Reconnecting does not replay this decision.'));
      target.append(card);
    });
  }
  function approvalReviewIdentity(approval) {return JSON.stringify([approval.id,approval.task_id,approval.kind,approval.summary,approval.reason,approval.scope,approval.requester,approval.created_at]);}
  function approvalStillLive(review) {
    const approval=state?.approvals.find(a=>a.id===review?.id);
    return !stale&&state?.connection.status==='connected'&&approval?.status==='pending'&&approval.task_id===review.task_id&&approval.kind===review.kind&&approvalReviewIdentity(approval)===review.identity&&reviewableKinds.has(approval.kind);
  }
  function clearSensitiveReview() {
    ['confirm-sensitive-reveal','confirm-sensitive-approve'].forEach(id=>$(id).checked=false);
    ['sensitive-reveal-section','sensitive-review-badge','sensitive-approve-label'].forEach(id=>$(id).hidden=true);
    $('reveal-sensitive-request').disabled=true;
  }
  function invalidateApprovalReview(message) {
    if(!approvalReview)return;
    approvalReview.review_id=null;approvalReview.sensitive_review=false;approvalReview.can_sensitive_review=false;clearSensitiveReview();approvalReviewSequence++;
    $('approve-request').disabled=true;
    $('approval-review-context').textContent='';$('approval-review-context').hidden=true;$('approval-command-context').replaceChildren();$('approval-command-context').hidden=true;
    $('approval-response-fields').replaceChildren();$('approval-response-fields').hidden=true;
    $('approval-review-status').textContent=message;
  }
  function checkApprovalReview() {
    if(approvalReview&&!approvalReview.unsupported&&!approvalStillLive(approvalReview))invalidateApprovalReview('This review is no longer live. Approval is disabled. Close and reopen a current request after refreshing.');
    const live=approvalReview&&!stale&&state?.connection.status==='connected'&&state.approvals.some(a=>a.id===approvalReview.id&&a.status==='pending');
    const unsupported=approvalReview?.unsupported===true;
    ["approve-request","configure-project-approvals","approval-project-mode","approval-review-scope"].forEach(id=>$(id).hidden=unsupported);
    if(unsupported)$("approval-review-status").textContent="This native request type is unsupported and cannot be approved here. Reopening or changing approval settings cannot add support. Close leaves the request pending. Stop run requests interruption of active work; earlier actions are not undone.";
    const sensitiveReady=approvalReview?.sensitive_review===true;
    const canReveal=approvalReview?.can_sensitive_review===true&&!sensitiveReady;
    $('sensitive-reveal-section').hidden=!canReveal;
    $('reveal-sensitive-request').disabled=!canReveal||!live||!approvalStillLive(approvalReview)||approvalReviewSending||approvalReview.loading||!$('confirm-sensitive-reveal').checked;
    $('sensitive-review-badge').hidden=!sensitiveReady;$('sensitive-approve-label').hidden=!sensitiveReady;
    $('approve-request').disabled=!live||!approvalReview?.review_id||approvalReviewSending||approvalReview.loading||(sensitiveReady&&!$('confirm-sensitive-approve').checked);
    const manualKind=['permissions','elicitation','approval_question'].includes(approvalReview?.kind);
    if(manualKind){$('configure-project-approvals').hidden=true;$('approval-project-mode').hidden=true;}
    $('approve-request').textContent=approvalReview?.kind==='permissions'?'Approve for this turn':approvalReview?.kind==='approval_question'?'Send selected answers':approvalReview?.kind==='elicitation'?'Send response':'Approve once';
    if(manualKind){try{approvalResponsePayload();}catch{$('approve-request').disabled=true;}}
    if(approvalReview?.kind==='permissions')$('approval-review-scope').textContent='Approving grants the exact permissions below for the remainder of this native turn. It may allow filesystem or network access beyond the baseline sandbox. Reject grants none. No session-wide grant is issued. Review all paths and network settings; content checks do not establish safety.';
    else if(manualKind)$('approval-review-scope').textContent='This is the exact native request and your response may authorize an external action or share the entered information with the named tool or server. Read the complete request and every choice. Never enter credentials or secrets. Nothing is sent until you choose a response.';
    else $('approval-review-scope').textContent='This decision applies only to this exact native request. It does not grant session-wide permissions or change approval policy. Approval may allow this action beyond baseline sandbox restrictions. Commands, patches and model-authored reasons below are untrusted; invoked scripts and file contents are not expanded or verified by this review. Content checks do not establish that the action is safe.';
    const declineOffered=!unsupported&&(state?.approvals.find(a=>a.id===approvalReview?.id)?.available_decisions||[]).includes('decline');
    $('decline-reviewed-request').hidden=!declineOffered;$('decline-reviewed-request').disabled=!live||!declineOffered||approvalReviewSending;
    $('decline-reviewed-request').textContent=manualKind?'Reject request':'Decline request';
    const cancelOffered=approvalReview?.kind==='elicitation'&&(state?.approvals.find(a=>a.id===approvalReview?.id)?.available_decisions||[]).includes('cancel');
    $('cancel-reviewed-request').hidden=!cancelOffered;$('cancel-reviewed-request').disabled=!live||!cancelOffered||approvalReviewSending;
    const task=state?.tasks.find(t=>t.id===approvalReview?.task_id);
    $('stop-reviewed-run').disabled=!live||!task||(!active.has(task.status)&&!(task.active_children>0))||approvalReviewSending;
    $('stop-reviewed-run').textContent=task?.active_children>0?'Stop active agents':'Stop run';
    $('retry-approval-review').hidden=!approvalReview?.retryable;
    $('retry-approval-review').disabled=!live||!approvalStillLive(approvalReview)||approvalReviewSending||approvalReview?.loading===true;
    const current=state?.approvals.find(a=>a.id===approvalReview?.id);
    const resolutionMode=current?.resolution_mode||approvalReview?.resolution_mode;
    const canAsk=Boolean(!providerOff('approval_alternative')&&!unsupported&&!manualKind&&approvalReview&&['decline','cancel'].includes(resolutionMode)&&(current?.can_request_alternative===true||approvalReview.can_request_alternative===true));
    $('request-approval-alternative').textContent=resolutionMode==='cancel'?'Send guidance and cancel this attempt':'Send guidance and decline request';
    $('approval-alternative-notice').textContent=resolutionMode==='cancel'?'This queues guidance with Codex, then requests cancellation of this native request and its turn. Queued guidance may be discarded when the turn stops. After interruption is confirmed, you can explicitly continue the same root task with the retained guidance. Nothing is approved or restarted automatically.':'This queues guidance with Codex, then declines this request. It does not approve or replay the blocked action. Revised requests follow the project’s manual or automatic approval mode.';
    ['approval-guidance-section','approval-alternative-notice','request-approval-alternative'].forEach(id=>$(id).hidden=!canAsk);
    const askDisabled=!canAsk||!live||!approvalStillLive(approvalReview)||approvalReviewSending||approvalReview.loading||approvalReview.alternativeAttempted;
    $('approval-guidance').disabled=Boolean(askDisabled);$('request-approval-alternative').disabled=Boolean(askDisabled);renderApprovalContinuation();
  }
  async function openApprovalReview(approval) {
    if(stale||state?.connection.status!=='connected')return;
    const current=state.approvals.find(a=>a.id===approval.id);
    if(!current||current.status!=='pending')return;
    displayedContinuationId=null;clearSensitiveReview();
    const sequence=++approvalReviewSequence;
    const guidanceDraft=approvalReview?.id===current.id?$('approval-guidance').value:'';
    approvalReview={id:current.id,task_id:current.task_id,kind:current.kind,identity:approvalReviewIdentity(current),review_id:null,retryable:false,loading:true,can_request_alternative:current.can_request_alternative===true,alternativeAttempted:false,resolution_mode:current.resolution_mode};
    $('approval-guidance').value=guidanceDraft;
    const task=state.tasks.find(t=>t.id===current.task_id);
    $('approval-review-title').textContent=current.summary||'Review native request';
    $('approval-project-mode').textContent=`Project approval mode: ${settings?.project_approval_modes?.[task?.project_id]==='automatic'?'Automatic for future eligible requests':'Manual review'}. Saving a mode does not approve this pending request; use Approve once after reviewing it.`;
    $('approval-review-task').textContent=`${project(task?.project_id)?.name||'Unknown project'} · ${task?.title||'Task'} · ${current.requester||role(task?.role)?.label||requesterFallback()}`;
    approvalReview.unsupported=!reviewableKinds.has(current.kind);
    $('approval-response-fields').replaceChildren();$('approval-response-fields').hidden=true;
    $('approval-review-context').textContent='';$('approval-review-context').hidden=true;$('approval-command-context').replaceChildren();$('approval-command-context').hidden=true;
    $('approval-review-status').textContent='Loading the full checked request…';
    $('approval-review-error').textContent='';$('approval-review-diagnostic').textContent='';$('approve-request').disabled=true;
    if(!$('approval-review-dialog').open)openDialog('approval-review-dialog');checkApprovalReview();
    if(approvalReview.unsupported){approvalReview.loading=false;checkApprovalReview();return;}
    try {
      const result=await request(`/api/approvals/${encodeURIComponent(current.id)}/review`);
      if(sequence!==approvalReviewSequence||!$('approval-review-dialog').open)return;
      if(!approvalStillLive(approvalReview))throw new Error('The request is no longer live.');
      if(result?.sensitive_review===true||!result||result.id!==current.id||result.task_id!==current.task_id||result.kind!==current.kind||typeof result.review_id!=='string'||!result.review_id||!result.context||typeof result.context!=='object'||Array.isArray(result.context)||!Object.keys(result.context).length)throw new Error('The full request response was incomplete.');
      renderApprovalCommands(result.context);
      renderApprovalResponse(result.context);
      $('approval-review-context').textContent=JSON.stringify(result.context,null,2);
      $('approval-review-context').hidden=false;approvalReview.review_id=result.review_id;
      $('approval-review-status').textContent='Full request loaded. Review every field below before deciding.';
      $('approve-request').disabled=approvalReviewSending;approvalReview.loading=false;checkApprovalReview();
    }catch(error){
      if(sequence!==approvalReviewSequence||!$('approval-review-dialog').open)return;
      invalidateApprovalReview('Review could not be loaded. Approval remains disabled until a complete review is available.');
      approvalReview.loading=false;approvalReview.can_sensitive_review=error.code==='scanner_blocked'&&error.can_sensitive_review===true;approvalReview.retryable=error.retryable===true;approvalReview.can_request_alternative=error.can_request_alternative===true;approvalReview.resolution_mode=error.resolution_mode||approvalReview.resolution_mode;
      $('approval-review-error').textContent=error.message;
      $('approval-review-diagnostic').textContent=[error.code?`Diagnostic: ${error.code}.`:'',error.action||'Refresh the dashboard to check the live request. No decision has been sent.'].filter(Boolean).join(' ');
      checkApprovalReview();
    }
  }
  async function revealSensitiveRequest() {
    if(!approvalReview?.can_sensitive_review||!$('confirm-sensitive-reveal').checked||approvalReviewSending||approvalReview.loading||!approvalStillLive(approvalReview))return;
    const current={...approvalReview},sequence=++approvalReviewSequence;
    approvalReview.loading=true;approvalReview.can_sensitive_review=false;clearSensitiveReview();checkApprovalReview();
    $('approval-review-status').textContent='Loading the exact request for explicit local review…';$('approval-review-error').textContent='';
    try {
      const result=await request(`/api/approvals/${encodeURIComponent(current.id)}/sensitive-review`,{confirmed:true});
      if(sequence!==approvalReviewSequence||!$('approval-review-dialog').open)return;
      if(!approvalStillLive(approvalReview)||result?.sensitive_review!==true||result.id!==current.id||result.task_id!==current.task_id||result.kind!==current.kind||typeof result.review_id!=='string'||!result.review_id||!result.context||typeof result.context!=='object'||Array.isArray(result.context)||!Object.keys(result.context).length)throw new Error('Sensitive review was not confirmed. Close and review the current request again.');
      approvalReview.sensitive_review=true;approvalReview.review_id=result.review_id;approvalReview.loading=false;
      renderApprovalCommands(result.context);$('approval-review-context').textContent=JSON.stringify(result.context,null,2);$('approval-review-context').hidden=false;
      renderApprovalResponse(result.context);
      $('approval-review-status').textContent='Sensitive request revealed locally. Review every field, then confirm the one-time risk before approving.';$('approval-review-diagnostic').textContent='';checkApprovalReview();
    }catch(error){
      if(sequence!==approvalReviewSequence||!$('approval-review-dialog').open)return;
      invalidateApprovalReview('Sensitive review could not be loaded. Nothing was approved. Close and review again before retrying.');approvalReview.loading=false;
      $('approval-review-error').textContent=error.message;checkApprovalReview();
    }
  }
  function renderApprovalResponse(context){
    const target=$('approval-response-fields');target.replaceChildren();target.hidden=true;
    approvalReview.responseFields=[];approvalReview.responseContext=context;approvalReview.responseBlocked=false;
    const kind=approvalReview.kind;
    if(kind==='approval_question'){
      target.hidden=false;target.append(node('h3','','Answer the native request'));if(!context.questions?.length)approvalReview.responseBlocked=true;
      for(const question of context.questions||[]){
        if(question.isSecret===true||question.is_secret===true){approvalReview.responseBlocked=true;target.append(node('p','conversation-notice','This question requests a secret. Complete the protected human step in '+providerName()+'; never enter the secret in this dashboard. You can reject the request here.'));continue;}
        const label=node('label','',question.question),input=node(question.options?.length?'select':'textarea');input.required=true;input.maxLength=4000;label.append(input);
        if(question.header)target.append(node('strong','',question.header));
        if(question.options?.length){const blank=node('option','','Choose an answer');blank.value='';input.append(blank);for(const option of question.options){const item=node('option','',option.label);item.value=option.label;input.append(item);if(option.description)target.append(node('p','field-help',`${option.label}: ${option.description}`));}}
        let other;if(question.options?.length&&(question.isOther===true||question.is_other===true)){const option=node('option','','Other answer');option.value='__other__';input.append(option);const otherLabel=node('label','','Other answer');other=node('textarea');other.maxLength=4000;other.hidden=true;otherLabel.append(other);target.append(otherLabel);input.addEventListener('change',()=>{other.hidden=input.value!=='__other__';});other.addEventListener('input',checkApprovalReview);}
        input.addEventListener('input',checkApprovalReview);input.addEventListener('change',checkApprovalReview);target.append(label);
        approvalReview.responseFields.push({key:question.id,input,other,type:'answer',required:true});
      }
    }else if(kind==='elicitation'){
      target.hidden=false;const mode=context.mode||'form';
      if(mode==='url'){
        target.append(node('h3','','Human step required'),node('p','conversation-notice','Complete the external sign-in or verification step in '+providerName()+' using the exact destination shown in the request. This dashboard does not open it or perform verification automatically. If '+providerName()+' resolves the request, refresh this dashboard; no second response is needed.'));
        const label=node('label','confirmation-label'),input=node('input');input.type='checkbox';label.append(input,node('span','','I completed the external step for this exact request and want to send its acknowledgement.'));target.append(label);input.addEventListener('change',checkApprovalReview);approvalReview.responseFields.push({key:'external_completed',input,type:'confirmation',required:true});
      }else if(mode!=='form'){
        target.append(node('h3','','Complete verification in '+providerName()+''),node('p','conversation-notice','This request requires native or device verification. Complete that human step in '+providerName()+', then refresh to observe its resolution. The dashboard cannot manufacture verification proof. You can reject the request here.'));approvalReview.responseBlocked=true;
      }else{
        target.append(node('h3','','Information requested by the tool'),node('p','field-help','Values below are sent to the requesting server only after you choose Send response. Never enter credentials or secrets.'));
        const schema=context.requestedSchema;
        if(!schema||schema.type!=='object'||!schema.properties||typeof schema.properties!=='object'){approvalReview.responseBlocked=true;target.append(node('p','conversation-notice','This form cannot be represented safely. Use its native form in '+providerName()+' or reject the request.'));return;}
        for(const [key,property] of Object.entries(schema.properties)){
          if(property.format==='password'||property.writeOnly===true){approvalReview.responseBlocked=true;target.append(node('p','conversation-notice','This form requests protected information. Complete its human step in '+providerName()+'; never enter credentials or secrets in this dashboard. You can reject the request here.'));continue;}
          const required=(schema.required||[]).includes(key),label=node('label','',`${property.title||key}${required?' (required)':''}`),choices=property.enum||property.oneOf?.map(option=>option.const);
          const type=property.type||'string',input=node(Array.isArray(choices)?'select':['object','array'].includes(type)?'textarea':'input');input.required=required;
          if(Array.isArray(choices)){const blank=node('option','','Choose a value');blank.value='';input.append(blank);choices.forEach((value,index)=>{const option=node('option','',String(value));option.value=String(index);input.append(option);});}
          else if(type==='boolean')input.type='checkbox';else if(type==='number'||type==='integer'){input.type='number';input.step=type==='integer'?'1':'any';if(typeof property.minimum==='number')input.min=property.minimum;if(typeof property.maximum==='number')input.max=property.maximum;}
          else{input.type='text';input.maxLength=Math.min(property.maxLength||4000,12000);if(type==='object'||type==='array'){input.rows=4;input.placeholder=`JSON ${type}`;}}
          if(property.description)label.append(node('span','field-help',property.description));label.append(input);target.append(label);input.addEventListener('input',checkApprovalReview);input.addEventListener('change',checkApprovalReview);
          approvalReview.responseFields.push({key,input,type,choices,required});
        }
      }
    }
  }
  function approvalResponsePayload(){
    if(!approvalReview||!['permissions','elicitation','approval_question'].includes(approvalReview.kind))return {};
    if(approvalReview.responseBlocked)throw new Error('Complete this request in '+providerName()+', or reject it here.');
    const values={};
    for(const field of approvalReview.responseFields||[]){
      const {input,key,type,required,choices,other}=field;
      if(type==='confirmation'){if(!input.checked)throw new Error('Confirm completion of the external step.');values[key]=true;continue;}
      if(type==='boolean'){values[key]=input.checked===true;continue;}
      if(!input.value){if(required)throw new Error('Answer every required field.');continue;}
      if(choices){values[key]=choices[Number(input.value)];continue;}
      if(type==='number'||type==='integer'){const value=Number(input.value);if(!Number.isFinite(value)||type==='integer'&&!Number.isInteger(value))throw new Error('Enter a valid number.');values[key]=value;}
      else if(type==='object'||type==='array'){try{values[key]=JSON.parse(input.value);}catch{throw new Error('Enter valid JSON for the structured field.');}}
      else if(type==='answer'){const answer=input.value==='__other__'?other?.value:input.value;if(!answer?.trim())throw new Error('Enter your other answer.');values[key]=[answer];}
      else values[key]=input.value;
    }
    return approvalReview.kind==='approval_question'?{answers:values}:approvalReview.kind==='elicitation'&&approvalReview.responseContext?.mode==='url'?values:approvalReview.kind==='elicitation'?{content:values}:{};
  }
  function renderApprovalCommands(context) {
    const section=$('approval-command-context');section.replaceChildren();section.hidden=true;
    if(typeof context.command!=='string')return;
    const subcommand=typeof context.approvalId==='string'&&context.approvalId.length>0;
    section.append(node('h3','',subcommand?'Requested subcommand':'Requested command'),node('pre','approval-review-context',context.command));
    if(typeof context.cwd==='string')section.append(node('p','',`Working directory: ${context.cwd}`));
    if(subcommand){
      section.append(node('p','field-help','This decision applies to the exact subcommand shown above. The parent command is context only; it is not approved by this decision.'));
      const parent=context.parentItemContext;
      if(parent&&typeof parent.command==='string')section.append(node('h3','','Parent command (context only)'),node('pre','approval-review-context',parent.command));
      else section.append(node('p','field-help','Parent command context was not supplied. The exact requested subcommand remains visible above.'));
    }
    section.hidden=false;
  }
  async function retryApprovalReview() {
    if(!approvalReview?.retryable||approvalReview.loading||approvalReviewSending)return;
    const current=state?.approvals.find(a=>a.id===approvalReview.id);
    if(!current||!approvalStillLive(approvalReview)){checkApprovalReview();return;}
    // Fetching a review never sends a native decision or retries execution.
    await openApprovalReview(current);
  }
  async function requestApprovalAlternative() {
    if(!approvalReview||approvalReviewSending||approvalReview.loading||approvalReview.alternativeAttempted||!approvalStillLive(approvalReview))return;
    const current=state.approvals.find(a=>a.id===approvalReview.id);
    if(current?.can_request_alternative!==true&&approvalReview.can_request_alternative!==true)return;
    const mode=current?.resolution_mode||approvalReview.resolution_mode;
    if(!['decline','cancel'].includes(mode))return;
    let text=$('approval-guidance').value.trim();
    if(mode==='cancel'&&!text)text='Please propose a fresh bounded, complete, reviewable alternative. Do not repeat the blocked action without a new approval.';
    if(text.length>12000){$('approval-review-error').textContent='Keep guidance within 12,000 characters.';return;}
    const reviewId=approvalReview.id;approvalReview.alternativeAttempted=true;approvalReviewSending=true;
    invalidateApprovalReview(mode==='cancel'?'Queuing guidance with Codex, then requesting cancellation of this attempt.':'Sending guidance to the agent. The current request will be declined after delivery is confirmed.');
    $('approval-review-error').textContent='';$('approval-review-diagnostic').textContent='';checkApprovalReview();
    try {
      const result=await request(`/api/approvals/${encodeURIComponent(reviewId)}/alternative`,mode==='cancel'?{text,mode:'cancel'}:{text});
      if(result?.guidance_sent===true&&result.cancel_sent===true&&mode==='cancel'){
        approvalContinuations.set(reviewId,{approval_id:reviewId,task_id:current.task_id,text,origin_thread_id:result.origin_thread_id,origin_turn_id:result.origin_turn_id,root_task:result.root_task,attempted:false,phase:'waiting'});
        if($('approval-review-dialog').open&&approvalReview?.id===reviewId){approvalReview=null;displayedContinuationId=reviewId;$('approval-guidance').value='';}
        announce('Guidance queued with Codex and cancellation requested. No new turn was started.');return;
      }
      if(result?.guidance_sent!==true||typeof result?.request_declined!=='boolean')throw new Error('The guidance and decline were not both confirmed.');
      const partial=result.request_declined===false;
      announce(partial?'Guidance was queued. The original request was already resolved, so no decline was sent.':'Guidance queued with Codex and the current request declined. Revised requests follow the project approval mode.');
      if($('approval-review-dialog').open&&approvalReview?.id===reviewId){
        approvalReview=null;$('approval-guidance').value='';
        $('approval-review-status').textContent=partial?'Guidance was queued, but the original request was already resolved, so no decline was sent. Check the conversation and current run state. This action granted no approval and will not resend guidance automatically. Any new request follows the project’s manual or automatic approval mode.':'Guidance queued with Codex. The current request was declined; no approval was granted. The agent can propose a revised action, which follows this project’s manual or automatic approval mode.';
      }
    }catch(error){
      if($('approval-review-dialog').open&&approvalReview?.id===reviewId){
        invalidateApprovalReview('The guidance and decline were not confirmed. Check the latest run state before taking another action.');
        $('approval-review-error').textContent=`${error.message} No automatic retry will occur.`;
        $('approval-review-diagnostic').textContent=error.action||'Review the conversation and current request before trying again. A new review is required before any approval.';
      }
    }finally{approvalReviewSending=false;checkApprovalReview();await refresh();}
  }
  function openApprovalContinuation(id) {
    if(!approvalContinuations.has(id))return;
    approvalReview=null;clearSensitiveReview();displayedContinuationId=id;$('approve-request').disabled=true;
    $('approval-review-context').textContent='';$('approval-review-context').hidden=true;$('approval-command-context').replaceChildren();$('approval-command-context').hidden=true;
    const continuation=approvalContinuations.get(id),task=state?.tasks.find(t=>t.id===continuation.task_id);
    $('approval-review-task').textContent=`${project(task?.project_id)?.name||'Unknown project'} · ${task?.title||'Task'}`;
    $('approval-project-mode').textContent='Any revised requests follow this project’s manual or automatic approval mode.';
    $('approval-review-title').textContent='Continue after cancellation';$('approval-review-error').textContent='';$('approval-review-diagnostic').textContent='';
    if(!$('approval-review-dialog').open)openDialog('approval-review-dialog');checkApprovalReview();
  }
  function renderApprovalContinuation() {
    const continuation=approvalContinuations.get(displayedContinuationId),section=$('approval-continuation');section.hidden=!continuation;
    if(!continuation)return;
    $('continuation-guidance').textContent=continuation.text;
    $('continuation-origin').textContent=JSON.stringify({task_id:continuation.task_id,thread_id:continuation.origin_thread_id,turn_id:continuation.origin_turn_id},null,2);
    const task=state?.tasks.find(t=>t.id===continuation.task_id);
    const bound=continuation.root_task===true&&typeof continuation.origin_thread_id==='string'&&typeof continuation.origin_turn_id==='string'&&task?.thread_id===continuation.origin_thread_id&&task?.turn_id===continuation.origin_turn_id;
    const ready=bound&&task.status==='interrupted'&&!task.active_children&&!stale&&state?.connection.status==='connected'&&!approvalReviewSending&&!continuation.attempted;
    $('continue-approval-guidance').disabled=!ready;$('continue-approval-guidance').hidden=continuation.root_task!==true;
    $('open-cancelled-conversation').disabled=!task;
    $('approval-review-status').textContent=continuation.phase==='sent'?'A new turn was requested with your retained guidance. Check the task conversation for progress.':continuation.phase==='requesting'?'Requesting a new turn with your retained guidance. Waiting for confirmation.':continuation.phase==='uncertain'?'Continuation delivery could not be confirmed. Inspect the task conversation before taking another action. No automatic retry will occur.':'Guidance was queued with Codex and cancellation was requested. No replacement turn has started.';
    $('continuation-status').textContent=continuation.attempted?'This continuation will not be sent again automatically. Use the task conversation to inspect the result.':continuation.root_task===false?'The cancelled request belongs to a child agent. This dashboard cannot resume that child through the coordinating task’s message endpoint. Open the coordinating conversation to decide the next step; the guidance below is retained.':!bound?'The original thread or turn no longer matches. Continuation is disabled; inspect the task conversation.':ready?'Interruption of the original turn is confirmed. Continue with guidance starts a new turn on the same task and sends only the retained guidance below.':stale||state?.connection.status!=='connected'?'Restore a fresh Codex connection before continuing.':'Waiting for the original turn to report interrupted. Continuation remains disabled.';
  }
  async function continueApprovalGuidance() {
    const continuation=approvalContinuations.get(displayedContinuationId);if(!continuation||approvalReviewSending||continuation.attempted)return;
    const task=state?.tasks.find(t=>t.id===continuation.task_id);
    if(stale||state?.connection.status!=='connected'||continuation.root_task!==true||typeof continuation.origin_thread_id!=='string'||typeof continuation.origin_turn_id!=='string'||task?.thread_id!==continuation.origin_thread_id||task?.turn_id!==continuation.origin_turn_id||task.status!=='interrupted'||task.active_children)return;
    continuation.attempted=true;continuation.phase='requesting';approvalReviewSending=true;checkApprovalReview();$('approval-review-error').textContent='';
    try{
      await request(`/api/tasks/${encodeURIComponent(continuation.task_id)}/message`,{text:continuation.text,expected_turn_id:continuation.origin_turn_id});
      continuation.phase='sent';
      announce('A new turn was requested with your retained guidance. The cancelled action was not replayed.');
    }catch(error){continuation.phase='uncertain';$('approval-review-error').textContent=`${error.message} Continuation was not confirmed and will not retry automatically. Check the task conversation.`;}
    finally{approvalReviewSending=false;checkApprovalReview();await refresh();}
  }
  async function respondReviewedApproval(decision) {
    if(approvalReviewSending||!approvalReview)return;
    const review={...approvalReview};
    if(decision==='accept'&&(!review.review_id||!approvalStillLive(review))){invalidateApprovalReview('This review is stale. Close and review the current request again.');return;}
    if(decision==='accept'&&review.sensitive_review&&!$('confirm-sensitive-approve').checked)return;
    if(stale||state?.connection.status!=='connected')return;
    const approval=state.approvals.find(a=>a.id===review.id);
    if(approval?.status!=='pending')return;
    let response={};if(decision==='accept'){try{response=approvalResponsePayload();}catch(error){$('approval-review-error').textContent=error.message;checkApprovalReview();return;}}
    const sequence=approvalReviewSequence;
    approvalReviewSending=true;['approve-request','decline-reviewed-request','stop-reviewed-run'].forEach(id=>$(id).disabled=true);checkApprovalReview();$('approval-review-error').textContent='';
    try {
      await request(`/api/approvals/${encodeURIComponent(review.id)}/respond`,decision==='accept'?{decision,review_id:review.review_id,...response,...(review.sensitive_review?{sensitive_confirmed:true}:{})}:{decision});
      announce(decision==='accept'?(review.kind==='permissions'?'The requested permissions were approved for this turn. No session-wide grant was issued.':'Your response was sent. Run progress still requires observation.'):decision==='cancel'?'Request cancellation sent. Run progress still requires observation.':'Request declined.');
      if(sequence===approvalReviewSequence)$('approval-review-dialog').close();
    }catch(error){
      if($('approval-review-dialog').open&&approvalReview?.id===review.id){invalidateApprovalReview('Decision was not confirmed. Approval is disabled; close and review again before retrying.');$('approval-review-error').textContent=`${error.message} No automatic retry will occur.`;}
    }finally{approvalReviewSending=false;await refresh();checkApprovalReview();}
  }
  function renderCosts(tasks) {
    const target=$('cost-list');target.replaceChildren();
    if(!tasks.length)empty(target,'No execution usage yet','Usage will appear when Codex reports it for a dashboard-managed run.');
    else {const wrap=node('div','table-scroll'),table=node('table'),head=node('thead'),hr=node('tr');['TASK','CONFIGURED MODEL','OBSERVED TOKENS','CREDIT ESTIMATE','BASIS / SOURCE'].forEach(t=>hr.append(node('th','',t)));head.append(hr);table.append(head);const body=node('tbody');tasks.forEach(t=>{const r=node('tr'),title=node('td'),link=button(t.title,()=>openTask(t.id));link.className='task-link';title.append(link,node('span','subtext',project(t.project_id)?.name||'Unknown project'));const cost=t.cost,estimate=cost?.basis==='estimated'&&typeof cost.credits==='number'&&Number.isFinite(cost.credits);const source=node('td','',estimate?'Estimated · Standard speed':'Unknown');source.append(node('span','subtext',cost?.source||'No verified cost basis'),node('span','subtext',cost?.pricing_date?`Pricing: ${cost.pricing_date}`:''));r.append(title,node('td','',t.model||'Not recorded'),node('td','',t.usage?number(t.usage.total_tokens):'Not observed'),node('td','',estimate?`≈ ${number(cost.credits)} credits`:'Unknown'),source);body.append(r);});table.append(body);wrap.append(table);target.append(wrap);}
    const p=state.pricing||{};$('pricing-note').replaceChildren(node('span','',`Standard-speed workspace credit estimates are not verified charges or invoices. No currency conversion. Estimates cover reported main-thread usage only; spawned-agent usage is not rolled up. ${p.pricing_date?'Pricing date: '+p.pricing_date+'. ':''}`));
    if(p.source){try{const url=new URL(p.source);if(url.protocol==='https:'&&['learn.chatgpt.com','developers.openai.com','openai.com'].includes(url.hostname)){const link=node('a','','Pricing source');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';$('pricing-note').append(link);}}catch{/* Unrecognized pricing URLs remain unlinked. */}}
  }
  function updateView() {
    const titles={overview:['Workspace overview','Follow the work. Understand the usage. Unblock your team.'],tasks:['Development tasks','Live status and execution evidence across your projects.'],approvals:['Human approvals','Review requests that need a decision to move forward.'],costs:['Execution costs','Observed usage and clearly labelled workspace credit estimates.'],files:['Project files','Inspect project source safely, without leaving your workspace.'],git:['Git & publish','Check repository status and publish committed work to a reviewed destination.'],team:['Your rebel crew','Meet the agents, review their latest recorded work and celebrate contributions.'],conversations:['Run conversations','Answer agent questions, guide live work and review observed exchanges.'],settings:['Workspace settings','Personalise your dashboard and choose defaults for new repositories.']};
    $('page-title').textContent=titles[view][0];$('page-subtitle').textContent=titles[view][1];$('breadcrumb-view').textContent=view[0].toUpperCase()+view.slice(1);
    document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    $('work-panel').parentElement.hidden=!['overview','tasks'].includes(view);$('attention-panel').hidden=view!=='overview';$('approvals-panel').hidden=view!=='approvals';$('costs-panel').hidden=view!=='costs';
    $('files-panel').hidden=view!=='files';$('git-panel').hidden=view!=='git';$('settings-panel').hidden=view!=='settings';$('team-panel').hidden=view!=='team';$('conversations-panel').hidden=view!=='conversations';
    if(view==='team'&&!teamLoaded)loadTeam();
    if(view==='conversations')ensureConversation();
    document.querySelector('.filterbar').hidden=['settings','conversations'].includes(view);document.querySelector('.heading-actions').hidden=['settings','team','conversations'].includes(view);document.querySelector('.source-strip').hidden=view==='settings';
    const projectView=['files','git','settings','team','conversations'].includes(view);
    $('metrics').hidden=projectView;$('search').closest('label').hidden=projectView;$('status-filter').hidden=projectView;$('role-filter').hidden=projectView;
    document.querySelector('.completion-note').hidden=projectView;
    if(view==='team'&&teamSnapshot)renderTeam();
    $('work-panel').parentElement.classList.toggle('tasks-only',view==='tasks');
    if(state)ensureProjectViews();
  }
  async function loadTeam() {
    if(teamBusy)return;teamBusy=true;teamLoaded=true;$('refresh-team').disabled=true;$('team-status').textContent='Loading your crew…';
    try{const result=await request('/api/team');if(!Array.isArray(result.members)||!Array.isArray(result.awards))throw new Error('The team response was incomplete.');const changed=JSON.stringify(teamSnapshot)!==JSON.stringify(result);teamSnapshot=result;if(changed)renderTeam();$('team-status').textContent=`${result.members.length} configured roles · observed direct and delegated activity`;}
    catch(error){$('team-status').textContent=`${teamSnapshot?'Showing the last received crew records. ':''}Team unavailable. ${error.message}`;}
    finally{teamBusy=false;$('refresh-team').disabled=false;}
  }
  function renderTeam() {
    const signature=JSON.stringify([teamSnapshot,$('project-filter').value,state?.projects,state?.tasks.map(t=>[t.id,t.title,t.project_id])]);if(signature===teamRenderSignature)return;teamRenderSignature=signature;
    const focusKey=[...$('team-grid').querySelectorAll('button')].includes(document.activeElement)?document.activeElement?.dataset.activityFocus:null;
    const grid=$('team-grid');grid.replaceChildren();
    if(!teamSnapshot.members.length)empty(grid,'No team profiles available','The configured agent roster will appear here.');
    teamSnapshot.members.forEach(m=>{
      const card=node('article','crew-card'),portrait=node('img','crew-portrait');portrait.alt=`Original fictional portrait of ${m.name}`;portrait.width=300;portrait.height=240;
      if(typeof m.id==='string'&&/^[a-z_]+$/.test(m.id)&&m.portrait===`/team-portraits/${m.id}.svg`)portrait.src=m.portrait;
      const body=node('div','crew-body'),head=node('div','crew-heading');head.append(node('h3','',m.name));if(m.agent_of_week)head.append(node('span','crew-award','★ Agent of the Week'));
      body.append(head,node('div','crew-role',m.role),node('p','crew-description',m.description),node('p','subtext',`Configured: ${m.model||'Model not configured'} · ${m.reasoning||'default'} reasoning`));
      const latest=node('section','crew-latest');latest.setAttribute('aria-label',`Recorded activity for ${m.name}`);
      const projectId=$('project-filter').value,activities=(Array.isArray(m.activities)?m.activities:m.last_task?[m.last_task]:[]).filter(a=>!projectId||a.project_id===projectId);
      latest.append(node('span','tiny-label',`RECORDED ACTIVITY · ${activities.length}`));
      if(!activities.length)latest.append(node('p','',projectId?'No observed activity in this project.':'No dashboard activity recorded yet.'));
      const list=node('ul','crew-activities');
      [...activities].sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))).forEach(a=>{
        const item=node('li','crew-activity'),parent=state?.tasks.find(t=>t.id===(a.parent_task_id||a.id)&&t.project_id===a.project_id),delegated=a.source==='delegated'||(a.source!=='direct'&&Boolean(a.parent_task_id));
        if(parent){const link=button(a.title,()=>openTask(parent.id));link.className='task-link';link.dataset.activityFocus=`${m.id}:${a.source||'task'}:${a.id}`;link.setAttribute('aria-label',`${a.title}: open ${delegated?'coordinating task':'task'} details`);item.append(link);}
        else item.append(node('strong','',a.title));
        item.append(badge(a.status),node('small','subtext',`${delegated?'Delegated':'Direct'} · ${project(a.project_id)?.name||'Unknown project'}`));
        if(delegated)item.append(node('small','subtext',`Coordinating task: ${parent?.title||'Unavailable'}`));
        item.append(node('small','subtext',`Updated ${date(a.updated_at)}`));list.append(item);
      });latest.append(list);
      const details=button('Details',()=>openAgentDetails(m));details.setAttribute('aria-label',`Details for ${m.name}`);details.setAttribute('aria-haspopup','dialog');
      details.dataset.activityFocus=`${m.id}:details`;
      body.append(details,latest,node('div','crew-coins',`◈ ${number(m.coins)} Rebel coins`));card.append(portrait,body);grid.append(card);
    });
    const awards=$('team-awards'),projectId=$('project-filter').value,visibleAwards=teamSnapshot.awards.filter(a=>!projectId||state?.tasks.some(t=>t.id===a.source_task&&t.project_id===projectId));awards.replaceChildren();if(!visibleAwards.length)empty(awards,'No commendations recorded yet','Awards will appear when the Chief of Staff issues them for eligible recorded work.');
    else visibleAwards.forEach(a=>{const record=node('article','award-record');record.append(node('strong','',teamSnapshot.members.find(m=>m.id===a.recipient_id)?.name||'Crew member'),node('span','badge',`${a.kind==='agent_of_week'?'Agent of the Week · ':''}+${number(a.coins)} Rebel coins`),node('p','',a.reason||'Recorded commendation'),node('small','subtext',`Issued by the Chief of Staff · ${date(a.issued_at)}`));if(state?.tasks.some(t=>t.id===a.source_task))record.append(button('View source task',()=>openTask(a.source_task),'secondary'));awards.append(record);});
    if(focusKey)[...grid.querySelectorAll('button')].find(b=>b.dataset.activityFocus===focusKey)?.focus();
  }
  async function openAgentDetails(member) {
    const sequence=++agentPromptSequence;
    $('agent-dialog-title').textContent=`${member.name} · ${member.role}`;
    $('agent-prompt-status').textContent='Loading personal prompt…';
    $('agent-prompt').textContent='';$('agent-prompt').hidden=true;
    openDialog('agent-dialog');
    try {
      const result=await request(`/api/team/${encodeURIComponent(member.id)}/prompt`);
      if(sequence!==agentPromptSequence||!$('agent-dialog').open)return;
      if(result.role_id!==member.id||typeof result.prompt!=='string'||!result.prompt.trim())throw new Error('The prompt response was incomplete.');
      $('agent-prompt').textContent=result.prompt;$('agent-prompt').hidden=false;
      $('agent-prompt-status').textContent='Personal prompt';
    } catch(error) {
      if(sequence!==agentPromptSequence||!$('agent-dialog').open)return;
      $('agent-prompt-status').textContent=`Prompt unavailable. ${error.message} Close and reopen Details to try again.`;
    }
  }
  function openConversation(id) {view='conversations';conversationId='';updateView();$('conversation-task').value=id;selectConversation();$('main').focus();}
  function ensureConversation() {
    const select=$('conversation-task'),previous=select.value;
    options(select,(state?.tasks||[]).map(t=>({id:t.id,label:`${t.title} · ${project(t.project_id)?.name||'Project'}`})),'Select a task');
    if(previous&&select.value!==previous)selectConversation();
    if(!conversationId){$('conversation-content').replaceChildren();empty($('conversation-content'),'Select a run to join the conversation','Only dashboard-managed tasks have a conversation here.');$('refresh-conversation').disabled=!select.value;}
  }
  function selectConversation() {
    conversationId=$('conversation-task').value;conversationData=null;conversationSignature='';conversationSequence+=1;
    $('conversation-content').replaceChildren();if(conversationId)loadConversation();else ensureConversation();
  }
  async function loadConversation() {
    const id=conversationId;if(!id||conversationBusy||conversationSending)return;
    const sequence=conversationSequence;conversationBusy=true;$('refresh-conversation').disabled=true;
    if(!conversationData)$('conversation-content').textContent='Loading conversation…';
    try{const result=await request(`/api/tasks/${encodeURIComponent(id)}/conversation`);if(sequence!==conversationSequence||id!==conversationId)return;
      if(result.task_id!==id||!Array.isArray(result.messages)||!Array.isArray(result.questions))throw new Error('The conversation response was incomplete.');
      conversationData=result;const signature=JSON.stringify([result,stale,state?.connection.status,state?.tasks.find(t=>t.id===id),state?.approvals.filter(a=>a.task_id===id)]);if(signature!==conversationSignature){conversationSignature=signature;renderConversation();}
    }catch(error){if(sequence===conversationSequence){conversationSignature='';const target=$('conversation-content');
      // Keep unsent drafts and the last received log when a poll fails. Native
      // actions stay disabled until a fresh conversation snapshot arrives.
      target.querySelector('.conversation-refresh-error')?.remove();
      const notice=node('p','conversation-refresh-error file-message',`Conversation unavailable. ${error.message} Your unsent answers remain in the form. Refresh to restore sending; nothing will retry automatically.`);notice.setAttribute('role','alert');target.append(notice);
      target.querySelectorAll('button, textarea, select').forEach(control=>{control.disabled=true;});
    }}
    finally{conversationBusy=false;$('refresh-conversation').disabled=!conversationId;}
  }
  function conversationAgentName(id, agents) {
    const identity=agents&&typeof agents==='object'&&!Array.isArray(agents)&&Object.hasOwn(agents,id)?agents[id]:null;
    return identity&&typeof identity.role_id==='string'&&typeof identity.name==='string'&&identity.name.trim()?identity.name:'Unknown agent';
  }
  function conversationMessageHeading(message, agents) {
    if(message.kind==='user')return 'You';
    if(message.kind==='system')return 'System';
    const sender=conversationAgentName(message.sender,agents),receivers=Array.isArray(message.receivers)?message.receivers:[];
    return sender+(receivers.length?' → '+receivers.map(id=>conversationAgentName(id,agents)).join(', '):'');
  }
  function conversationAgentIdentifiers(message) {
    const details=node('details','agent-identifiers');details.append(node('summary','','Agent identifiers'));
    details.append(node('pre','',JSON.stringify({sender:message.sender||null,receivers:Array.isArray(message.receivers)?message.receivers:[]},null,2)));return details;
  }
  function renderConversation() {
    const result=conversationData,target=$('conversation-content'),drafts=new Map([...target.querySelectorAll('[data-draft-key]')].map(e=>[e.dataset.draftKey,e.value])),focusKey=target.contains(document.activeElement)?document.activeElement.dataset.draftKey:null,selection=document.activeElement?.selectionStart,selectionEnd=document.activeElement?.selectionEnd,selectionDirection=document.activeElement?.selectionDirection;
    const oldLog=target.querySelector('.conversation-log'),page=document.scrollingElement,pageTop=page?.scrollTop;
    const top=oldLog?.scrollTop||0,follow=!!oldLog&&oldLog.scrollHeight-top-oldLog.clientHeight<32;
    const anchor=oldLog&&[...oldLog.children].find(e=>e.offsetTop+e.offsetHeight>oldLog.offsetTop+top),anchorOffset=anchor?anchor.offsetTop-oldLog.offsetTop-top:0;
    let body=target.querySelector('.conversation-body');
    if(!body){target.replaceChildren();body=node('div','conversation-body');target.append(body);body.append(node('p','conversation-notice','Only scanned, completed messages and observed collaboration events are shown. Tool commands, reasoning and token fragments are withheld. History is saved locally in the private dashboard database; existing desktop chats are excluded. Never enter secrets.'));}
    else [...body.children].forEach(child=>{if(child!==oldLog&&child!==body.children[0])child.remove();});
    target.querySelector('.conversation-refresh-error')?.remove();
    const log=oldLog||node('div','conversation-log');log.setAttribute('role','log');log.setAttribute('aria-label','Recorded run messages');
    const task=state?.tasks.find(t=>t.id===conversationId),assessmentTask=task?.task_purpose==='recovery_assessment',assessmentReady=assessmentTask&&result.send_mode==='assessment';
    const deliveryParent=deliveryParents.get(conversationId);if(deliveryParent&&state?.tasks.some(item=>item.id===deliveryParent))body.append(button('Back to delivery review',()=>openTask(deliveryParent)));
    const messageSignature=JSON.stringify([result.messages,result.agents]);
    if(log.dataset.messages!==messageSignature){
    const previous=[...log.children];if(!result.messages.length||previous.some((e,i)=>e.dataset.message!==JSON.stringify(result.messages[i])))log.replaceChildren();
    if(!result.messages.length){
      if(task?.status==='failed')empty(log,'This run failed before any conversation was recorded',latestDiagnostic(task)?.message||task.error||'No agent message is available for this run.',button('View failure details',()=>openTask(task.id)));
      else empty(log,'No messages recorded yet','Completed messages appear after they pass the safety scan.');
    }
    result.messages.forEach((m,index)=>{if(log.children[index]?.dataset.message===JSON.stringify(m))return;const message=node('article',`conversation-message ${m.kind==='user'?'human':''}`);message.append(node('strong','',conversationMessageHeading(m,result.agents)),node('small','subtext',`${date(m.created_at)}${m.status?' · '+m.status:''}`),node('p','',m.text||'Message content withheld.'));if(['agent','interagent'].includes(m.kind))message.append(conversationAgentIdentifiers(m));message.dataset.message=JSON.stringify(m);log.append(message);});log.dataset.messages=messageSignature;}if(!oldLog)body.append(log);
    const jump=button('Jump to latest',()=>{log.scrollTop=log.scrollHeight;jump.hidden=true;});jump.hidden=true;body.append(jump);
    if(Number.isInteger(result.omitted_count)&&result.omitted_count>0)body.append(node('p','conversation-notice','Some events or actions were omitted because a runtime processing limit was reached. This log has incomplete coverage.'));
    const updateJump=()=>{jump.hidden=log.scrollHeight-log.scrollTop-log.clientHeight<32;};log.onscroll=updateJump;
    const exchanges=node('details','exchange-log');exchanges.append(node('summary','',`Agent-to-agent exchanges (${result.messages.filter(m=>m.kind==='interagent').length})`));result.messages.filter(m=>m.kind==='interagent').forEach(m=>{const entry=node('article');entry.append(node('p','',`${conversationMessageHeading(m,result.agents)}: ${m.text||'Content withheld.'}`),conversationAgentIdentifiers(m));exchanges.append(entry);});if(!result.messages.some(m=>m.kind==='interagent'))exchanges.append(node('p','','No interagent exchange has been observed for this run.'));body.append(exchanges);
    const pendingApprovals=(state?.approvals||[]).filter(a=>a.task_id===conversationId&&a.status==='pending');
    if(pendingApprovals.length){const decisions=node('section','conversation-decisions');decisions.setAttribute('aria-label','Requests blocking this conversation');decisions.append(node('h3','','Resolve pending requests'),node('p','conversation-notice','The agent is waiting for a decision. Review each request here, or send revised guidance from its review dialog. Sending ordinary chat does not resolve an approval.'));
      pendingApprovals.forEach(a=>{const card=node('article','approval-card'),review=button(reviewableKinds.has(a.kind)?"Review request":"View blocked request",()=>openApprovalReview(a));review.disabled=stale||state?.connection.status!=='connected';review.dataset.liveAction='true';card.append(node('h4','',a.summary||'Native approval request'),node('p','',a.reason||'A human decision is required before this action can proceed.'),review);decisions.append(card);});body.append(decisions);
    }
    result.questions.forEach(q=>renderQuestion(body,q));
    const form=node('form','conversation-composer'),label=node('label','',assessmentTask?'Ask about recovery':result.send_mode==='steer'?'Guide this active run':'Continue this task'),input=node('textarea');input.rows=4;input.maxLength=16000;input.required=true;input.name='text';input.id='conversation-message';input.dataset.draftKey='composer';label.htmlFor=input.id;input.placeholder='Give clear guidance or ask a follow-up. Do not include secrets.';
    const error=node('p','form-error');error.setAttribute('role','alert');const actions=node('div','dialog-actions'),send=button(result.send_mode==='steer'?'Send guidance':'Send follow-up',()=>{},'primary');send.type='submit';send.disabled=conversationSending||!result.can_send||stale||(!assessmentReady&&state?.connection.status!=='connected');input.disabled=send.disabled;
    if(result.recovery_available===true&&!providerOff('recovery'))body.append(node('p','conversation-notice','This task or its delegated work needs recovery checks. Inspect the evidence before planning continuation.'),button('Recover task',()=>openRecovery(conversationId)));
    if(send.disabled)form.append(node('p','conversation-notice',result.blocked_reason||'This run cannot receive a message now. Restore the live connection or select a current dashboard-owned task. Runs from an earlier server session are read-only.'));
    form.append(label,input,node('p','conversation-notice',assessmentTask?'Sending starts assessment agent work and can consume workspace usage. This conversation cannot change project files, run project commands or continue development.':'Sending can consume workspace usage and modify project files. Guidance does not undo actions already taken.'),error);actions.append(send);form.append(actions);body.append(form);
    target.querySelectorAll('[data-draft-key]').forEach(e=>{if(drafts.has(e.dataset.draftKey)){e.value=drafts.get(e.dataset.draftKey);e.dispatchEvent(new Event('change'));}if(e.dataset.draftKey===focusKey&&!e.disabled){e.focus({preventScroll:true});if(typeof selection==='number'&&e.tagName==='TEXTAREA')e.setSelectionRange(selection,selectionEnd??selection,selectionDirection);}});
    const retainedAnchor=anchor&&[...log.children].find(e=>e.dataset.message===anchor.dataset.message);
    if(oldLog){log.scrollTop=follow?log.scrollHeight:retainedAnchor?retainedAnchor.offsetTop-log.offsetTop-anchorOffset:top;}
    updateJump();if(page&&typeof pageTop==='number')page.scrollTop=pageTop;
    form.addEventListener('submit',async event=>{event.preventDefault();if(conversationSending||stale||(!assessmentReady&&state?.connection.status!=='connected')||!form.reportValidity()||!input.value.trim()||send.disabled)return;
      conversationSending=true;send.disabled=true;input.disabled=true;error.textContent='';const id=conversationId,sequence=conversationSequence,text=input.value.trim();
      try{await request(`/api/tasks/${encodeURIComponent(id)}/message`,{text,expected_turn_id:result.turn_id??state.tasks.find(t=>t.id===id)?.turn_id??null});if(sequence===conversationSequence){input.value='';announce('Message sent to the run.');conversationSignature='';}}
      catch(e){if(sequence===conversationSequence)error.textContent=`${e.message} Your message remains here. Sending will not retry automatically.`;}
      finally{conversationSending=false;if(sequence===conversationSequence){const savedError=error.textContent;conversationSignature='';await refresh();await loadConversation();if(savedError){const currentError=$('conversation-content').querySelector('.conversation-composer .form-error');if(currentError)currentError.textContent=savedError;}}}
    });
  }
  function renderQuestion(body,requestData) {
    const card=node('form','question-card');card.dataset.questionId=requestData.id;card.append(node('h3','',requestData.status==='pending'?'The agent has a question':requestData.status==='resolved'?'Question answered':'Question unavailable'));
    if(requestData.status==='pending')card.append(node('p','conversation-notice','Use this form for advisory answers only. Never grant access or enter credentials here; stop the run if the purpose is unclear.'));
    const fields=[];requestData.questions.forEach((q,index)=>{const id=`question-${requestData.id}-${index}`,label=node('label','',q.question),input=node(q.options?.length?'select':'textarea');input.id=id;input.dataset.draftKey=`${requestData.id}:${q.id}`;input.required=true;label.htmlFor=id;
      if(q.header)card.append(node('strong','',q.header));card.append(label);
      if(q.options?.length){input.append(new Option('Choose an answer',''));q.options.forEach(o=>input.append(new Option(o.label,o.label)));if(q.is_other)input.append(new Option('Other answer','__other__'));q.options.forEach(o=>{if(o.description)card.append(node('p','field-help',`${o.label}: ${o.description}`));});}
      else{input.rows=3;input.maxLength=4000;}
      const other=node('textarea');other.rows=3;other.maxLength=4000;other.dataset.draftKey=`${requestData.id}:${q.id}:other`;other.hidden=true;other.setAttribute('aria-label',`Other answer: ${q.header||q.question}`);input.addEventListener('change',()=>{other.hidden=input.value!=='__other__';other.required=!other.hidden;other.disabled=other.hidden||requestData.status!=='pending';});
      input.disabled=requestData.status!=='pending';other.disabled=true;card.append(input,other);fields.push({question:q,input,other});
    });
    const error=node('p','form-error');error.setAttribute('role','alert');card.append(error);const send=button('Send answers',()=>{},'primary');send.type='submit';send.disabled=conversationSending||requestData.status!=='pending'||stale||state?.connection.status!=='connected';card.append(send);if(requestData.status==='unavailable'){card.append(node('p','conversation-notice','This question cannot be answered safely or is no longer live. You can stop an active run from its task details.'));const task=state.tasks.find(t=>t.id===conversationId);if(task)card.append(button('View task',()=>openTask(task.id)));}body.append(card);
    card.addEventListener('submit',async event=>{event.preventDefault();if(conversationSending||stale||state?.connection.status!=='connected'||!card.reportValidity()||send.disabled)return;const answers={};for(const f of fields){const text=(f.input.value==='__other__'?f.other.value:f.input.value).trim();if(!text){error.textContent='Answer every question with more than whitespace.';return;}answers[f.question.id]=[text];}
      conversationSending=true;send.disabled=true;fields.forEach(f=>{f.input.disabled=true;f.other.disabled=true;});error.textContent='';const sequence=conversationSequence;try{await request(`/api/questions/${encodeURIComponent(requestData.id)}/respond`,{answers});announce('Answers sent to the agent.');conversationSignature='';}catch(e){error.textContent=`${e.message} Answers were not confirmed; they will not retry automatically.`;}finally{conversationSending=false;if(sequence===conversationSequence){const savedError=error.textContent;conversationSignature='';await refresh();await loadConversation();if(savedError){const currentCard=[...$('conversation-content').querySelectorAll('.question-card')].find(c=>c.dataset.questionId===requestData.id);if(currentCard)currentCard.querySelector('.form-error').textContent=savedError;}}}
    });
  }
  function clearPreview(message='Select a file from the list. Content is scanned before it is shown.') {
    previewRequest+=1;selectedFile='';$('file-content').textContent='';$('file-lines').textContent='';$('file-meta').textContent='';$('file-preview-title').textContent='Select a file to preview';$('code-preview').hidden=true;$('file-preview-message').hidden=false;$('file-preview-message').textContent=message;
  }
  function ensureProjectViews() {
    const id=$('project-filter').value;
    if(id!==browserProject){
      browserProject=id;fileEntries=[];filesLoaded=false;filesRequest+=1;gitSnapshot=null;gitLoaded=false;gitRequest+=1;gitCheckedAt=0;
      $('file-search').value='';$('file-list').replaceChildren();$('file-browser').hidden=true;clearPreview();$('files-message').textContent='';$('git-details').replaceChildren();$('git-message').textContent='';
      if($('publish-dialog').open&&!publishing)$('publish-dialog').close();publishPreview=null;
      if($('repository-dialog').open&&!creatingRepository)$('repository-dialog').close();
    }
    $('refresh-files').disabled=!id;$('refresh-git').disabled=!id||publishing||creatingRepository;
    if(!id){$('files-message').textContent='Choose one project above to browse its files.';$('git-message').textContent='Choose one project above to inspect its Git status.';return;}
    if(view==='files'&&!filesLoaded)loadFiles();
    if(view==='git'&&!gitLoaded)loadGit();
  }
  async function loadFiles() {
    const id=$('project-filter').value;if(!id)return;
    const sequence=++filesRequest;filesLoaded=true;fileEntries=[];clearPreview();$('file-list').replaceChildren();$('file-browser').hidden=true;$('files-message').textContent='Loading project files…';$('refresh-files').disabled=true;
    try {
      const result=await request(`/api/projects/${encodeURIComponent(id)}/files`);
      if(sequence!==filesRequest||id!==$('project-filter').value)return;
      if(result.project_id!==id||!Array.isArray(result.files))throw new Error('The file list response was incomplete. Refresh to try again.');
      fileEntries=result.files.filter(f=>typeof f.path==='string');
      $('files-message').textContent=result.limit_reached?'Showing a limited file list. Some project files are omitted.':`${fileEntries.length} visible file${fileEntries.length===1?'':'s'} · ${project(id)?.name||'Selected project'}`;
      $('file-browser').hidden=!fileEntries.length;
      if(!fileEntries.length)$('files-message').textContent='No visible files. Git-ignored, credential and runtime paths are excluded.';
      renderFiles();
    } catch(error){if(sequence===filesRequest&&id===$('project-filter').value)$('files-message').textContent=`Files unavailable. ${error.message}`;}
    finally{if(sequence===filesRequest)$('refresh-files').disabled=false;}
  }
  function renderFiles() {
    const query=$('file-search').value.trim().toLocaleLowerCase(),target=$('file-list'),focusedPath=target.contains(document.activeElement)?document.activeElement.dataset.filePath:null;target.replaceChildren();
    const matches=fileEntries.filter(f=>f.path.toLocaleLowerCase().includes(query));
    if(!matches.length){target.append(node('p','file-message','No matching file paths.'));return;}
    matches.forEach(f=>{const b=button(f.path,()=>loadPreview(f.path));b.className='file-path';b.title=f.path;b.dataset.filePath=f.path;if(f.path===selectedFile){b.classList.add('selected');b.setAttribute('aria-current','true');}target.append(b);if(f.path===focusedPath)b.focus({preventScroll:true});});
  }
  async function loadPreview(path) {
    const id=$('project-filter').value;if(!id)return;
    clearPreview('Scanning and loading this file…');selectedFile=path;const sequence=previewRequest;
    $('file-preview-title').textContent=path;renderFiles();
    try{
      const result=await request(`/api/projects/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}`);
      if(sequence!==previewRequest||id!==$('project-filter').value||selectedFile!==path)return;
      if(result.project_id!==id||result.path!==path||typeof result.content!=='string')throw new Error('The preview response was incomplete. Select the file again to retry.');
      // Plain text only. File contents are never interpreted as HTML or placed in browser storage.
      $('file-content').textContent=result.content;
      const lines=result.content.length?result.content.split('\n').length:1;
      $('file-lines').textContent=Array.from({length:lines},(_,i)=>String(i+1)).join('\n');
      $('file-meta').textContent=`${number(result.size)} bytes · ${number(result.line_count)} lines`;
      $('file-preview-message').hidden=true;$('code-preview').hidden=false;
      announce(`Read-only preview loaded: ${path}`);
    }catch(error){if(sequence!==previewRequest||id!==$('project-filter').value)return;$('file-content').textContent='';$('file-lines').textContent='';$('code-preview').hidden=true;$('file-preview-message').hidden=false;$('file-preview-message').textContent=`Preview unavailable. ${error.message}`;}
  }
  async function loadGit() {
    const id=$('project-filter').value;if(!id||publishing||creatingRepository)return;
    const sequence=++gitRequest;gitLoaded=true;gitSnapshot=null;gitCheckedAt=0;$('git-details').replaceChildren();$('git-message').textContent='Checking repository status…';$('refresh-git').disabled=true;
    if($('publish-dialog').open)$('publish-dialog').close();publishPreview=null;
    try{
      const result=await request(`/api/projects/${encodeURIComponent(id)}/git`);
      if(sequence!==gitRequest||id!==$('project-filter').value)return;
      if(typeof result.is_repository!=='boolean'||!Array.isArray(result.changes))throw new Error('The Git status response was incomplete. Refresh to try again.');
      gitSnapshot=result;gitCheckedAt=Date.now();renderGit();
    }catch(error){if(sequence===gitRequest&&id===$('project-filter').value){$('git-message').textContent=`Git status unavailable. ${error.message}`;}}
    finally{if(sequence===gitRequest)$('refresh-git').disabled=false;}
  }
  function canPublish() {
    return Boolean(gitSnapshot?.is_repository&&gitSnapshot.clean===true&&gitSnapshot.can_publish===true&&gitSnapshot.head&&gitSnapshot.branch&&gitSnapshot.remote&&gitCheckedAt&&Date.now()-gitCheckedAt<60000&&!publishing);
  }
  function renderGit() {
    const target=$('git-details');target.replaceChildren();const git=gitSnapshot;if(!git)return;
    $('git-message').textContent=git.is_repository?(git.clean?'Working tree clean.':'Working tree has changes. Publishing requires a clean working tree.'):'This project is not a Git repository.';
    if(!git.is_repository){target.append(node('p','git-note',git.reason||'Register a project with an existing Git repository to use publishing.'));return;}
    const grid=node('dl','detail-grid git-summary');
    const fields=[['Project',project(browserProject)?.name||'Selected project'],['Branch',git.branch||'Detached or unavailable'],['Commit',git.head||'No commit recorded'],['Destination',git.remote||'No supported remote configured'],['Repository',git.repository||'Not configured'],['Upstream',git.upstream||'Not configured'],['Ahead / behind',`${git.ahead??'Unknown'} / ${git.behind??'Unknown'}`],['Status checked',date(git.last_checked)]];
    fields.forEach(([k,v])=>grid.append(node('dt','',k),node('dd','',String(v))));target.append(grid);
    const counts=git.counts||{},summary=node('div','git-counts');
    [['Staged',counts.staged],['Modified',counts.modified],['Untracked',counts.untracked]].forEach(([label,value])=>summary.append(node('span','badge',`${label}: ${number(value)}`)));target.append(summary);
    if(git.hidden_changes)target.append(node('p','git-note',`${number(git.hidden_changes)} additional changes have hidden paths. Sensitive paths are never displayed; hidden changes still block publishing.`));
    if(git.changes.length){const wrap=node('div','table-scroll'),table=node('table'),thead=node('thead'),head=node('tr');head.append(node('th','','STATUS'),node('th','','FILE'));thead.append(head);table.append(thead);const body=node('tbody');git.changes.forEach(change=>{const row=node('tr');row.append(node('td','git-status-code',change.status),node('td','git-change-path',change.path));body.append(row);});table.append(body);wrap.append(table);target.append(wrap);}
    const actions=node('div','git-publish-actions'),publish=button('Review publish…',openPublish,'primary');publish.id='review-publish';publish.disabled=!canPublish();
    if(git.can_create_repository===true){const create=button('Create GitHub repository…',openRepository,'secondary');create.disabled=creatingRepository||!settings||!gitCheckedAt||Date.now()-gitCheckedAt>=60000;create.id='create-repository';actions.append(create);if(git.create_repository_reason)actions.append(node('p','git-note',git.create_repository_reason));}
    const reason=node('p','git-publish-reason',git.reason||(!git.remote?'Configure a supported origin remote outside this dashboard, then refresh status.':!git.clean?'Commit or otherwise resolve your changes outside this dashboard, then refresh status.':'Review the exact destination and commit before publishing.'));reason.id='git-publish-reason';publish.setAttribute('aria-describedby',reason.id);actions.append(reason,publish);target.append(actions);
  }
  function repositoryDestination() {
    const form=$('repository-form');form.elements.confirmed.checked=false;
    $('repository-destination').textContent=`Create ${form.elements.visibility.value.toUpperCase()} repository: github.com/${form.elements.owner.value.trim()}/${form.elements.name.value.trim()}`;
  }
  function openRepository() {
    if(!settings||gitSnapshot?.can_create_repository!==true||creatingRepository||!browserProject||Date.now()-gitCheckedAt>=60000)return;
    repositoryProject=browserProject;const form=$('repository-form');form.reset();form.elements.owner.value=settings.github_username;form.elements.visibility.value=settings.github_visibility;
    form.elements.name.value=String(project(browserProject)?.name||'').replace(/[^A-Za-z0-9_.-]/g,'-').slice(0,100);
    repositoryDestination();openDialog('repository-dialog');
  }
  async function createRepository(event) {
    event.preventDefault();const form=$('repository-form'),error=form.querySelector('.form-error');
    if(creatingRepository||!form.reportValidity())return;
    if(!repositoryProject||repositoryProject!==$('project-filter').value||gitSnapshot?.can_create_repository!==true||Date.now()-gitCheckedAt>=60000){error.textContent='Refresh Git status and review repository creation again.';return;}
    const body={owner:form.elements.owner.value.trim(),name:form.elements.name.value.trim(),visibility:form.elements.visibility.value,confirmed:form.elements.confirmed.checked};
    creatingRepository=true;form.querySelectorAll('input,select,button').forEach(el=>el.disabled=true);$('project-filter').disabled=true;$('refresh-git').disabled=true;error.textContent='Creating the empty repository. Waiting for the server result…';
    try{const result=await request(`/api/projects/${encodeURIComponent(repositoryProject)}/repository`,body);if(result.created!==true)throw new Error('Creation was not confirmed. Check GitHub and refresh status before retrying.');if(result.attached!==true){error.textContent=result.warning||'The empty GitHub repository was created, but origin was not attached. Check GitHub and configure origin before any further action. Do not create another repository to retry.';announce('Repository created; origin attachment needs attention.');}else{$('repository-dialog').close();announce('Empty GitHub repository created. No commits were published.');}}
    catch(e){error.textContent=`${e.message} This action will not be retried automatically. Check GitHub and refresh status before trying again.`;}
    finally{creatingRepository=false;form.querySelectorAll('input,select,button').forEach(el=>el.disabled=false);$('project-filter').disabled=false;$('refresh-git').disabled=false;repositoryProject=null;gitCheckedAt=0;await loadGit();}
  }
  function checkGitFreshness() {
    if(!gitSnapshot||!gitCheckedAt||Date.now()-gitCheckedAt<60000)return;
    const create=$('create-repository');if(create)create.disabled=true;
    const b=$('review-publish');if(b)b.disabled=true;
    const reason=$('git-publish-reason');if(reason)reason.textContent='This Git status is stale. Refresh status before reviewing a publish.';
    if($('publish-dialog').open&&!publishing){$('confirm-publish').disabled=true;$('publish-error').textContent='This preview is stale. Cancel and refresh Git status before publishing.';}
  }
  function openPublish() {
    if(!canPublish()||!browserProject)return;
    publishPreview=Object.freeze({project_id:browserProject,head:gitSnapshot.head,branch:gitSnapshot.branch,remote:gitSnapshot.remote});
    const summary=$('publish-summary');summary.replaceChildren();
    [['Project',project(browserProject)?.name||'Selected project'],['Repository URL',publishPreview.remote],['Branch',publishPreview.branch],['Commit',publishPreview.head]].forEach(([k,v])=>summary.append(node('dt','',k),node('dd','',v)));
    $('publish-error').textContent='';$('confirm-publish').disabled=false;openDialog('publish-dialog');
  }
  async function publishCommits() {
    const preview=publishPreview;
    if(!preview||!canPublish()||preview.project_id!==$('project-filter').value){$('publish-error').textContent='Refresh Git status and review a new preview before publishing.';return;}
    publishing=true;$('confirm-publish').disabled=true;$('refresh-git').disabled=true;$('project-filter').disabled=true;$('publish-error').textContent='Publishing committed work. Waiting for the server result…';
    // Exact values captured by the confirmation, never newly inferred from a refreshed state.
    try {
      const result=await request(`/api/projects/${encodeURIComponent(preview.project_id)}/publish`,{head:preview.head,branch:preview.branch,remote:preview.remote,confirmed:true});
      if(result.published!==true)throw new Error('Publishing was not confirmed. Refresh status before taking further action.');
      $('publish-dialog').close();announce('Committed work published.');$('git-message').textContent='Committed work published. Refreshing status…';
    }catch(error){$('publish-error').textContent=`${error.message} Publishing will not be retried automatically. Cancel and refresh status to review the current repository.`;}
    finally{
      publishing=false;$('project-filter').disabled=false;$('refresh-git').disabled=false;gitCheckedAt=0;publishPreview=null;checkGitFreshness();const b=$('review-publish');if(b)b.disabled=true;
      if(!$('publish-dialog').open)await loadGit();
    }
  }
  function openDialog(id) {const dialog=$(id);dialog.returnFocus=document.activeElement;dialog.querySelectorAll('form .form-error').forEach(e=>e.textContent='');dialog.showModal();}
  function openProject(){openDialog('project-dialog');}
  function openRun(){if(stale||!state||!state.projects.length||state.connection.status!=='connected'||connectionDisabled(state.connection))return;applyProviderText();const form=$('run-form');options(form.elements.project_id,state.projects.map(p=>({id:p.id,label:p.name})));if($('project-filter').value)form.elements.project_id.value=$('project-filter').value;options(form.elements.role,state.roles);if(state.roles.some(r=>r.id===preferredRole))form.elements.role.value=preferredRole;modelHint();openDialog('run-dialog');}
  function modelHint(){const r=role($('run-form').elements.role.value);$('role-model').textContent=r?`Configured: ${r.model||'model not recorded'} · ${r.reasoning||'default'} reasoning. Actual routing may differ.`:'';}
  function openTask(id){detailId=id;detailSignature='';deliveryId=id;deliverySequence++;deliveryData=null;deliveryPlan=null;deliveryPreview=null;deliveryFresh=false;deliveryError='';renderDetail(id);openDialog('task-dialog');if(deliveryEligible(state.tasks.find(t=>t.id===id)))loadDelivery();}
  function deletionControl(task){
    const remove=button('Delete run',()=>openRunDeletion(task.id),'danger');remove.dataset.activityFocus='delete-run';
    remove.disabled=stale||task.can_delete!==true;remove.title=stale?'Refresh dashboard data before deleting.':task.deletion_blocker|| (task.can_delete!==true?'Deletion availability is not available. Refresh the dashboard.':'Delete this dashboard run and its history.');
    const group=node('div','dialog-actions');group.append(remove);
    if(remove.disabled)group.append(node('small','subtext',remove.title));return group;
  }
  function openRunDeletion(id){
    const task=state?.tasks.find(t=>t.id===id);if(stale||task?.can_delete!==true)return;
    deleteTarget=uncertainDeletions.get(id)||{id,version:task.deletion_version,uncertain:false};$('delete-run-name').textContent=`${task.title} · ${project(task.project_id)?.name||'Project'} · ${id}`;
    $('delete-run-acknowledge').checked=false;$('delete-run-error').textContent='';renderRunDeletion();openDialog('delete-run-dialog');$('delete-run-cancel').focus();
  }
  function renderRunDeletion(){
    if(!deleteTarget)return;const task=state?.tasks.find(t=>t.id===deleteTarget.id),current=task?.deletion_version===deleteTarget.version;
    $('delete-run-confirm').disabled=deleteBusy||deleteTarget.uncertain||stale||task?.can_delete!==true||!current||!$('delete-run-acknowledge').checked;
    $('delete-run-cancel').disabled=deleteBusy;$('delete-run-acknowledge').disabled=deleteBusy||deleteTarget.uncertain;
    $('delete-run-refresh').hidden=!deleteTarget.uncertain;$('delete-run-refresh').disabled=deleteBusy||refreshing;
    $('delete-run-dialog').setAttribute('aria-busy',String(deleteBusy));
    $('delete-run-status').textContent=deleteBusy?'Deleting dashboard run…':deleteTarget.uncertain?'The request result is uncertain. Check deletion status; nothing will be resent automatically.':stale?'Refresh dashboard data before deleting.':!current?'This run changed. Close and reopen Delete run to review its current state.':task?.deletion_blocker||'Confirm above to permanently delete this dashboard run.';
  }
  function restoreRunDeletionFocus(dialog){
    if(dialog.returnFocus?.isConnected!==false){dialog.returnFocus?.focus();return;}
    const id=deleteTarget?.id,parent=recoveryId===id&&$('recovery-dialog').open?$('recovery-dialog'):detailId===id&&$('task-dialog').open?$('task-dialog'):null;
    const content=parent?.id==='recovery-dialog'?$('recovery-content'):parent?$('task-detail'):null;
    const current=content?[...content.querySelectorAll('button')].find(control=>control.dataset.activityFocus==='delete-run'&&!control.disabled):null;
    (current||parent?.querySelector('[data-close]')||$('main')).focus();
  }
  function finishRunDeletion(id){
    uncertainDeletions.delete(id);
    if(detailId===id)$('task-dialog').close();
    if(recoveryId===id){recoverySequence++;recoveryId='';recoveryData=null;recoveryFresh=false;recoveryDrafts.delete(id);$('recovery-dialog').close();}
    if(conversationId===id){conversationSequence++;conversationId='';conversationData=null;conversationSignature='';$('conversation-task').value='';$('conversation-content').replaceChildren();}
    deliveryPending.delete(id);deliveryParents.delete(id);attentionDismissals.delete(id);
    for(const [key,value] of deliveryParents)if(value===id)deliveryParents.delete(key);
    if(failureNoticeId===id)failureNoticeId=null;if(submittedTaskId===id)submittedTaskId=null;
    if(approvalReview?.task_id===id)$('approval-review-dialog').close();
    for(const [key,value] of approvalContinuations)if(value.task_id===id)approvalContinuations.delete(key);
    $('delete-run-dialog').close();deleteTarget=null;teamLoaded=false;teamRenderSignature='';
    announce('Run deleted from the dashboard. Project files and Codex native history are unchanged.');$('main').focus();
  }
  async function confirmRunDeletion(){
    if(!deleteTarget||$('delete-run-confirm').disabled)return;const target=deleteTarget;deleteBusy=true;renderRunDeletion();$('delete-run-error').textContent='';
    try{
      const result=await request(`/api/tasks/${encodeURIComponent(target.id)}/delete`,{expected_version:target.version,confirmed:true});
      if(result?.task_id!==target.id||result.deleted!==true)throw new Error('Deletion was not confirmed by the server.');
      state.tasks=state.tasks.filter(t=>t.id!==target.id);state.approvals=state.approvals.filter(a=>a.task_id!==target.id);state.delegated_activities=(state.delegated_activities||[]).filter(a=>a.parent_task_id!==target.id);
      finishRunDeletion(target.id);render();await refresh();if(view==='team')await loadTeam();
    }catch(error){if(deleteTarget===target){target.uncertain=!error.status||error.status>=500;if(target.uncertain)uncertainDeletions.set(target.id,target);$('delete-run-error').textContent=error.message;}}
    finally{deleteBusy=false;if(deleteTarget===target)renderRunDeletion();}
  }
  function renderDiagnostics(target,task){
    const entries=Array.isArray(task.diagnostics)?task.diagnostics:[],latest=entries.at(-1);
    if(task.status==='failed'){
      const summary=node('section','failure-summary');summary.append(node('h3','','Run failed'),node('p','',latest?.message||task.error||'No detailed failure category was recorded for this older run.'));
      if(latest?.action)summary.append(node('strong','','What to do next'),node('p','',latest.action));
      summary.append(node('p','subtext','This run will not retry automatically. Review the issue before starting another run.'));target.append(summary);
    }else if(task.error)target.append(node('p','form-error',task.error));
    const section=node('section','detail-section');section.append(node('h3','','Run diagnostics'));
    if(entries.length){
      const stages={model_check:'Model availability',thread_start:'Create Codex thread',safety_check:'Sandbox and approval checks',turn_start:'Start model turn',execution:'Model execution',transport:'App Server connection'};
      const timeline=node('ol','diagnostic-timeline');entries.forEach(entry=>{
        const item=node('li');item.append(node('strong','',stages[entry.stage]||'Run checkpoint'),node('small','subtext',`${date(entry.at)}${entry.code?' · '+entry.code:''}`),node('p','',entry.message||'Checkpoint recorded.'));
        if(entry.action)item.append(node('p','diagnostic-action',`Next step: ${entry.action}`));timeline.append(item);
      });section.append(timeline);
    }else section.append(node('p','','No diagnostic checkpoints were recorded for this run. Older records may contain only a general error.'));
    section.append(node('p','subtext','Diagnostics contain safe runtime categories. Raw RPC traffic, credentials, tool output and reasoning are withheld.'));target.append(section);
  }
  function renderDelegatedActivities(target,task,activities) {
    const section=node('section','detail-section delegated-section');section.append(node('h3','','Delegated activity'));
    section.append(node('p','subtext','Observed specialist work under this coordinating task. Delegated usage is not included in the main-thread cost estimate.'));
    if(!activities.length)section.append(node('p','','No delegated activity has been observed for this task.'));
    else {
      section.append(node('p','',`${activities.length} activities · ${activitySummary(activities)}`));
      const byThread=new Map(activities.filter(a=>a.thread_id).map(a=>[a.thread_id,a])),children=new Map();
      activities.forEach(a=>{const parent=byThread.has(a.parent_thread_id)&&a.parent_thread_id!==a.thread_id?a.parent_thread_id:null;if(!children.has(parent))children.set(parent,[]);children.get(parent).push(a);});
      const seen=new Set();
      function appendActivity(a,list){
        if(seen.has(a.id))return;seen.add(a.id);
        const item=node('li','delegated-activity'),heading=node('div','activity-heading');heading.append(node('strong','',a.title),badge(a.status));item.append(heading,node('p','',role(a.role)?.label||a.role||'Role not recorded'),node('small','subtext',`Created ${date(a.created_at)} · Updated ${date(a.updated_at)}`));
        const parent=byThread.get(a.parent_thread_id),parentLabel=parent?(role(parent.role)?.label||parent.role||'Role not recorded'):a.parent_thread_id&&a.parent_thread_id===task.thread_id?(role(task.role)?.label||task.role):'Parent agent not recorded';item.append(node('small','subtext',`Delegated by: ${parentLabel}`));
        const nested=node('ul','delegated-list');(a.thread_id?children.get(a.thread_id)||[]:[]).forEach(child=>appendActivity(child,nested));if(nested.children.length)item.append(nested);list.append(item);
      }
      const list=node('ul','delegated-list');(children.get(null)||[]).forEach(a=>appendActivity(a,list));
      // Keep orphaned or cyclic lineage visible without recursing indefinitely.
      activities.forEach(a=>appendActivity(a,list));section.append(list);
      const conversation=button('Open coordinating conversation',()=>{openConversation(task.id);$('task-dialog').close();});conversation.dataset.activityFocus='delegated-conversation';section.append(conversation);
    }
    target.append(section);
  }
  function openOutputs(id){
    const task=state?.tasks.find(t=>t.id===id);if(!task)return;
    ++outputsSequence;const target=$('outputs-content');target.replaceChildren();
    $('outputs-title').textContent=`Outputs · ${task.title}`;$('outputs-dialog').dataset.taskId=id;
    target.append(node('p','subtext',`${project(task.project_id)?.name||'Unknown project'} · Output availability does not establish delivery acceptance or release approval.`));
    const preview=node('section','detail-section'),status=node('p','conversation-notice'),content=node('pre','approval-review-context');status.setAttribute('role','status');content.tabIndex=0;content.hidden=true;content.setAttribute('aria-label','Checked report content');preview.append(status,content);
    async function inspect(output){
      const current=++outputsSequence;status.textContent='Checking report…';content.textContent='';content.hidden=true;
      try{const result=await request(`/api/tasks/${encodeURIComponent(id)}/outputs/${encodeURIComponent(output.id)}`);
        if(current!==outputsSequence||!$('outputs-dialog').open)return;
        if(result.task_id!==id||result.id!==output.id)throw new Error('The report response did not match this task.');
        if(result.state==='changed'){status.textContent='This report changed since it was associated. Its content is withheld. Review the current file in Files before explicitly associating it again.';return;}
        if(result.state!=='available'||typeof result.content!=='string')throw new Error('The report is unavailable for checked preview.');
        status.textContent=`${result.title||output.title} · ${result.path||output.path} · ${result.line_count} lines. Checked preview; no delivery acceptance is implied.`;content.textContent=result.content;content.hidden=false;
      }catch(error){if(current===outputsSequence&&$('outputs-dialog').open)status.textContent=`${error.outputState==='missing'?'Report missing':error.outputState==='blocked'?'Report blocked':'Report checks unavailable'}. ${error.message} No content was shown. You can select the report again to recheck.`;}
    }
    if(!task.outputs?.length)target.append(node('p','conversation-notice','No output recorded. Paths mentioned in conversation are not verified outputs.'));
    (task.outputs||[]).forEach(output=>{const item=node('article','approval-card');item.append(node('h3','',output.title||'Report'),node('p','subtext',output.path),button('Open report',()=>inspect(output)));target.append(item);});
    if(task.can_attach_output===true){
      const form=node('form','conversation-composer'),label=node('label','','Associate an existing report'),path=node('input');path.id='output-report-path';path.required=true;path.maxLength=4096;path.placeholder='Project-relative report path';label.htmlFor=path.id;
      const confirmLabel=node('label','confirmation-label'),confirmation=node('input');confirmation.type='checkbox';confirmation.required=true;confirmLabel.append(confirmation,node('span','','I confirm this existing report is an output of this task. Association does not accept delivery.'));
      const error=node('p','form-error');error.setAttribute('role','alert');const submit=button('Associate report',()=>{});submit.type='submit';submit.disabled=stale;
      form.append(label,path,confirmLabel,node('p','field-help','Only an explicitly selected, checked text file within this project can be associated. No paths are inferred from conversation.'),error,submit);target.append(form);
      form.addEventListener('submit',async event=>{event.preventDefault();if(stale||submit.disabled||!form.reportValidity()||!confirmation.checked||!path.value.trim())return;const current=++outputsSequence;submit.disabled=true;error.textContent='';status.textContent='Checking and associating the selected report…';
        try{const result=await request(`/api/tasks/${encodeURIComponent(id)}/outputs`,{path:path.value.trim(),expected_turn_id:task.turn_id??null,confirmed:true});if(current!==outputsSequence||!$('outputs-dialog').open)return;if(result.task_id!==id||!result.output?.id)throw new Error('Report association was not confirmed.');task.outputs=[...(task.outputs||[]).filter(o=>o.path!==result.output.path),result.output];detailSignature='';openOutputs(id);$('outputs-content').querySelector('button')?.focus({preventScroll:true});announce('Report associated with this task. Delivery acceptance is unchanged.');await refresh();}
        catch(failure){if(current===outputsSequence){status.textContent='';error.textContent=`${failure.message} Association was not confirmed. Nothing retries automatically; refresh to check before retrying.`;submit.disabled=stale;}}
      });
    }
    target.append(preview);if(!$('outputs-dialog').open)openDialog('outputs-dialog');
  }
  function renderDetail(id){
    const t=state.tasks.find(x=>x.id===id),target=$('task-detail');
    const activities=t?delegatedFor(t):[],signature=JSON.stringify([t,activities,state.connection.status,stale,providerKey()]);if(signature===detailSignature)return;detailSignature=signature;
    const focusKey=target.contains(document.activeElement)?document.activeElement?.dataset.activityFocus:null;
    const restoreStop=target.contains(document.activeElement)&&document.activeElement?.dataset.liveAction;
    target.replaceChildren();if(!t){target.append(node('p','','This task is no longer available.'));return;}
    $('task-dialog-title').textContent=t.title;target.append(badge(t.status));const grid=node('dl','detail-grid');
    renderDiagnostics(target,t);
    if(t.active_children>0)target.append(node('p','conversation-notice',`${t.active_children} child agent(s) are still active. The project remains reserved until they stop.`));
    const fields=[['Project',project(t.project_id)?.name||'Unknown'],['Agent',role(t.role)?.label||t.role],['Configured model',t.model||'Not recorded'],['Reasoning',t.reasoning||'Not recorded'],['Created',date(t.created_at)],['Updated',date(t.updated_at)],['Thread',t.thread_id||'Not observed'],['Turn',t.turn_id||'Not observed']];if(t.provider&&t.provider!=='codex')fields.splice(1,0,['Provider',providerLabel(t.provider)]);fields.forEach(([k,v])=>grid.append(node('dt','',k),node('dd','',v)));target.append(grid);
    const conversation=button('Open conversation',()=>{openConversation(t.id);$('task-dialog').close();});conversation.dataset.activityFocus='conversation';target.append(conversation);
    const deliveryParent=deliveryParents.get(t.id);if(deliveryParent&&state.tasks.some(task=>task.id===deliveryParent)){const back=button('Back to delivery review',()=>openTask(deliveryParent));back.dataset.activityFocus='delivery-parent';target.append(back);}
    if(t.recovery_available===true&&!providerOff('recovery')){const recover=button('Recover task',()=>{ $('task-dialog').close();openRecovery(t.id);});recover.dataset.activityFocus='recovery';target.append(recover);}
    target.append(deletionControl(t));
    if(t.status==='completed'||t.outputs?.length){const outputs=node('section','detail-section');outputs.append(node('h3','','Outputs'),node('p','subtext',t.outputs?.length?t.outputs.map(o=>`${o.title} · ${o.path}`).join('\n'):'No report is associated with this task.'));const open=button('Open task outputs',()=>openOutputs(t.id));open.dataset.outputsTask=t.id;outputs.append(open);target.append(outputs);}
    if(stale)target.append(node('p','conversation-notice','Showing the last received activity. Status may be stale.'));
    renderDelegatedActivities(target,t,activities);
    if(deliveryEligible(t)){const section=node('section','detail-section delivery-section');section.id='delivery-content';section.setAttribute('aria-labelledby','delivery-heading');target.append(section);renderDelivery();}
    if(t.blocker)target.append(node('p','form-error',`Blocker: ${t.blocker}`));
    const plan=node('section','detail-section');plan.append(node('h3','','Live plan'));if(t.plan?.length){const list=node('ol','plan');t.plan.forEach(s=>{const item=node('li','',s.step);item.append(node('span','subtext',s.status||'Status not recorded'));list.append(item);});plan.append(list);}else plan.append(node('p','','No plan steps have been reported by Codex.'));target.append(plan);
    plan.append(node('p','subtext','Plan labels are withheld to keep model-authored content out of the dashboard. Step counts and statuses are live.'));
    const usage=node('section','detail-section');usage.append(node('h3','','Execution evidence'));usage.append(node('p','',t.usage?`Observed tokens: ${number(t.usage.total_tokens)} total; ${number(t.usage.input_tokens)} input, ${number(t.usage.cached_input_tokens)} cached input, ${number(t.usage.output_tokens)} output. Reasoning output: ${number(t.usage.reasoning_output_tokens)}.`:'Usage has not been observed. Cost remains unknown without a supported model and pricing basis.'));usage.append(node('p','','A completed turn does not establish acceptance, passing tests or release approval. Delivery checks and independent review are recorded separately where enforced.'));target.append(usage);
    if(active.has(t.status)||t.active_children>0){const actions=node('div','dialog-actions'),stop=button(t.active_children>0?'Stop active agents':'Stop run',()=>interrupt(t,stop),'danger');stop.dataset.liveAction='true';stop.disabled=state.connection.status!=='connected'&&t.task_purpose!=='recovery_assessment';actions.append(stop);target.append(actions);if(restoreStop&&!stop.disabled)stop.focus();}
    if(focusKey)[...target.querySelectorAll('button')].find(b=>b.dataset.activityFocus===focusKey)?.focus();
  }

  const deliveryLabels={not_enforced:'Not enforced for this run',awaiting_checks:'Awaiting checks',checks_running:'Checks running',checks_failed:'Checks need attention',awaiting_review:'Awaiting independent review',review_running:'Independent review running',changes_requested:'Changes requested',ready:'Ready for delivery',stale:'Evidence needs refreshing',unverified:'Delivery not verified'};
  function deliveryEligible(task){return !!task&&(task.delivery_available===true||!task.delivery_subject&&['backend_developer','frontend_developer'].includes(task.role)||task.delivery&&task.delivery.status!=='not_enforced');}
  function deliveryDraft(){const projectId=state?.tasks.find(t=>t.id===deliveryId)?.project_id||deliveryId;if(!deliveryDrafts.has(projectId))deliveryDrafts.set(projectId,{text:'',initialized:false,dirty:false,planConfirmed:false,runConfirmed:false});return deliveryDrafts.get(projectId);}
  function deliveryValid(data){const digest=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);return data&&data.task_id===deliveryId&&Object.hasOwn(deliveryLabels,data.status)&&data.actions&&['run_checks','start_review','review_decision'].every(key=>typeof data.actions[key]==='boolean')&&Number.isInteger(data.plan_version)&&data.plan_version>=0&&Array.isArray(data.reason_codes)&&data.reason_codes.every(reason=>typeof reason==='string')&&(!Object.values(data.actions).some(value=>value===true)||digest(data.snapshot_digest)&&digest(data.policy_digest));}
  function deliveryPlanValid(plan,projectId){return plan&&plan.project_id===projectId&&Number.isInteger(plan.version)&&Array.isArray(plan.commands)&&plan.commands.length<=8&&plan.commands.every(c=>c&&typeof c.command==='string'&&typeof c.id==='string');}
  function deliveryContextReady(){return deliveryFresh&&!stale&&state?.connection.status==='connected'&&!deliveryBusy&&Date.now()-deliveryCheckedAt<60000;}
  function deliveryReady(){return deliveryContextReady()&&!deliveryPending.has(deliveryId);}
  function deliveryCommands(){return deliveryDraft().text.split('\n').filter(value=>value.trim());}
  function deliveryReconcile(){
    const pending=deliveryPending.get(deliveryId);if(!pending)return;
    const operation=pending.kind==='checks'?deliveryData.check_operation:pending.kind==='reviews'?deliveryData.review_operation:null;
    const planMatched=pending.kind==='plan'&&deliveryPlan.version>pending.body.expected_version&&JSON.stringify(deliveryPlan.commands.map(c=>c.command))===JSON.stringify(pending.body.commands);
    const decisionAck=deliveryData.review_operation?.decision_ack;
    const decisionMatched=pending.kind==='decision'&&deliveryData.review_operation?.id===pending.body.review_id&&decisionAck&&['decision','receipt_id','review_digest','expected_snapshot'].every(key=>decisionAck[key]===pending.body[key]);
    if(operation&&operation.id===pending.body.operation_id||planMatched||decisionMatched){deliveryPending.delete(deliveryId);deliveryError='';if(planMatched){const draft=deliveryDraft();draft.dirty=false;draft.planConfirmed=false;}announce('Delivery request reconciled with the current server record.');}
  }
  async function loadDelivery(){
    const id=deliveryId,sequence=deliverySequence,task=state?.tasks.find(t=>t.id===id);if(!id||!deliveryEligible(task)||deliveryBusy)return;
    deliveryBusy=true;if(!deliveryData)renderDelivery();
    try{
      const [data,plan]=await Promise.all([request(`/api/tasks/${encodeURIComponent(id)}/delivery`),request(`/api/projects/${encodeURIComponent(task.project_id)}/check-plan`)]);
      if(sequence!==deliverySequence||id!==deliveryId)return;
      if(!deliveryValid(data)||!deliveryPlanValid(plan,task.project_id))throw new Error('Delivery verification response was incomplete.');
      const changed=deliveryData&&(deliveryData.snapshot_digest!==data.snapshot_digest||deliveryData.policy_digest!==data.policy_digest||deliveryData.plan_version!==data.plan_version||deliveryData.review_operation?.id!==data.review_operation?.id);
      if(changed){deliveryPreview=null;deliveryPreviewAt=0;deliveryDraft().runConfirmed=false;}
      deliveryData=data;deliveryPlan=plan;deliveryFresh=true;deliveryCheckedAt=Date.now();
      const draft=deliveryDraft();if(!draft.initialized||!draft.dirty){draft.text=plan.commands.map(c=>c.command).join('\n');draft.initialized=true;draft.dirty=false;}
      deliveryReconcile();
    }catch(error){if(sequence===deliverySequence&&id===deliveryId){deliveryFresh=false;deliveryPreview=null;deliveryError=`${error.message} Refresh delivery status to restore actions; unsaved checks remain here.`;}}
    finally{deliveryBusy=false;if(sequence===deliverySequence&&id===deliveryId)renderDelivery();}
  }
  async function deliveryAction(kind,path,body){
    if(!deliveryReady()||kind!=='plan'&&deliveryDraft().dirty||kind==='checks'&&deliveryData.actions.run_checks!==true||kind==='reviews'&&deliveryData.actions.start_review!==true||kind==='decision'&&deliveryData.actions.review_decision!==true)return;
    const frozen=Object.freeze({...body,...(Array.isArray(body.commands)?{commands:Object.freeze([...body.commands])}:{})}),pending={kind,path,body:frozen};
    deliveryPending.set(deliveryId,pending);await sendDeliveryRequest(pending);
  }
  async function retryDeliveryRequest(){
    const pending=deliveryPending.get(deliveryId);if(!pending||!deliveryContextReady())return;
    await sendDeliveryRequest(pending);
  }
  async function sendDeliveryRequest(pending){
    const id=deliveryId,sequence=deliverySequence,{kind,path,body}=pending;if(deliveryPending.get(id)!==pending)return;
    deliveryBusy=true;deliveryFresh=false;deliveryPreview=null;deliveryError='';renderDelivery();
    try{
      await request(path,body);
      if(sequence!==deliverySequence||id!==deliveryId)return;
      deliveryPending.delete(id);if(kind==='plan'){deliveryDraft().dirty=false;deliveryDraft().planConfirmed=false;}deliveryDraft().runConfirmed=false;
      announce(kind==='decision'?'Review decision recorded.':'Delivery request recorded. Check its observed progress below.');
    }catch(error){if(sequence===deliverySequence&&id===deliveryId){if(error.not_started===true||error.status&&error.status<500){deliveryPending.delete(id);deliveryDraft().runConfirmed=false;deliveryDraft().planConfirmed=false;}deliveryError=deliveryPending.has(id)?`${error.message} The request result is uncertain. Refresh to reconcile it, or explicitly retry only the original request. Nothing is retried automatically.`:error.message;}}
    finally{deliveryBusy=false;if(sequence===deliverySequence&&id===deliveryId){await loadDelivery();if(deliveryPending.has(id)){deliveryError='The request result is still uncertain. Refresh to reconcile it, or explicitly retry the original request. Do not start a different request.';renderDelivery();}}}
  }
  async function previewDeliveryReview(){
    if(!deliveryReady()||!deliveryData.actions.review_decision||!deliveryData.review_operation)return;
    const id=deliveryId,sequence=deliverySequence,reviewId=deliveryData.review_operation.id,snapshot=deliveryData.snapshot_digest;deliveryBusy=true;deliveryPreview=null;deliveryError='';renderDelivery();
    try{
      const preview=await request(`/api/tasks/${encodeURIComponent(id)}/delivery/reviews/${encodeURIComponent(reviewId)}`);
      if(sequence!==deliverySequence||id!==deliveryId)return;
      if(preview.review_id!==reviewId||preview.snapshot_digest!==snapshot||preview.current!==true||typeof preview.receipt_id!=='string'||typeof preview.review_digest!=='string'||!Array.isArray(preview.messages)||!preview.messages.length||!preview.messages.every(m=>m&&typeof m.text==='string'))throw new Error('The current independent review could not be verified.');
      deliveryPreview=preview;deliveryPreviewAt=Date.now();
    }catch(error){if(sequence===deliverySequence&&id===deliveryId)deliveryError=error.message;}
    finally{deliveryBusy=false;if(sequence===deliverySequence&&id===deliveryId)renderDelivery();}
  }
  function renderDelivery(){
    const target=$('delivery-content');if(!target||!deliveryId)return;
    const focused=target.contains(document.activeElement)?document.activeElement:null,key=focused?.dataset.deliveryFocus,start=focused?.selectionStart,end=focused?.selectionEnd,direction=focused?.selectionDirection;
    target.replaceChildren();const heading=node('h3','','Delivery readiness');heading.id='delivery-heading';heading.tabIndex=-1;target.append(heading,node('p','subtext','The agent’s execution status and delivery readiness are separate. Opening this panel starts no work.'));
    if(!deliveryData){target.append(node('p','',deliveryBusy?'Loading delivery verification…':'Delivery verification has not loaded.'));const retry=button('Refresh delivery status',()=>{deliveryError='';loadDelivery();});retry.disabled=deliveryBusy;target.append(retry);if(deliveryError)target.append(node('p','form-error',deliveryError));return;}
    const data=deliveryData,draft=deliveryDraft(),ready=deliveryReady(),pending=deliveryPending.get(deliveryId),dirty=draft.dirty;
    target.append(node('strong','delivery-status',deliveryLabels[data.status]||'Delivery not verified'));
    if(data.status==='not_enforced')target.append(node('p','conversation-notice','This run has no enforced delivery evidence. A new managed implementation run must pass the launch policy before it can earn delivery readiness.'));
    const refresh=button('Refresh delivery status',()=>{deliveryError='';loadDelivery();});refresh.dataset.deliveryFocus='refresh';refresh.disabled=deliveryBusy;target.append(refresh);
    if(!deliveryFresh||stale)target.append(node('p','conversation-notice','Delivery evidence is unavailable or stale. Refresh before taking an action.'));
    if(pending){const notice=node('p','conversation-notice','A request is awaiting reconciliation. Retry resends only the original unchanged request. Recorded runs are not started twice; stale approvals may be rejected. Nothing retries automatically.');notice.id='delivery-retry-help';const retry=button('Retry original request',retryDeliveryRequest);retry.dataset.deliveryFocus='retry-original';retry.setAttribute('aria-describedby','delivery-retry-help');retry.disabled=!deliveryContextReady();target.append(notice,retry);}
    if(deliveryError){const error=node('p','form-error',deliveryError);error.setAttribute('role','alert');target.append(error);}
    if(data.reason_codes.length){const reasons=node('ul','delivery-reasons');data.reason_codes.forEach(reason=>reasons.append(node('li','',String(reason).replaceAll('_',' '))));target.append(reasons);}
    const plan=node('section','delivery-check-plan');plan.append(node('h4','','Approved project checks'),node('p','subtext','Enter one exact check command per line, up to eight. Approval saves this project’s check plan; it does not execute commands. Checks run through Codex with its existing sandbox and approval rules.'));
    const label=node('label','','Check commands'),field=node('textarea');field.rows=4;field.value=draft.text;field.dataset.deliveryFocus='commands';field.setAttribute('aria-label','Project check commands');field.disabled=deliveryBusy||!!pending;
    field.addEventListener('input',()=>{draft.text=field.value;draft.dirty=true;draft.planConfirmed=false;deliveryPreview=null;deliveryPreviewAt=0;renderDelivery();});label.append(field);plan.append(label);
    const approvalLabel=node('label','delivery-confirm'),approval=node('input');approval.type='checkbox';approval.checked=draft.planConfirmed;approval.dataset.deliveryFocus='approve-plan';approval.disabled=deliveryBusy||!!pending;approval.addEventListener('change',()=>{draft.planConfirmed=approval.checked;renderDelivery();});approvalLabel.append(approval,node('span','','I approve these exact checks for this project.'));plan.append(approvalLabel);
    const save=button('Save approved checks',()=>{const commands=deliveryCommands();if(!commands.length||commands.length>8||commands.some(c=>c.length>2000)){deliveryError='Enter between one and eight commands, each no more than 2,000 characters.';renderDelivery();return;}const task=state.tasks.find(t=>t.id===deliveryId);deliveryAction('plan',`/api/projects/${encodeURIComponent(task.project_id)}/check-plan`,{expected_version:deliveryPlan.version,commands,confirmed:true});});save.dataset.deliveryFocus='save-plan';save.disabled=!ready||!draft.planConfirmed||!draft.text.trim();plan.append(save);
    if(dirty){const discard=button('Use saved checks',()=>{draft.text=deliveryPlan.commands.map(c=>c.command).join('\n');draft.dirty=false;draft.planConfirmed=false;renderDelivery();});discard.disabled=deliveryBusy||!!pending;plan.append(discard,node('p','conversation-notice','Save or discard the edited plan before running checks or reviewing delivery.'));}target.append(plan);
    const runLabel=node('label','delivery-confirm'),runApproval=node('input');runApproval.type='checkbox';runApproval.checked=draft.runConfirmed;runApproval.disabled=!ready||dirty;runApproval.dataset.deliveryFocus='confirm-run';runApproval.addEventListener('change',()=>{draft.runConfirmed=runApproval.checked;renderDelivery();});runLabel.append(runApproval,node('span','','I understand that starting checks or review can consume workspace usage and request native approvals.'));target.append(runLabel);
    const actions=node('div','dialog-actions'),checks=button('Run approved checks',()=>deliveryAction('checks',`/api/tasks/${encodeURIComponent(deliveryId)}/delivery/checks`,{expected_snapshot:data.snapshot_digest,expected_plan_version:data.plan_version,operation_id:crypto.randomUUID().replaceAll('-',''),confirmed:true}),'primary');checks.dataset.deliveryFocus='run-checks';checks.disabled=!ready||dirty||!draft.runConfirmed||data.actions.run_checks!==true;actions.append(checks);
    const review=button('Start independent review',()=>deliveryAction('reviews',`/api/tasks/${encodeURIComponent(deliveryId)}/delivery/reviews`,{expected_snapshot:data.snapshot_digest,check_operation_id:data.check_operation?.id,operation_id:crypto.randomUUID().replaceAll('-',''),confirmed:true}));review.dataset.deliveryFocus='start-review';review.disabled=!ready||dirty||!draft.runConfirmed||data.actions.start_review!==true;actions.append(review);target.append(actions);
    for(const [kind,operation] of [['Checks',data.check_operation],['Independent review',data.review_operation]])if(operation){const progress=node('div','delivery-operation');progress.append(node('strong','',kind),node('p','',`Recorded operation: ${operation.status||'Awaiting observation'}`));if(kind==='Checks')progress.append(node('p','',`${number(operation.passed_checks)} of ${number(operation.required_checks)} approved checks observed passing.`));if(operation.task_id){deliveryParents.set(operation.task_id,deliveryId);const open=button(`Open ${kind==='Checks'?'checks':'review'} conversation`,()=>{openConversation(operation.task_id);$('task-dialog').close();});open.dataset.deliveryFocus=`open-${kind}`;progress.append(open);}target.append(progress);}
    if(data.actions.review_decision){const preview=button('Read independent review',previewDeliveryReview);preview.dataset.deliveryFocus='preview-review';preview.disabled=!ready||dirty;target.append(preview);}
    if(deliveryPreview){const preview=node('section','delivery-review-preview');preview.append(node('h4','','Independent review for these changes'));deliveryPreview.messages.forEach(message=>preview.append(node('p','delivery-review-message',message.text)));const current=ready&&!dirty&&data.actions.review_decision===true&&deliveryPreview.review_id===data.review_operation?.id&&deliveryPreview.snapshot_digest===data.snapshot_digest&&Date.now()-deliveryPreviewAt<60000;
      for(const [decision,text] of [['accept','Accept review and mark delivery ready'],['reject','Request changes']]){const control=button(text,()=>{const receipt=deliveryPreview;if(!receipt)return;deliveryAction('decision',`/api/tasks/${encodeURIComponent(deliveryId)}/delivery/review-decision`,{review_id:receipt.review_id,receipt_id:receipt.receipt_id,review_digest:receipt.review_digest,expected_snapshot:receipt.snapshot_digest,decision,confirmed:true});},decision==='accept'?'primary':'secondary');control.dataset.deliveryFocus=`decision-${decision}`;control.disabled=!current;preview.append(control);}if(!current)preview.append(node('p','conversation-notice','This review preview is stale. Refresh delivery status and read the current review again.'));target.append(preview);}
    target.append(node('p','subtext','Ready for delivery means current approved checks and an independently reviewed decision are recorded. It does not publish, deploy or grant native approvals.'));
    if(key){const replacement=[...target.querySelectorAll('button,input,textarea')].find(control=>control.dataset.deliveryFocus===key&&!control.disabled);(replacement||heading).focus();if(replacement&&Number.isInteger(start)&&typeof replacement.setSelectionRange==='function')replacement.setSelectionRange(start,end,direction);}
  }

  // Recovery authority is supplied by short-lived server receipts; browser state only
  // retains drafts and operation IDs. Opening, refreshing and closing never dispatch work.
  function recoveryDraft() {
    if(!recoveryDrafts.has(recoveryId))recoveryDrafts.set(recoveryId,{question:'What can we verify about this task, what is still uncertain, and what should happen next?',followup:'',instruction:'',note:'',disposition:'needs_investigation',role:'chief_of_staff',strategy:'new_linked',selected:new Set(),dirty:false,previewed:false,handoffReply:'',handoffReplyDirty:false,handoffPacketDirty:false});
    return recoveryDrafts.get(recoveryId);
  }
  function recoveryOperation(kind) {
    const key=`${recoveryId}:${kind}`;
    if(!recoveryOperations.has(key))recoveryOperations.set(key,crypto.randomUUID().replaceAll('-',''));
    return recoveryOperations.get(key);
  }
  async function openRecovery(id) {
    recoveryId=id;recoverySequence++;recoveryData=null;recoveryEvidence=[];recoveryChat=null;recoveryHandoff=null;recoveryFresh=false;
    $('recovery-error').textContent='';$('recovery-content').replaceChildren();
    $('recovery-status').textContent='Checking recorded task and current runtime status. No agent work is starting.';
    $('recovery-dialog').returnFocus=document.activeElement;$('recovery-dialog').showModal();$('recovery-title').focus();
    await loadRecovery();
    if(recoveryId===id&&recoveryData?.actions.check&&recoveryFresh)await recoveryAction('check',{expected_revision:recoveryData.revision});
  }
  async function loadRecovery() {
    if(recoveryBusy||!recoveryId)return;
    const id=recoveryId,sequence=recoverySequence;recoveryBusy=true;
    loadRecoveryAuth(sequence);
    try {
      const result=await request(`/api/tasks/${encodeURIComponent(id)}/recovery`);
      if(sequence!==recoverySequence)return;
      if(result.task_id!==id||!result.actions||!result.capabilities)throw new Error('Recovery response is incomplete.');
      recoveryData=result;recoveryFresh=true;
      try {const history=await request(`/api/tasks/${encodeURIComponent(id)}/conversation`);if(sequence!==recoverySequence)return;recoveryEvidence=Array.isArray(history.messages)?history.messages:[];}catch {recoveryEvidence=[];}
      recoveryChat=null;
      if(result.assessment?.task_id&&result.assessment.source!=='handoff'){try {const chat=await request(`/api/tasks/${encodeURIComponent(result.assessment.task_id)}/conversation`);if(sequence!==recoverySequence)return;recoveryChat=chat;}catch {/* Retain the assessment link and show its unavailable history. */}}
      recoveryHandoff=null;
      if(result.handoff?.id){try {
        const packet=await request(`/api/tasks/${encodeURIComponent(id)}/recovery/handoffs/${encodeURIComponent(result.handoff.id)}`);
        if(sequence!==recoverySequence)return;
        if(packet.task_id!==id||packet.handoff_id!==result.handoff.id||packet.version!==result.handoff.version||typeof packet.packet_text!=='string')throw new Error('Handoff preview is incomplete.');
        recoveryHandoff=packet;recoveryHandoffCheckedAt=Date.now();
      }catch {if(sequence===recoverySequence)$('recovery-error').textContent='The checked handoff preview is unavailable. Your drafts remain here. Refresh checks before copying or accepting a return.';}}
    }catch(error){if(sequence===recoverySequence){recoveryFresh=false;$('recovery-error').textContent=`${error.message} Drafts are retained. Refresh checks before taking action.`;renderRecovery();}}
    finally{recoveryBusy=false;if(sequence===recoverySequence)renderRecovery();else if($('recovery-dialog').open)loadRecovery();}
  }
  async function loadRecoveryAuth(sequence=recoverySequence) {
    if(recoveryAuthBusy)return;
    try {
      const result=await request('/api/recovery-auth');
      if(sequence!==recoverySequence)return;
      if(!['signed_out','signing_in','authenticated','plan_unavailable','error','dependency_unavailable'].includes(result.state)||typeof result.authenticated!=='boolean'||typeof result.plan_enabled!=='boolean')throw new Error('Sign-in status is unavailable.');
      recoveryAuth=result;if(result.state!=='signing_in')recoveryAuthUrl=null;
      if($('recovery-dialog').open&&!recoveryBusy)renderRecovery();
    }catch {if(sequence===recoverySequence){recoveryAuth=null;if($('recovery-dialog').open&&!recoveryBusy)renderRecovery();}}
  }
  async function recoveryAuthAction(action) {
    if(recoveryAuthBusy)return;
    const sequence=recoverySequence;recoveryAuthBusy=true;recoveryAuthUrl=null;renderRecovery();
    try {
      const result=await request(`/api/recovery-auth/${action}`,{});
      if(sequence!==recoverySequence)return;
      if(action==='start'){
        const address=new URL(result.authorization_url);
        if(address.origin!=='https://auth.openai.com'||address.pathname!=='/api/accounts/authorize'||address.username||address.password||address.hash)throw new Error('Unsupported sign-in destination.');
        recoveryAuthUrl=address.href;
      }
    }catch(error){if(sequence===recoverySequence)$('recovery-error').textContent=`${error.message} Sign-in was not confirmed. No assessment was started.`;}
    finally{recoveryAuthBusy=false;if(sequence===recoverySequence){await loadRecoveryAuth(sequence);if(recoveryAuthUrl)renderRecovery();await loadRecovery();}}
  }
  async function recoveryAction(path,body,{operationKind=null}={}) {
    if(recoveryBusy||!recoveryFresh)return;
    const id=recoveryId,sequence=recoverySequence;recoveryBusy=true;recoveryFresh=false;
    $('recovery-error').textContent='';$('recovery-status').textContent='Waiting for the server to confirm this recovery action…';renderRecovery();
    try {
      await request(`/api/tasks/${encodeURIComponent(id)}/recovery/${path}`,body);
      if(sequence!==recoverySequence)return;
      if(operationKind)recoveryOperations.delete(`${id}:${operationKind}`);
      announce('Recovery action acknowledged. Checking observed progress.');
    }catch(error){if(sequence===recoverySequence)$('recovery-error').textContent=`${error.message} The action was not confirmed. Your drafts remain here; nothing will be resent automatically. Refresh checks to reconcile delivery before another decision.`;}
    finally{recoveryBusy=false;if(sequence===recoverySequence)await loadRecovery();}
  }
  async function handoffAction(kind) {
    if(recoveryBusy||!recoveryFresh||stale)return;
    const data=recoveryData,draft=recoveryDraft(),packet=recoveryHandoff,id=recoveryId,sequence=recoverySequence;
    if(draft.pendingHandoff){$('recovery-error').textContent='Reconcile the previous handoff action before starting another one.';return;}
    if(!data?.actions?.[`handoff_${kind}`])return;
    let path='handoffs',body={expected_revision:data.revision,operation_id:crypto.randomUUID().replaceAll('-',''),confirmed:true};
    if(kind==='prepare'){
      if(!draft.question.trim()){$('recovery-error').textContent='Enter an assessment question before preparing a packet.';return;}
      Object.assign(body,{selected_message_ids:[...draft.selected],text:draft.question});
    }else{
      if(!packet||packet.stale||packet.handoff_id!==data.handoff?.id||packet.version!==data.handoff.version)return;
      path+=`/${encodeURIComponent(packet.handoff_id)}/${kind==='response'?'responses':'accept'}`;
      Object.assign(body,{packet_digest:packet.packet_digest,expected_handoff_version:packet.version});
      if(kind==='response'){
        if(!draft.handoffReply.trim()){$('recovery-error').textContent='Paste the assessment reply before checking it.';return;}
        Object.assign(body,{text:draft.handoffReply});
      }else{
        const reply=packet.response;
        if(draft.handoffReplyDirty||!reply?.review_id||Date.now()-recoveryHandoffCheckedAt>55000){$('recovery-error').textContent='Review the current return again before accepting it.';return;}
        Object.assign(body,{response_id:reply.response_id,response_version:reply.response_version,response_digest:reply.response_digest,review_id:reply.review_id});
      }
    }
    draft.pendingHandoff={kind,path,body:JSON.stringify(body),question:draft.question,reply:draft.handoffReply,selected:JSON.stringify([...draft.selected])};
    await reconcileHandoffAction();
  }
  async function reconcileHandoffAction() {
    if(recoveryBusy||!recoveryFresh||stale)return;
    const id=recoveryId,sequence=recoverySequence,draft=recoveryDraft(),pending=draft.pendingHandoff;
    if(!pending)return;
    recoveryBusy=true;recoveryFresh=false;$('recovery-error').textContent='';renderRecovery();
    try{
      await request(`/api/tasks/${encodeURIComponent(id)}/recovery/${pending.path}`,JSON.parse(pending.body));
      if(draft.pendingHandoff===pending)delete draft.pendingHandoff;
      if(pending.kind==='prepare'){
        if(draft.question===pending.question&&JSON.stringify([...draft.selected])===pending.selected)draft.handoffPacketDirty=false;
        if(draft.handoffReply===pending.reply){draft.handoffReply='';draft.handoffReplyDirty=false;}
      }
      if(pending.kind==='response'&&draft.handoffReply===JSON.parse(pending.body).text)draft.handoffReplyDirty=false;
      if(sequence===recoverySequence)announce(pending.kind==='accept'?'Assessment acceptance confirmed. Development still needs its own reviewed plan and approval.':'Handoff action confirmed. Review the checked preview before the next step.');
    }catch(error){
      const rejected=Number.isInteger(error.status)&&error.status>=400&&error.status<500;
      if(rejected&&draft.pendingHandoff===pending)delete draft.pendingHandoff;
      if(sequence===recoverySequence)$('recovery-error').textContent=rejected?`${error.message} The server rejected this attempt. Your drafts remain here. Review refreshed checks before making a new decision.`:`${error.message} Delivery is unconfirmed. Your drafts remain here. Nothing is resent automatically. Use Reconcile previous handoff action to confirm the exact earlier request before a new action.`;
    }
    finally{recoveryBusy=false;if(sequence===recoverySequence)await loadRecovery();}
  }
  async function copyRecoveryHandoff() {
    const packet=recoveryHandoff,draft=recoveryDraft(),id=recoveryId,sequence=recoverySequence;
    if(!recoveryFresh||recoveryBusy||stale||!packet||packet.stale||draft.handoffPacketDirty)return;
    let manualCopy=false;recoveryBusy=true;renderRecovery();
    try{
      const checked=await request(`/api/tasks/${encodeURIComponent(id)}/recovery/handoffs/${encodeURIComponent(packet.handoff_id)}`);
      if(sequence!==recoverySequence||draft.handoffPacketDirty)return;
      if(checked.task_id!==id||checked.handoff_id!==packet.handoff_id||checked.version!==recoveryData?.handoff?.version||checked.packet_digest!==packet.packet_digest||checked.stale||typeof checked.packet_text!=='string')throw new Error('The packet changed or is stale. Refresh checks and prepare a new round.');
      recoveryHandoff=checked;recoveryHandoffCheckedAt=Date.now();
      try{
        if(!globalThis.navigator?.clipboard?.writeText)throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(checked.packet_text);announce('Checked packet copied. Paste it into your chosen approved chat.');
      }catch{
        manualCopy=true;
        $('recovery-error').textContent='Clipboard access is unavailable. Select and copy the checked packet below using your browser keyboard controls.';
      }
    }catch(error){if(sequence===recoverySequence){recoveryHandoff=null;$('recovery-error').textContent=`${error.message} Nothing was copied. Your drafts are retained.`;}}
    finally{recoveryBusy=false;if(sequence===recoverySequence){renderRecovery();if(manualCopy){const field=$('recovery-handoff-packet');field?.focus();field?.select?.();}}}
  }
  function renderAssessmentHandoff(main,data,ready) {
    const draft=recoveryDraft(),packet=recoveryHandoff,current=packet&&packet.handoff_id===data.handoff?.id&&packet.version===data.handoff.version;
    const section=node('section','recovery-handoff');section.append(node('h3','','Assessment handoff'),node('p','conversation-notice','Use an existing approved chat to assess a checked recovery packet. Preview and copy the packet yourself, then paste the reply here for review. The dashboard sends nothing to another chat and starts no model work.'));
    const notice=node('p','conversation-notice',data.capabilities.assessment_handoff===true?'This route needs no dashboard assessment sign-in. Shared text is scanned, but scanning cannot guarantee that all sensitive information is detected. Review what you share.':'Assessment handoff is unavailable. Refresh checks for the current capability.');notice.id='recovery-handoff-limit';section.append(notice);
    if(draft.pendingHandoff){const pendingNotice=node('p','conversation-notice','A previous handoff action has unconfirmed delivery. Reconcile that exact action before preparing, returning or accepting another assessment. Edited drafts are retained.');pendingNotice.id='recovery-handoff-pending';section.append(pendingNotice);const reconcile=button('Reconcile previous handoff action',()=>reconcileHandoffAction(),'primary');reconcile.disabled=!ready;reconcile.setAttribute('aria-describedby','recovery-handoff-pending');section.append(reconcile);}
    const prepare=button(data.handoff?'Prepare next assessment round':'Prepare checked handoff packet',()=>handoffAction('prepare'),'primary');prepare.disabled=!!draft.pendingHandoff||!ready||data.actions.handoff_prepare!==true||data.capabilities.assessment_handoff!==true;prepare.setAttribute('aria-describedby','recovery-action-status recovery-handoff-limit');section.append(prepare);
    if(data.handoff){
      if(!current)section.append(node('p','form-error','The checked packet preview is unavailable. Refresh checks to review it; drafts are retained.'));
      else{
        if(packet.stale)section.append(node('p','form-error','Recovery evidence changed. This packet is stale. Prepare a new round before sharing or accepting a return.'));
        const label=node('label','','Checked packet to share'),text=node('textarea');text.id='recovery-handoff-packet';label.htmlFor=text.id;text.value=packet.packet_text;text.readOnly=true;text.rows=10;text.setAttribute('aria-describedby','recovery-handoff-limit');label.append(text);section.append(label);
        const copy=button('Copy checked packet',()=>copyRecoveryHandoff());copy.id='recovery-handoff-copy';copy.disabled=!ready||packet.stale||draft.handoffPacketDirty;section.append(copy);
        if(draft.handoffPacketDirty)section.append(node('p','conversation-notice','Your question or message selection changed. Prepare the next round to include those edits.'));
        section.append(node('p','conversation-notice','Paste the packet into your chosen chat. Ask for assessment only. Return the complete reply below; the dashboard cannot verify which chat, model or tools produced it.'));
        section.append(recoveryField('Paste assessment reply','handoffReply',8));
        const check=button('Check and preview returned assessment',()=>handoffAction('response'));check.disabled=!!draft.pendingHandoff||!ready||packet.stale||data.actions.handoff_response!==true;section.append(check);
        if(packet.response){
          const returned=node('div','recovery-return-preview');returned.append(node('h4','','Checked returned assessment'),node('p','',packet.response.text||'No checked reply text is available.'),node('p','conversation-notice','Human-supplied external assessment. Source, model, tools, usage and claims are unverified. Accepting records your review; it does not clear unknown work, prove tool isolation or authorize development.'));section.append(returned);
          const accept=button('Accept reviewed assessment',()=>handoffAction('accept'),'primary');accept.id='recovery-handoff-accept';accept.disabled=!!draft.pendingHandoff||!ready||packet.stale||draft.handoffReplyDirty||data.actions.handoff_accept!==true||!packet.response.review_id||Date.now()-recoveryHandoffCheckedAt>55000;accept.setAttribute('aria-describedby','recovery-handoff-accept-limit');section.append(accept);
          const limit=node('p','conversation-notice',draft.handoffReplyDirty?'Your pasted reply changed. Check and preview it again before acceptance.':data.handoff.status==='accepted'?'This assessment was accepted. A continuation plan still needs separate review and approval.':'Read the checked return, then explicitly accept it. If review expires, refresh checks to review it again.');limit.id='recovery-handoff-accept-limit';section.append(limit);
        }
      }
    }else section.append(node('p','','No handoff packet has been prepared. Choose any checked messages and enter your question above.'));
    main.append(section);
  }
  function recoveryField(labelText,key,rows=4) {
    const draft=recoveryDraft(),label=node('label','',labelText),input=node('textarea');input.rows=rows;input.maxLength=key==='question'?12000:key==='note'?4000:key==='handoffReply'?16000:16000;input.id=`recovery-${key}`;input.value=draft[key];label.htmlFor=input.id;input.dataset.recoveryField=key;
    input.addEventListener('input',()=>{draft[key]=input.value;if(key==='handoffReply'){draft.handoffReplyDirty=true;const accept=$('recovery-handoff-accept');if(accept)accept.disabled=true;}if(key==='question'){draft.handoffPacketDirty=true;const copy=$('recovery-handoff-copy');if(copy)copy.disabled=true;}if(key==='instruction'){draft.dirty=true;const approve=$('recovery-continue');if(approve)approve.disabled=true;}});label.append(input);return label;
  }
  function recoveryObserved(target,label,value) {target.append(node('dt','',label),node('dd','',value===true?'Observed':value===false?'Unavailable':value==null?'Not recorded':String(value)));}
  function renderRecovery() {
    const target=$('recovery-content'),draft=recoveryDraft(),previous=target.contains(document.activeElement)?document.activeElement:null;
    const focused=previous?.dataset.recoveryFocus,selection=previous?.selectionStart,selectionEnd=previous?.selectionEnd,direction=previous?.selectionDirection;
    function restoreFocus(){
      const controls=[...target.querySelectorAll('button,textarea,select,input,a,summary')];
      controls.forEach(control=>{control.dataset.recoveryFocus=control.dataset.recoveryField||control.id||control.dataset.recoveryFocus||`${control.tagName}:${control.textContent}`;});
      if(!focused)return;
      const control=controls.find(e=>e.dataset.recoveryFocus===focused&&!e.disabled);
      (control||$('recovery-title')).focus({preventScroll:true});
      if(control?.tagName==='TEXTAREA'&&Number.isInteger(selection))control.setSelectionRange(selection,selectionEnd??selection,direction);
    }
    target.replaceChildren();const data=recoveryData,task=state?.tasks.find(t=>t.id===recoveryId);
    const refresh=button('Refresh checks',()=>{if(data)recoveryAction('check',{expected_revision:data.revision});else loadRecovery();});refresh.disabled=recoveryBusy||(!!data&&data.actions.check!==true);
    const actions=node('div','dialog-actions');actions.append(refresh,button('View recorded conversation',()=>{$('recovery-dialog').close();openConversation(recoveryId);}));target.append(actions);
    if(task)target.append(deletionControl(task));
    if(!data){target.append(node('p','','Recovery evidence is unavailable. Refresh to try again. No model work has started.'));restoreFocus();return;}
    const ready=recoveryFresh&&!recoveryBusy&&!stale,allowed=key=>ready&&(!draft.pendingHandoff||!['review_plan','continue'].includes(key))&&data.actions[key]===true&&(key!=='continue'||state?.connection.status==='connected');
    const actionState=node('p','conversation-notice',ready?'Available actions depend on the selected assessment route, reviewed assessment and checked activity. See the explanation beside each step.':'Recovery actions need a fresh dashboard check. Your drafts are retained.');actionState.id='recovery-action-status';actionState.setAttribute('role','status');target.append(actionState);
    $('recovery-title').textContent=`Recover ${task?.title||'task'}`;
    const recoveryLabels={unchecked:'Checks needed',checking:'Checking recovery',needs_review:'Review recovery',assessment_only:'Assessment available; development blocked',assessing:'Assessment in progress',awaiting_continuation:'Review continuation',reconnecting:'Starting linked development',connected:'Linked development connected',delivery_unknown:'Delivery not confirmed',blocked:'Recovery needs attention'};
    $('recovery-status').textContent=`${recoveryLabels[data.state]||'Review recovery'} · Last checked: ${date(data.checked_at)}${recoveryFresh?'':' · Needs fresh checks'}`;
    target.append(badge(task?.status||'unknown'),node('p','conversation-notice',task?.status&&task.status!=='unknown'?'The parent task’s recorded status is preserved. Delegated work or recovery evidence remains unresolved. Idle or no recent events does not establish that work stopped.':'The original task’s outcome remains unknown. Idle or no recent events does not establish that work stopped.'));
    const stages=node('ol','recovery-stages');['Check recovery','Assess and discuss','Review continuation'].forEach(text=>stages.append(node('li','',text)));target.append(stages);
    const layout=node('div','recovery-layout'),main=node('div','recovery-main'),evidence=node('section','recovery-evidence');evidence.setAttribute('aria-label','Checked recovery evidence');layout.append(main,evidence);target.append(layout);
    const authSection=node('section','recovery-signin');authSection.append(node('h3','','Optional connected assessment'),node('p','conversation-notice','Recovery assessments use ChatGPT plan access with no model tools. Sign-in never starts an assessment or approves development. No API key is requested.'));
    if(recoveryAuth?.authenticated&&recoveryAuth.plan_enabled){authSection.append(node('p','','ChatGPT is connected for assessments.'),button('Disconnect recovery sign-in',()=>recoveryAuthAction('sign-out')));}
    else {
      const authMessage=recoveryAuth?.state==='plan_unavailable'?'This account has not granted eligible ChatGPT plan access. Check this account’s plan access before trying again. No API billing fallback will be used.':recoveryAuth?.state==='dependency_unavailable'?'Sign-in dependencies are unavailable. Follow the dashboard setup instructions before connecting.':recoveryAuth?.state==='signing_in'?'Complete sign-in in the OpenAI page, then return here.':'Connect ChatGPT to start a restricted recovery assessment. Workspace eligibility is checked during sign-in.';
      const authNotice=node('p','conversation-notice',authMessage);authNotice.id='recovery-signin-limit';authSection.append(authNotice);
      if(recoveryAuthUrl){const link=node('a','button primary','Continue with ChatGPT');link.href=recoveryAuthUrl;link.target='_blank';link.rel='noopener noreferrer';authSection.append(link);}
      else {const connect=button('Connect ChatGPT for assessment',()=>recoveryAuthAction('start'),'primary');connect.disabled=recoveryAuthBusy||recoveryAuth?.state==='dependency_unavailable'||recoveryAuth?.state==='signing_in';authSection.append(connect);}
      if(recoveryAuth?.state==='signing_in')authSection.append(button('Cancel pending sign-in',()=>recoveryAuthAction('cancel')));
    }
    if(recoveryAuth?.error_code)authSection.append(node('p','form-error','The sign-in attempt could not establish assessment access. Retry sign-in or keep reviewing local evidence.'));
    if(recoveryAuth?.remote_revocation_confirmed===true)authSection.append(node('p','conversation-notice','Recovery sign-in is disconnected. OpenAI confirmed revocation of the saved refresh token.'));
    else if(recoveryAuth?.remote_revocation_confirmed===false)authSection.append(node('p','conversation-notice','Recovery sign-in is disconnected locally. OpenAI revocation was not confirmed. A request already sent may continue remotely.'));
    authSection.append(node('p','subtext','This recovery session is held in memory. After a dashboard restart you may need to sign in again. Existing Codex credentials are not copied.'));
    evidence.append(node('h3','','Checked evidence and limitations'));const facts=node('dl','detail-grid');
    recoveryObserved(facts,'Project',project(task?.project_id)?.name);recoveryObserved(facts,'Registered directory',project(task?.project_id)?.path);recoveryObserved(facts,'Checked at',date(data.checked_at));recoveryObserved(facts,'Coverage',data.coverage);recoveryObserved(facts,'Execution clearance',data.execution_clearance);recoveryObserved(facts,'Last turn observation',data.last_turn?`${data.last_turn.status} · ${data.last_turn.source} · ${date(data.last_turn.observed_at)}`:'Unavailable');recoveryObserved(facts,'Child agents recorded',data.children?.count);recoveryObserved(facts,'Unresolved children',data.children?.unresolved);evidence.append(facts);
    (data.reason_codes||[]).forEach(reason=>evidence.append(node('p','conversation-notice',reason.replaceAll('_',' '))));
    (Array.isArray(data.observations)?data.observations:[]).forEach(observation=>{const item=node('article','recovery-observation');item.append(node('strong','',observation.kind||observation.source||'Runtime observation'),node('p','',observation.status||observation.coverage||'Unavailable'),node('small','subtext',date(observation.observed_at||observation.checked_at)));evidence.append(item);});
    evidence.append(node('p','conversation-notice','Only the checked evidence shown here is available. The full original native conversation was not restored. Missing usage is Unknown.'));
    const preview=node('section','recovery-packet');preview.append(node('h3','','Assessment input preview'),node('p','conversation-notice','Choose checked local messages to include. Original instructions are never automatically resent. Do not include secrets.'));
    if(!recoveryEvidence.length)preview.append(node('p','','No checked local messages are available. Assessment can use the smaller checked evidence packet where supported.'));
    recoveryEvidence.forEach(message=>{if(!message.id||!['agent','user','system'].includes(message.kind))return;const label=node('label','confirmation-label'),check=node('input');check.type='checkbox';check.dataset.recoveryFocus=`message:${message.id}`;check.checked=draft.selected.has(message.id);check.disabled=!!data.assessment&&data.assessment.source!=='handoff';check.addEventListener('change',()=>{if(check.checked&&draft.selected.size>=20){check.checked=false;$('recovery-error').textContent='Choose at most 20 checked messages.';return;}check.checked?draft.selected.add(message.id):draft.selected.delete(message.id);draft.handoffPacketDirty=true;const copy=$('recovery-handoff-copy');if(copy)copy.disabled=true;});label.append(check,node('span','',`${message.kind||'Message'} · ${date(message.created_at)}\n${message.text||'Content withheld.'}`));preview.append(label);});
    if(!data.assessment||data.assessment.source==='handoff')preview.append(recoveryField('Your assessment question','question'));
    if(!data.assessment){
      const assessor=role('technical_architect');authSection.append(node('p','conversation-notice',`Assessment role: ${assessor?.label||'Technical architect'} · Configured model: ${assessor?.model||'Unknown'}. Required assessment scope: no project tools or connectors.`));
      authSection.append(node('p','conversation-notice','Starts agent work and can consume workspace usage. This conversation can assess the checked evidence and answer questions. It has no authority to change project files, run project commands or continue the old work.'));
      const start=button('Start assessment conversation',()=>{if(!draft.question.trim()){$('recovery-error').textContent='Enter an assessment question.';return;}recoveryAction('assess',{receipt_id:data.receipt_id,operation_id:recoveryOperation('assess'),selected_message_ids:[...draft.selected],text:draft.question.trim(),confirmed:true},{operationKind:'assess'});},'primary');start.disabled=!allowed('assess')||data.capabilities.assessment!==true;authSection.append(start);
      const assessmentLimit=node('p',data.capabilities.assessment!==true?'form-error':'conversation-notice',data.capabilities.assessment!==true?'Safe assessment capability is not verified. Connect ChatGPT for assessment, then refresh checks. No model turn can start until the assessment boundary is ready.':!data.actions.assess?'Refresh checks before starting an assessment. Any unresolved dispatch must be reconciled first.':'Starting an assessment does not approve development.');assessmentLimit.id='recovery-assessment-limit';authSection.append(assessmentLimit);start.setAttribute('aria-describedby','recovery-action-status recovery-assessment-limit');
    }main.append(preview);
    renderAssessmentHandoff(main,data,ready);main.append(authSection);
    if(data.assessment){
      if(data.assessment.source!=='handoff'){
      const section=node('section','recovery-assessment');section.append(node('h3','','Linked assessment conversation'),badge(data.assessment.status),button('Open assessment conversation',()=>{$('recovery-dialog').close();openConversation(data.assessment.task_id);}));
      section.append(node('p','conversation-notice','Assessment completion does not change the old outcome or grant development authority.'));
      const log=node('div','conversation-log');log.setAttribute('role','log');log.setAttribute('aria-label','Recovery assessment messages');
      if(!recoveryChat)log.append(node('p','','Assessment history is unavailable. Refresh checks to restore it.'));
      else if(!recoveryChat.messages?.length)log.append(node('p','','No completed assessment message has been observed yet.'));
      (recoveryChat?.messages||[]).forEach(message=>{const article=node('article','conversation-message');article.append(node('strong','',message.kind==='user'?'You':'Assessment agent'),node('p','',message.text||'Content withheld.'));log.append(article);});section.append(log);
      section.append(recoveryField('Ask about recovery','followup'),node('p','conversation-notice','Sending a question starts agent work and can consume workspace usage. Questions cannot authorize file changes or continuation.'));
      const send=button('Send question',()=>sendRecoveryQuestion(),'primary');send.disabled=!ready||recoveryChat?.can_send!==true;section.append(send);
      if(active.has(data.assessment.status)){const stop=button('Stop assessment',()=>stopRecoveryAssessment(),'danger');stop.disabled=!ready;section.append(stop);}
      main.append(section);
      }
      const review=node('section','recovery-review');review.append(node('h3','','Review continuation'));
      if(data.plan&&!draft.dirty){draft.instruction=data.plan.instruction||'';draft.role=data.plan.role||draft.role;draft.strategy=data.plan.target_strategy||draft.strategy;}
      review.append(recoveryField('Exact new instruction','instruction',6));
      const roleLabel=node('label','','Agent role'),roleSelect=node('select');roleSelect.dataset.recoveryField='role';(state?.roles||[]).forEach(r=>{const option=node('option','',r.label||r.id);option.value=r.id;roleSelect.append(option);});roleSelect.value=draft.role;roleSelect.addEventListener('change',()=>{draft.role=roleSelect.value;draft.dirty=true;const approve=$('recovery-continue');if(approve)approve.disabled=true;});roleLabel.append(roleSelect);review.append(roleLabel);
      const strategyLabel=node('label','','Continuation target'),strategy=node('select');strategy.dataset.recoveryField='strategy';[['new_linked','New linked work conversation'],['same_thread','Original conversation']].forEach(([value,text])=>{const option=node('option','',text);option.value=value;option.disabled=data.capabilities[value]!==true;strategy.append(option);});strategy.value=draft.strategy;strategy.addEventListener('change',()=>{draft.strategy=strategy.value;draft.dirty=true;const approve=$('recovery-continue');if(approve)approve.disabled=true;});strategyLabel.append(strategy);review.append(strategyLabel);
      const save=button(data.plan?'Save revised plan':'Create continuation plan',()=>{if(!draft.instruction.trim()){$('recovery-error').textContent='Enter a fresh continuation instruction.';return;}const body={assessment_task_id:data.assessment.task_id,expected_revision:data.revision,instruction:draft.instruction.trim(),target_strategy:draft.strategy,role:draft.role};if(data.plan){body.expected_plan_version=data.plan.version;delete body.assessment_task_id;}draft.dirty=true;recoveryAction(data.plan?`plans/${encodeURIComponent(data.plan.id)}`:'plans',body).then(()=>{if(recoveryData?.plan?.instruction===draft.instruction.trim()&&recoveryData.plan.role===draft.role&&recoveryData.plan.target_strategy===draft.strategy){draft.dirty=false;renderRecovery();}});});save.disabled=!allowed('review_plan');review.append(save);
      review.append(node('p','conversation-notice',`Target project: ${project(task?.project_id)?.name||'Unavailable'} · Directory: ${project(task?.project_id)?.path||'Unavailable'}`));
      review.append(node('p','conversation-notice',`Saved project approval preference: ${settings?.project_approval_modes?.[task?.project_id]||'manual'}. Recovery execution requires manual approvals. Previous approvals are not restored.`));
      if(data.plan)review.append(node('p','recovery-plan-binding',`Reviewed plan version ${data.plan.version} · Model ${data.plan.model||'Unknown'} · Approval mode ${data.plan.effective_approval_mode||'Unknown'}`));
      if(data.plan?.project_identity){const identity=data.plan.project_identity;review.append(node('p','conversation-notice',`Selected current project directory: ${identity.canonical_path||project(task?.project_id)?.path||'Unavailable'}. Directory identity is checked again before dispatch.${identity.legacy_original_unverified?' The original directory identity was not recorded; this approval selects the current directory for new linked work only.':''}`));}
      review.append(node('p','conversation-notice','Starts a new work turn using the instruction shown above. It can consume workspace usage and modify files under the current permissions. Earlier actions may already have happened. Previous approvals are not restored.'));
      const proceed=button('Approve and continue development',()=>{if(draft.dirty||!data.plan)return;recoveryAction('continue',{receipt_id:data.receipt_id,operation_id:recoveryOperation('continue'),assessment_task_id:data.assessment.task_id,plan_id:data.plan.id,plan_digest:data.plan.digest,confirmed:true},{operationKind:'continue'});},'primary');proceed.id='recovery-continue';proceed.disabled=!allowed('continue')||!data.plan||draft.dirty;review.append(proceed,button('Back to assessment',()=>{const field=$('recovery-handoffReply')||$('recovery-followup');field?.focus();}));
      const continuationLimit=node('p','conversation-notice',draft.dirty?'Save the revised plan, then refresh checks before approving continuation.':!data.actions.continue?(data.plan&&!data.receipt_id?'Plan saved. Select Refresh checks to verify current activity before approving continuation. You can keep discussing recovery.':'Continuation is blocked until assessment, current authority, ownership and activity checks permit it. You can keep discussing recovery.'):'Approval starts only the reviewed plan. Existing permissions and manual action approvals still apply.');continuationLimit.id='recovery-continuation-limit';review.append(continuationLimit);proceed.setAttribute('aria-describedby','recovery-action-status recovery-continuation-limit');main.append(review);
    }
    if(data.operation){const operation=node('section','recovery-operation');operation.append(node('h3','','Recovery operation'),node('p','',`${data.operation.kind} · ${data.operation.status}`));
      if(data.operation.target_task_id){const current=state?.tasks.find(t=>t.id===data.operation.target_task_id);operation.append(button('Open live work conversation',()=>{$('recovery-dialog').close();openConversation(data.operation.target_task_id);}),node('p','',`Observed task state: ${current?.status||'Not yet observed'}. Acknowledgement is not completion.`));}
      if(data.actions.cancel){const cancel=button(data.operation.status==='prepared'?'Cancel before dispatch':'Request stop and reconcile',()=>recoveryAction(`operations/${encodeURIComponent(data.operation.id)}/cancel`,{expected_revision:data.revision,confirmed:true}),'danger');cancel.disabled=!allowed('cancel');operation.append(cancel);}
      operation.append(node('p','conversation-notice','Uncertain delivery is never retried automatically. Cancellation reports success only with matching evidence.'));main.append(operation);}
    if(data.actions.plan_restart){const plan=button('Plan a computer restart',()=>recoveryAction('restart-plan',{expected_revision:data.revision,confirmed:true}));plan.disabled=!allowed('plan_restart');evidence.append(node('p','conversation-notice','If process ownership cannot be verified, you may choose to plan a computer restart. This only prepares manual steps; it never restarts your computer.'),plan);}
    if(data.restart){evidence.append(node('h3','','Manual restart plan'),node('p','',`Boot fence: ${data.restart.boot_fence_status||'Unchecked'}`));const list=node('ol');(data.restart.instructions||[]).forEach(text=>list.append(node('li','',text)));evidence.append(list);}
    const technical=node('details','recovery-technical');technical.append(node('summary','','Technical references'),node('p','subtext',`Original task: ${recoveryId}`));if(data.assessment)technical.append(node('p','subtext',`Assessment task: ${data.assessment.task_id}`));if(data.plan)technical.append(node('p','subtext',`Reviewed plan identifier: ${data.plan.id} · Digest: ${data.plan.digest}`));evidence.append(technical);
    const annotation=node('section','recovery-annotation');annotation.append(node('h3','','Your assessment note'),node('p','conversation-notice','This records your conclusion only. It does not change the native outcome, clear a project hold or authorize work.'));
    const dispositionLabel=node('label','','Your conclusion'),disposition=node('select');disposition.dataset.recoveryField='disposition';[['needs_investigation','Needs investigation'],['reviewed','Evidence reviewed'],['abandoned','No further work planned']].forEach(([value,text])=>{const option=node('option','',text);option.value=value;disposition.append(option);});disposition.value=draft.disposition;disposition.addEventListener('change',()=>{draft.disposition=disposition.value;});dispositionLabel.append(disposition);annotation.append(dispositionLabel,recoveryField('Evidence and remaining uncertainty','note',3));
    const saveNote=button('Save assessment note',()=>{if(!draft.note.trim()){$('recovery-error').textContent='Enter a nonsecret note about the evidence.';return;}recoveryAction('disposition',{expected_revision:data.revision,disposition:draft.disposition,note:draft.note.trim(),confirmed:true});});saveNote.disabled=recoveryBusy||!recoveryFresh;annotation.append(saveNote);evidence.append(annotation);
    target.querySelectorAll('button,select,input').forEach(control=>{if(control.disabled&&!control.getAttribute?.('aria-describedby'))control.setAttribute('aria-describedby',control.textContent==='Connect ChatGPT for assessment'?'recovery-action-status recovery-signin-limit':'recovery-action-status');});
    restoreFocus();
  }
  async function sendRecoveryQuestion() {
    const data=recoveryData,draft=recoveryDraft();if(recoveryBusy||!recoveryFresh||!recoveryChat?.can_send||!draft.followup.trim())return;
    const id=recoveryId,sequence=recoverySequence;recoveryBusy=true;renderRecovery();
    try {await request(`/api/tasks/${encodeURIComponent(data.assessment.task_id)}/message`,{text:draft.followup.trim(),expected_turn_id:recoveryChat.turn_id??null});if(sequence===recoverySequence)draft.followup='';}
    catch(error){if(sequence===recoverySequence)$('recovery-error').textContent=`${error.message} Your question remains here. Nothing will resend automatically.`;}
    finally{recoveryBusy=false;if(sequence===recoverySequence&&id===recoveryId)await loadRecovery();}
  }
  async function stopRecoveryAssessment() {
    if(recoveryBusy||!recoveryFresh||!recoveryData?.assessment)return;
    const sequence=recoverySequence;recoveryBusy=true;renderRecovery();
    try{await request(`/api/tasks/${encodeURIComponent(recoveryData.assessment.task_id)}/interrupt`,{});if(sequence===recoverySequence)$('recovery-status').textContent='Stop requested. Waiting for observed interruption; this is not proof that work stopped.';}
    catch(error){if(sequence===recoverySequence)$('recovery-error').textContent=`${error.message} Stop delivery is uncertain. Refresh checks.`;}
    finally{recoveryBusy=false;if(sequence===recoverySequence)await loadRecovery();}
  }

  async function interrupt(task, b){await perform(b,`/api/tasks/${encodeURIComponent(task.id)}/interrupt`,{},'Stop requested. Waiting for Codex to confirm the run state.');}
  async function submit(event,path){event.preventDefault();const form=event.currentTarget;if(!form.reportValidity())return;const b=form.querySelector('[type="submit"]'),error=form.querySelector('.form-error');if(path==='/api/tasks'&&(stale||state?.connection.status!=='connected')){error.textContent='Refresh the workspace and restore the Codex connection before starting a run.';return;}const body=Object.fromEntries(new FormData(form));Object.keys(body).forEach(k=>body[k]=body[k].trim());if(Object.values(body).some(v=>!v)){error.textContent='Complete all fields with more than whitespace.';return;}b.disabled=true;error.textContent='';try{const result=await request(path,body);if(path==='/api/tasks')submittedTaskId=result?.id||null;form.closest('dialog').close();form.reset();announce(path==='/api/projects'?'Project added.':'Run submitted. Open its activity for live checkpoints and any failure details.');await refresh();if(path==='/api/tasks'&&result?.id){const task=state?.tasks.find(t=>t.id===result.id);if(task?.status==='failed'){failureNoticeId=task.id;renderFailureNotice();}if(task)openTask(task.id);}}catch(e){error.textContent=e.message;}finally{b.disabled=false;}}
  $('view-run-failure').addEventListener('click',()=>{if(failureNoticeId)openTask(failureNoticeId);});
  $('dismiss-run-failure').addEventListener('click',()=>{failureNoticeId=null;renderFailureNotice();});
  $('conversation-task').addEventListener('change',selectConversation);$('refresh-conversation').addEventListener('click',loadConversation);
  $('refresh-team').addEventListener('click',loadTeam);
  $('approve-request').addEventListener('click',()=>respondReviewedApproval('accept'));
  $('configure-project-approvals').addEventListener('click',openProjectApprovalSettings);
  $('reveal-sensitive-request').addEventListener('click',revealSensitiveRequest);
  ['confirm-sensitive-reveal','confirm-sensitive-approve'].forEach(id=>$(id).addEventListener('change',checkApprovalReview));
  $('retry-approval-review').addEventListener('click',retryApprovalReview);
  $('request-approval-alternative').addEventListener('click',requestApprovalAlternative);
  $('continue-approval-guidance').addEventListener('click',continueApprovalGuidance);
  $('open-cancelled-conversation').addEventListener('click',()=>{const continuation=approvalContinuations.get(displayedContinuationId);if(continuation){$('approval-review-dialog').close();openConversation(continuation.task_id);}});
  $('decline-reviewed-request').addEventListener('click',()=>respondReviewedApproval('decline'));
  $('cancel-reviewed-request').addEventListener('click',()=>respondReviewedApproval('cancel'));
  $('stop-reviewed-run').addEventListener('click',async()=>{if(!approvalReview||approvalReviewSending||stale||state?.connection.status!=='connected')return;const task=state.tasks.find(t=>t.id===approvalReview.task_id);if(!task)return;approvalReviewSending=true;invalidateApprovalReview('Stop requested. Waiting for the run state to be confirmed.');checkApprovalReview();try{await interrupt(task,$('stop-reviewed-run'));}finally{approvalReviewSending=false;checkApprovalReview();}});
  $('settings-form').addEventListener('submit',saveSettings);$('reload-settings').addEventListener('click',loadSettings);$('logo-upload').addEventListener('change',uploadLogo);$('settings-form').elements.logo_choice.addEventListener('change',updateLogoPreview);
  $('repository-form').addEventListener('submit',createRepository);['owner','name','visibility'].forEach(key=>$('repository-form').elements[key].addEventListener('input',repositoryDestination));
  $('delete-run-acknowledge').addEventListener('change',renderRunDeletion);$('delete-run-confirm').addEventListener('click',confirmRunDeletion);$('delete-run-refresh').addEventListener('click',async()=>{await refresh(true);if(deleteTarget)renderRunDeletion();});
  $('add-project').addEventListener('click',openProject);$('start-run').addEventListener('click',openRun);$('retry').addEventListener('click',refresh);
  $('refresh-files').addEventListener('click',loadFiles);$('file-search').addEventListener('input',renderFiles);$('refresh-git').addEventListener('click',loadGit);$('confirm-publish').addEventListener('click',publishCommits);
  $('project-form').addEventListener('submit',e=>submit(e,'/api/projects'));$('run-form').addEventListener('submit',e=>submit(e,'/api/tasks'));$('run-form').elements.role.addEventListener('change',()=>{preferredRole=$('run-form').elements.role.value;modelHint();});
  ['project-filter','status-filter','role-filter'].forEach(id=>$(id).addEventListener('change',()=>state&&render()));$('search').addEventListener('input',()=>state&&render());
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.view;updateView();}));
  document.querySelectorAll('dialog').forEach(dialog=>{
    dialog.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>dialog.close()));
    dialog.addEventListener('cancel',event=>{if(dialog.id==='repository-dialog'&&creatingRepository||dialog.id==='delete-run-dialog'&&deleteBusy)event.preventDefault();});
    dialog.addEventListener('close',()=>{if(dialog.id==='outputs-dialog'){outputsSequence++;if(dialog.returnFocus?.isConnected===false)dialog.returnFocus=[...document.querySelectorAll('button')].find(b=>b.dataset.outputsTask===dialog.dataset.taskId)||$('task-dialog-title'); }if(dialog.id==='task-dialog'){detailId=null;deliveryId='';deliverySequence++;deliveryData=null;deliveryPreview=null;deliveryFresh=false;}if(dialog.id==='approval-review-dialog'){$('approval-response-fields').replaceChildren();$('approval-response-fields').hidden=true;displayedContinuationId=null;approvalReview=null;clearSensitiveReview();approvalReviewSequence++;$('approval-guidance').value='';$('approval-review-context').textContent='';$('approval-review-context').hidden=true;$('approval-command-context').replaceChildren();$('approval-command-context').hidden=true;$('approve-request').disabled=true;}if(dialog.id==='agent-dialog'){agentPromptSequence++;$('agent-prompt').textContent='';$('agent-prompt').hidden=true;}if(dialog.id==='delete-run-dialog')restoreRunDeletionFocus(dialog);else dialog.returnFocus?.focus();});
    // Native modal dialogs handle Escape and inert the page; explicitly wrap Tab for keyboard users.
    dialog.addEventListener('keydown',e=>{if(e.key!=='Tab')return;const controls=[...dialog.querySelectorAll('button,input,textarea,select,a[href]')].filter(x=>!x.disabled&&!x.hidden);if(!controls.length){e.preventDefault();return;}const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});
  });
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){refresh();checkGitFreshness();}});
  setInterval(()=>{if(!document.hidden){refresh();checkGitFreshness();if(view==='team')loadTeam();if(view==='conversations')loadConversation();if($('recovery-dialog').open&&!recoveryBusy)loadRecovery();if($('task-dialog').open&&deliveryId&&!deliveryBusy)loadDelivery();}},3000);loadProvider();loadSettings();refresh();
})();
