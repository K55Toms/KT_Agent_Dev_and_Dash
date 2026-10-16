'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  let state = null, view = 'overview', refreshing = false, lastRefresh = null, detailId = null, detailSignature = '', stale = true, preferredRole = 'chief_of_staff';
  let browserProject = null, fileEntries = [], filesLoaded = false, filesRequest = 0, previewRequest = 0, selectedFile = '';
  let gitSnapshot = null, gitLoaded = false, gitRequest = 0, gitCheckedAt = 0, publishPreview = null, publishing = false;
  const active = new Set(['queued', 'running', 'waiting_approval']);
  const labels = {queued:'Queued', running:'Running', waiting_approval:'Approval needed', completed:'Completed', failed:'Failed', interrupted:'Interrupted', unknown:'Unknown'};
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
    if(!response.ok) throw new Error(typeof data.error==='string' ? data.error : 'The request could not be completed.');
    return data;
  }
  async function loadTheme() {
    const themes={hybrid:'Hybrid Night Shift',terminal:'Terminal Ops',rebel:'Rebel Command'};
    let theme='hybrid';
    try {
      const config=await request('/api/config');
      if(config&&Object.hasOwn(themes,config.theme))theme=config.theme;
    } catch {
      // A missing or unavailable configuration keeps the safe, chosen Hybrid default.
    }
    document.body.dataset.theme=theme;
    $('active-theme').textContent=themes[theme];
  }
  function selectedTasks() { const id=$('project-filter').value, q=$('search').value.trim().toLocaleLowerCase(), status=$('status-filter').value, owner=$('role-filter').value;return state.tasks.filter(t=>(!id||t.project_id===id)&&(!q||String(t.title).toLocaleLowerCase().includes(q))&&(!status||t.status===status)&&(!owner||t.role===owner)); }
  function selectedApprovals(tasks) { const ids=new Set(tasks.map(t=>t.id));return state.approvals.filter(a=>ids.has(a.task_id)); }
  function options(select, items, placeholder) { const old=select.value;select.replaceChildren();if(placeholder)select.append(new Option(placeholder,''));items.forEach(i=>select.append(new Option(i.label,i.id)));if(Array.from(select.options).some(o=>o.value===old))select.value=old; }
  async function refresh() {
    if(refreshing)return;refreshing=true;
    try {
      const next=await request('/api/state');
      if(!next || !['projects','tasks','approvals','roles'].every(key=>Array.isArray(next[key])) || !next.connection)throw new Error('The local server returned an incomplete workspace state.');
      const changed=JSON.stringify(next)!==JSON.stringify(state)||!$('load-error').hidden;
      state=next;stale=false;lastRefresh=new Date();$('load-error').hidden=true;$('loading').hidden=true;$('dashboard-content').hidden=false;
      if(!changed){$('refresh-time').textContent=`Dashboard checked: ${date(lastRefresh)}`;return;}
      options($('project-filter'),state.projects.map(p=>({id:p.id,label:p.name})),'All projects');
      options($('role-filter'),state.roles,'All roles');
      render();
    } catch(error) {
      stale=true;$('load-error').hidden=false;$('load-error-text').textContent=`${state?'Showing the last received data. It may be stale. ':'Could not load the workspace. '}${error.message}`;
      if(!state)$('loading').textContent='Workspace unavailable. Check that the local dashboard server is running, then retry.';
      $('connection-label').textContent='Dashboard data unavailable';$('connection-dot').className='connection-dot';
      // Stale native approvals must not remain actionable.
      document.querySelectorAll('[data-live-action]').forEach(b=>{b.disabled=true;});$('start-run').disabled=true;
    } finally {refreshing=false;}
  }
  function metric(label,value,note,icon,emphasis=false) {const box=node('article','metric'),head=node('div','metric-head');head.append(node('span','',label),node('span','metric-icon',icon));box.append(head,node('div','metric-value',String(value)),node('div',`metric-note${emphasis?' emphasis':''}`,note));return box;}
  function render() {
    const tasks=selectedTasks(), approvals=selectedApprovals(tasks), pending=approvals.filter(a=>a.status==='pending');
    $('metrics').replaceChildren();
    const completed=tasks.filter(t=>t.status==='completed').length, running=tasks.filter(t=>active.has(t.status)).length;
    const known=tasks.filter(t=>t.cost?.basis==='estimated'&&typeof t.cost.credits==='number'&&Number.isFinite(t.cost.credits));
    const bases=new Set(known.map(t=>JSON.stringify([t.cost.source,t.cost.pricing_date]))), unknown=tasks.length-known.length;
    let amount='Unknown',costNote=tasks.length ? `${unknown} run${unknown===1?'':'s'} with unknown cost` : 'No execution usage observed';
    if(known.length&&bases.size===1){amount=`≈ ${number(known.reduce((sum,t)=>sum+t.cost.credits,0))}`;costNote=`Estimated credits · ${unknown} unknown run${unknown===1?'':'s'}`;}
    else if(bases.size>1){amount='Mixed basis';costNote='See individual estimates below';}
    $('metrics').append(metric('Total tasks',tasks.length,`${state.projects.filter(p=>!$('project-filter').value||p.id===$('project-filter').value).length} registered projects`,'☷'),metric('Active runs',running,`${completed} completed model turns`,'↗',running>0),metric('Human decisions',pending.length,pending.length?'Your input is needed':'No pending requests','◇',pending.length===0),metric('Execution estimate',amount,costNote,'◷'));
    $('nav-approval-count').textContent=String(state.approvals.filter(a=>a.status==='pending').length);
    $('task-count').textContent=`${tasks.length} task${tasks.length===1?'':'s'}`;
    renderTasks(tasks);renderAttention(tasks,pending);renderApprovals(approvals);renderCosts(tasks);
    const c=state.connection;$('connection-dot').className=`connection-dot ${c.status==='connected'?'connected':c.status==='connecting'?'connecting':''}`;
    $('connection-label').textContent=c.status==='connected'?'Codex connected':c.status==='connecting'?'Connecting to Codex':'Codex disconnected';
    $('source-title').textContent=`Codex App Server${c.server_version?' · '+c.server_version:''}`;
    $('source-detail').textContent=c.detail||'Only runs started in this dashboard are tracked. Existing desktop chats are not included.';
    $('source-time').textContent=`Source event: ${date(c.last_event_at)}`;$('refresh-time').textContent=`Dashboard checked: ${date(lastRefresh)}`;
    $('start-run').disabled=stale||!state.projects.length||!state.roles.length||c.status!=='connected';
    $('start-run').title=!state.projects.length?'Add a project first':c.status!=='connected'?'Wait for the Codex connection':'';
    if(detailId&&$('task-dialog').open)renderDetail(detailId);
    updateView();
    if(stale){$('connection-label').textContent='Dashboard data unavailable';$('connection-dot').className='connection-dot';document.querySelectorAll('[data-live-action]').forEach(b=>{b.disabled=true;});}
  }
  function renderTasks(tasks) {
    const target=$('task-list');target.replaceChildren();
    if(!tasks.length){empty(target,state.tasks.length?'No matching tasks':state.projects.length?'Ready for your first run':'A clear view of your team’s work',state.tasks.length?'Try a different project, status, role or search.':state.projects.length?'Start a run to see live progress, plans and approval requests.':'Add a local project to begin tracking dashboard-managed Codex runs.',!state.projects.length?button('+ Add project',openProject):undefined);return;}
    const wrap=node('div','table-scroll'),table=node('table'),head=node('thead'),row=node('tr');['TASK / PROJECT','AGENT','STATUS','UPDATED'].forEach(t=>row.append(node('th','',t)));head.append(row);table.append(head);const body=node('tbody');
    [...tasks].sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))).forEach(t=>{const r=node('tr'),title=node('td'),link=button(t.title,()=>openTask(t.id));link.className='task-link';title.append(link,node('span','subtext',project(t.project_id)?.name||'Unknown project'));const owner=node('td','',role(t.role)?.label||t.role);owner.append(node('span','subtext',t.model?`${t.model} · configured`:'Model not recorded'));const status=node('td');status.append(badge(t.status));r.append(title,owner,status,node('td','',date(t.updated_at)));body.append(r);});table.append(body);wrap.append(table);target.append(wrap);
  }
  function renderAttention(tasks,pending) {
    const target=$('attention-list');target.replaceChildren();
    if(!pending.length&&!tasks.some(t=>['failed','unknown'].includes(t.status))){empty(target,'Nothing waiting on you','New approval requests and interrupted connections will appear here.');return;}
    pending.slice(0,3).forEach(a=>{const item=node('article','attention-item'),task=tasks.find(t=>t.id===a.task_id);item.append(badge('waiting_approval'),node('h3','',a.summary||'Approval needed'),node('p','',task?.title||'Task'),button('Review request',()=>{view='approvals';updateView();$('main').focus();}));target.append(item);});
    tasks.filter(t=>['failed','unknown'].includes(t.status)).slice(0,2).forEach(t=>{const item=node('article','attention-item');item.append(badge(t.status),node('h3','',t.title),node('p','',t.status==='unknown'?'The run state could not be confirmed. Review the connection before proceeding.':'The run needs review.'),button('View task',()=>openTask(t.id)));target.append(item);});
  }
  async function perform(buttonElement, path, body, message) {
    if(stale){announce('Refresh workspace data before acting on a live run.');return;}
    buttonElement.disabled=true;
    try {await request(path,body);announce(message);await refresh();}
    catch(error){ const e=node('p','form-error',error.message);buttonElement.parentElement.append(e);buttonElement.disabled=false; }
  }
  function renderApprovals(approvals) {
    const target=$('approval-list');target.replaceChildren();
    if(!approvals.length){empty(target,'No decisions to review','Native approval requests appear here when a dashboard-managed run asks for permission.');return;}
    [...approvals].sort((a,b)=>(a.status==='pending'?-1:1)-(b.status==='pending'?-1:1)).forEach(a=>{
      const card=node('article','approval-card'),task=state.tasks.find(t=>t.id===a.task_id);card.append(node('span',`badge ${a.status==='pending'?'waiting_approval':''}`,a.status==='pending'?'Approval needed':a.status==='resolved'?'Resolved':'Unavailable'),node('h3','',a.summary||'Native approval request'),node('p','',`${project(task?.project_id)?.name||'Unknown project'} · ${task?.title||'Task'} · ${date(a.created_at)}`));
      card.append(node('p','',`Requested by: ${a.requester || role(task?.role)?.label || 'Codex App Server'}`));
      if(a.reason)card.append(node('p','',a.reason));if(a.scope)card.append(node('div','scope',typeof a.scope==='string'?a.scope:JSON.stringify(a.scope)));
      if(a.status==='pending') {
        card.append(node('p','', 'This version can decline or stop the run. Approval grants require a full-context review flow. Decisions apply only to this request.'));
        const actions=node('div','approval-actions');
        // Grants are deliberately absent: sanitized summaries cannot provide full-context review.
        if((a.available_decisions||[]).includes('decline')){const decline=button('Decline request',()=>perform(decline,`/api/approvals/${encodeURIComponent(a.id)}/respond`,{decision:'decline'},'Request declined.'),'danger');decline.dataset.liveAction='true';decline.disabled=state.connection.status!=='connected';actions.append(decline);}
        if(task&&active.has(task.status)){const stop=button('Stop run',()=>interrupt(task,stop),'secondary');stop.dataset.liveAction='true';stop.disabled=state.connection.status!=='connected';actions.append(stop);}
        if(!(a.available_decisions||[]).includes('decline'))card.append(node('p','', 'This request type cannot be answered here. Stop the run if it cannot proceed.'));
        card.append(actions);
      } else if(a.status==='unavailable')card.append(node('p','', 'The live request is no longer actionable. Reconnecting does not replay this decision.'));
      target.append(card);
    });
  }
  function renderCosts(tasks) {
    const target=$('cost-list');target.replaceChildren();
    if(!tasks.length)empty(target,'No execution usage yet','Usage will appear when Codex reports it for a dashboard-managed run.');
    else {const wrap=node('div','table-scroll'),table=node('table'),head=node('thead'),hr=node('tr');['TASK','CONFIGURED MODEL','OBSERVED TOKENS','CREDIT ESTIMATE','BASIS / SOURCE'].forEach(t=>hr.append(node('th','',t)));head.append(hr);table.append(head);const body=node('tbody');tasks.forEach(t=>{const r=node('tr'),title=node('td'),link=button(t.title,()=>openTask(t.id));link.className='task-link';title.append(link,node('span','subtext',project(t.project_id)?.name||'Unknown project'));const cost=t.cost,estimate=cost?.basis==='estimated'&&typeof cost.credits==='number'&&Number.isFinite(cost.credits);const source=node('td','',estimate?'Estimated · Standard speed':'Unknown');source.append(node('span','subtext',cost?.source||'No verified cost basis'),node('span','subtext',cost?.pricing_date?`Pricing: ${cost.pricing_date}`:''));r.append(title,node('td','',t.model||'Not recorded'),node('td','',t.usage?number(t.usage.total_tokens):'Not observed'),node('td','',estimate?`≈ ${number(cost.credits)} credits`:'Unknown'),source);body.append(r);});table.append(body);wrap.append(table);target.append(wrap);}
    const p=state.pricing||{};$('pricing-note').replaceChildren(node('span','',`Standard-speed workspace credit estimates are not verified charges or invoices. No currency conversion. Estimates cover reported main-thread usage only; spawned-agent usage is not rolled up. ${p.pricing_date?'Pricing date: '+p.pricing_date+'. ':''}`));
    if(p.source){try{const url=new URL(p.source);if(url.protocol==='https:'&&['learn.chatgpt.com','developers.openai.com','openai.com'].includes(url.hostname)){const link=node('a','','Pricing source');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';$('pricing-note').append(link);}}catch{/* Unrecognized pricing URLs remain unlinked. */}}
  }
  function updateView() {
    const titles={overview:['Workspace overview','Follow the work. Understand the usage. Unblock your team.'],tasks:['Development tasks','Live status and execution evidence across your projects.'],approvals:['Human approvals','Review requests that need a decision to move forward.'],costs:['Execution costs','Observed usage and clearly labelled workspace credit estimates.'],files:['Project files','Inspect project source safely, without leaving your workspace.'],git:['Git & publish','Check repository status and publish committed work to a reviewed destination.']};
    $('page-title').textContent=titles[view][0];$('page-subtitle').textContent=titles[view][1];$('breadcrumb-view').textContent=view[0].toUpperCase()+view.slice(1);
    document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    $('work-panel').parentElement.hidden=!['overview','tasks'].includes(view);$('attention-panel').hidden=view!=='overview';$('approvals-panel').hidden=view!=='approvals';$('costs-panel').hidden=view!=='costs';
    $('files-panel').hidden=view!=='files';$('git-panel').hidden=view!=='git';
    const projectView=['files','git'].includes(view);
    $('metrics').hidden=projectView;$('search').closest('label').hidden=projectView;$('status-filter').hidden=projectView;$('role-filter').hidden=projectView;
    document.querySelector('.completion-note').hidden=projectView;
    $('work-panel').parentElement.classList.toggle('tasks-only',view==='tasks');
    if(state)ensureProjectViews();
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
    }
    $('refresh-files').disabled=!id;$('refresh-git').disabled=!id||publishing;
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
    const id=$('project-filter').value;if(!id||publishing)return;
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
    const reason=node('p','git-publish-reason',git.reason||(!git.remote?'Configure a supported origin remote outside this dashboard, then refresh status.':!git.clean?'Commit or otherwise resolve your changes outside this dashboard, then refresh status.':'Review the exact destination and commit before publishing.'));reason.id='git-publish-reason';publish.setAttribute('aria-describedby',reason.id);actions.append(reason,publish);target.append(actions);
  }
  function checkGitFreshness() {
    if(!gitSnapshot||!gitCheckedAt||Date.now()-gitCheckedAt<60000)return;
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
  function openRun(){if(stale||!state||!state.projects.length||state.connection.status!=='connected')return;const form=$('run-form');options(form.elements.project_id,state.projects.map(p=>({id:p.id,label:p.name})));if($('project-filter').value)form.elements.project_id.value=$('project-filter').value;options(form.elements.role,state.roles);if(state.roles.some(r=>r.id===preferredRole))form.elements.role.value=preferredRole;modelHint();openDialog('run-dialog');}
  function modelHint(){const r=role($('run-form').elements.role.value);$('role-model').textContent=r?`Configured: ${r.model||'model not recorded'} · ${r.reasoning||'default'} reasoning. Actual routing may differ.`:'';}
  function openTask(id){detailId=id;detailSignature='';renderDetail(id);openDialog('task-dialog');}
  function renderDetail(id){
    const t=state.tasks.find(x=>x.id===id),target=$('task-detail');
    const signature=JSON.stringify([t,state.connection.status,stale]);if(signature===detailSignature)return;detailSignature=signature;
    const restoreStop=target.contains(document.activeElement)&&document.activeElement?.dataset.liveAction;
    target.replaceChildren();if(!t){target.append(node('p','','This task is no longer available.'));return;}
    $('task-dialog-title').textContent=t.title;target.append(badge(t.status));const grid=node('dl','detail-grid');
    const fields=[['Project',project(t.project_id)?.name||'Unknown'],['Agent',role(t.role)?.label||t.role],['Configured model',t.model||'Not recorded'],['Reasoning',t.reasoning||'Not recorded'],['Created',date(t.created_at)],['Updated',date(t.updated_at)],['Thread',t.thread_id||'Not observed'],['Turn',t.turn_id||'Not observed']];fields.forEach(([k,v])=>grid.append(node('dt','',k),node('dd','',v)));target.append(grid);
    if(t.blocker)target.append(node('p','form-error',`Blocker: ${t.blocker}`));
    if(t.error)target.append(node('p','form-error',t.error));
    const plan=node('section','detail-section');plan.append(node('h3','','Live plan'));if(t.plan?.length){const list=node('ol','plan');t.plan.forEach(s=>{const item=node('li','',s.step);item.append(node('span','subtext',s.status||'Status not recorded'));list.append(item);});plan.append(list);}else plan.append(node('p','','No plan steps have been reported by Codex.'));target.append(plan);
    plan.append(node('p','subtext','Plan labels are withheld to keep model-authored content out of the dashboard. Step counts and statuses are live.'));
    const usage=node('section','detail-section');usage.append(node('h3','','Execution evidence'));usage.append(node('p','',t.usage?`Observed tokens: ${number(t.usage.total_tokens)} total; ${number(t.usage.input_tokens)} input, ${number(t.usage.cached_input_tokens)} cached input, ${number(t.usage.output_tokens)} output. Reasoning output: ${number(t.usage.reasoning_output_tokens)}.`:'Usage has not been observed. Cost remains unknown without a supported model and pricing basis.'));usage.append(node('p','','A completed turn does not establish acceptance, passing tests or release approval. These checks are not supplied by this live event feed.'));target.append(usage);
    if(active.has(t.status)){const actions=node('div','dialog-actions'),stop=button('Stop run',()=>interrupt(t,stop),'danger');stop.dataset.liveAction='true';stop.disabled=state.connection.status!=='connected';actions.append(stop);target.append(actions);if(restoreStop&&!stop.disabled)stop.focus();}
  }
  async function interrupt(task, b){await perform(b,`/api/tasks/${encodeURIComponent(task.id)}/interrupt`,{},'Stop requested. Waiting for Codex to confirm the run state.');}
  async function submit(event,path){event.preventDefault();const form=event.currentTarget;if(!form.reportValidity())return;const b=form.querySelector('[type="submit"]'),error=form.querySelector('.form-error');if(path==='/api/tasks'&&(stale||state?.connection.status!=='connected')){error.textContent='Refresh the workspace and restore the Codex connection before starting a run.';return;}const body=Object.fromEntries(new FormData(form));Object.keys(body).forEach(k=>body[k]=body[k].trim());if(Object.values(body).some(v=>!v)){error.textContent='Complete all fields with more than whitespace.';return;}b.disabled=true;error.textContent='';try{await request(path,body);form.closest('dialog').close();form.reset();announce(path==='/api/projects'?'Project added.':'Run submitted.');await refresh();}catch(e){error.textContent=e.message;}finally{b.disabled=false;}}
  $('add-project').addEventListener('click',openProject);$('start-run').addEventListener('click',openRun);$('retry').addEventListener('click',refresh);
  $('refresh-files').addEventListener('click',loadFiles);$('file-search').addEventListener('input',renderFiles);$('refresh-git').addEventListener('click',loadGit);$('confirm-publish').addEventListener('click',publishCommits);
  $('project-form').addEventListener('submit',e=>submit(e,'/api/projects'));$('run-form').addEventListener('submit',e=>submit(e,'/api/tasks'));$('run-form').elements.role.addEventListener('change',()=>{preferredRole=$('run-form').elements.role.value;modelHint();});
  ['project-filter','status-filter','role-filter'].forEach(id=>$(id).addEventListener('change',()=>state&&render()));$('search').addEventListener('input',()=>state&&render());
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.view;updateView();}));
  document.querySelectorAll('dialog').forEach(dialog=>{
    dialog.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>dialog.close()));
    dialog.addEventListener('close',()=>{if(dialog.id==='task-dialog')detailId=null;dialog.returnFocus?.focus();});
    // Native modal dialogs handle Escape and inert the page; explicitly wrap Tab for keyboard users.
    dialog.addEventListener('keydown',e=>{if(e.key!=='Tab')return;const controls=[...dialog.querySelectorAll('button,input,textarea,select,a[href]')].filter(x=>!x.disabled&&!x.hidden);if(!controls.length){e.preventDefault();return;}const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});
  });
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){refresh();checkGitFreshness();}});
  setInterval(()=>{if(!document.hidden){refresh();checkGitFreshness();}},3000);loadTheme();refresh();
})();
