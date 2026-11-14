// All user/model content is rendered as text. Only known source URLs become links.
(() => {
  const el = (id) => document.getElementById(id);
  const runs = new Map();
  const starting = new Set();
  let currentSite = null;
  let pollTimer;
  let revision = 0;
  const terminal = new Set(['complete', 'partial', 'failed', 'cancelled']);
  const roles = {'crash-analyst':'Crash evidence', 'site-analyst':'Aerial context', 'guidance-researcher':'Safety guidance', lead:'Lead investigator'};
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  };
  async function api(action, site, fields={}) {
    const response = await fetch(`/api/${action}`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({site:site.name, ...fields}),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || 'The investigation request could not complete.');
    return body;
  }
  function safeLink(source) {
    try {
      const url = new URL(source.url);
      if (url.protocol !== 'https:' || !['data.ca.gov','highways.dot.gov','vexceldata.com'].includes(url.hostname)) return null;
      const a = node('a', 'Open source');
      a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer';
      return a;
    } catch { return null; }
  }
  function sourceDetails(source) {
    const box = node('details', undefined, 'source-card');
    box.append(node('summary', source.kind === 'statistic' ? source.text : source.title));
    if (source.record) {
      const r = source.record;
      box.append(node('p', `${r.road} / ${r.cross} · ${r.location_group}`));
      box.append(node('p', `Offset: ${r.offset_ft === null ? 'unknown' : `${r.offset_ft} ft`} · Injured: ${r.injured ?? 'unknown'} · Killed: ${r.killed ?? 'unknown'} · Lighting: ${r.light ?? 'unknown'} · Involved with: ${r.involved_with ?? 'unknown'}`, 'note'));
    } else if (source.kind !== 'statistic') box.append(node('p', source.text));
    if (source.observations) {
      const ul = node('ul');
      source.observations.forEach(text => ul.append(node('li', text)));
      box.append(ul, node('p', source.uncertainties.join(' '), 'note'), node('p', `Capture date: ${source.capture_date}. ${source.extent}.`, 'note'));
    }
    if (source.prerequisites) box.append(node('p', `Before applying: ${source.prerequisites}`, 'note'));
    if (source.basis) box.append(node('p', `${source.basis}. Reviewed ${source.reviewed_at}.`, 'note'));
    if (source.period) box.append(node('p', `Source period: ${source.period}`, 'note'));
    const link = safeLink(source);
    if (link) box.append(link);
    return box;
  }
  function citationList(ids, sources) {
    const list = node('div', undefined, 'finding-sources');
    [...new Set(ids)].forEach(id => { if (sources[id]) list.append(sourceDetails(sources[id])); });
    return list;
  }
  function labeled(parent, label, text) {
    const p = node('p'); p.append(node('strong', `${label} `), document.createTextNode(text)); parent.append(p);
  }
  function clear() {
    ['agent-progress','investigation-summary','investigation-findings','investigation-limits','evidence-library','activity-list','specialist-notes','followup-answers'].forEach(id => el(id).replaceChildren());
    ['agent-progress','investigation-evidence','investigation-activity','followup-section','cancel-analysis','refresh-analysis'].forEach(id => el(id).hidden=true);
    delete el('evidence-library').dataset.key;
    el('investigation-badge').textContent='Ready';
    el('investigation-status').textContent='Analysis runs only when requested. Allow about one to three minutes.';
    el('analyze').disabled=starting.has(currentSite?.name);
    el('analyze').hidden=false;
    el('followup-question').value='';
  }
  function render(run) {
    if (run.site !== currentSite?.name) return;
    const busy = !terminal.has(run.status) || run.followup_running;
    el('analyze').hidden=!!run.report;
    el('analyze').disabled=busy || starting.has(run.site);
    el('refresh-analysis').hidden=!terminal.has(run.status);
    el('refresh-analysis').disabled=busy;
    el('cancel-analysis').hidden=!busy;
    el('investigation-badge').textContent=run.cached ? 'Cached report' : ({running:'Investigating', complete:'Report ready',partial:'Partial results',failed:'Could not finish',cancelled:'Cancelled'}[run.status]);
    el('investigation-status').textContent=`${run.message} · Started ${new Date(run.created_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}`;
    const progress = el('agent-progress'); progress.hidden=false; progress.replaceChildren();
    for (const [role,label] of Object.entries(roles)) {
      const events=run.events.filter(e=>e.role===role);
      const done=!!run.artifacts[role] || (role==='lead' && !!run.report);
      const status=done?'Complete':events.length?(busy?'Working':'Stopped'):'Waiting';
      const card=node('div', undefined, `agent-step ${done?'done':''}`);
      card.append(node('strong',label),node('span',status)); progress.append(card);
    }
    el('investigation-summary').textContent=run.report?.summary || '';
    const findings=el('investigation-findings'); findings.replaceChildren();
    for (const [index,finding] of (run.report?.findings || []).entries()) {
      const article=node('article', undefined, 'finding');
      article.append(node('div', `${index+1} · ${finding.category}`, 'eyebrow'), node('h3',finding.title), node('p',finding.concern));
      labeled(article,'Next check:',finding.next_check);
      labeled(article,'Possible explanation:',finding.hypothesis);
      labeled(article,'Option to evaluate:',finding.candidate_option);
      labeled(article,'Before deciding:',finding.prerequisites);
      article.append(node('p',`${finding.strength[0].toUpperCase()+finding.strength.slice(1)} evidence · ${finding.strength_reason}`,'note'));
      article.append(citationList([...finding.evidence_ids,...finding.guidance_ids], run.sources));
      findings.append(article);
    }
    const limits=el('investigation-limits'); limits.replaceChildren();
    if (run.report) {
      limits.append(node('strong','What remains uncertain'));
      const ul=node('ul');run.report.limitations.forEach(t=>ul.append(node('li',t)));limits.append(ul);
    } else if (terminal.has(run.status)) limits.append(node('p','No final AI report was accepted. Source facts and any completed specialist notes remain available below.'));
    el('investigation-evidence').hidden=false;
    const library=el('evidence-library');
    // Preserve open source details across polling while the source set is unchanged.
    const sourceKey=run.id+':'+Object.keys(run.sources).join(',');
    if (library.dataset.key!==sourceKey) {
      library.replaceChildren();library.dataset.key=sourceKey;
      Object.values(run.sources).forEach(source=>library.append(sourceDetails(source)));
    }
    el('investigation-activity').hidden=false;
    el('investigation-usage').textContent=`${run.usage.model_calls}/${run.usage.max_calls} investigation model calls · ${run.usage.input_tokens.toLocaleString()} input tokens · ${run.usage.output_tokens.toLocaleString()} output tokens. Notes are AI-generated working artifacts; the final report is checked separately. Reports stay in this server’s memory for up to one hour.`;
    const activity=el('activity-list');activity.replaceChildren();
    run.events.forEach(event=>activity.append(node('li',`${event.seconds}s · ${roles[event.role] || event.role}: ${event.text}`)));
    const notes=el('specialist-notes');notes.replaceChildren();
    Object.entries(run.artifacts).forEach(([role,artifact])=>{
      const details=node('details');details.append(node('summary',`${roles[role] || role} · ${artifact.path}`),node('pre',artifact.text));notes.append(details);
    });
    el('followup-section').hidden=!run.report;
    el('ask-followup').disabled=busy || run.followups.length>=5 || run.status==='cancelled';
    const answers=el('followup-answers');answers.replaceChildren();
    run.followups.forEach(answer=>{
      const div=node('article',undefined,'followup-answer');
      div.append(node('strong',answer.question),node('p',answer.answer || (answer.status==='cancelled'?'Cancelled.':'Reviewing this investigation’s evidence…')));
      if(answer.evidence_ids)div.append(citationList(answer.evidence_ids,run.sources));answers.append(div);
    });
  }
  function schedule(run, site, token) {
    clearTimeout(pollTimer);
    if (token!==revision || (terminal.has(run.status)&&!run.followup_running)) return;
    pollTimer=setTimeout(async()=>{
      try {
        const next=await api('investigation',site,{run_id:run.id});
        runs.set(site.name,next);
        if(token===revision){render(next);schedule(next,site,token);}
      } catch(error) {
        if(token===revision){el('investigation-status').textContent=error.message+' Select Analyze to reconnect.';el('analyze').hidden=false;el('analyze').disabled=false;}
      }
    },1500);
  }
  window.investigationSelect = (site) => {
    if (currentSite?.name === site?.name) return;
    currentSite=site;revision++;clearTimeout(pollTimer);
    el('investigator').hidden=!site;
    if (!site) return;
    el('investigation-site').textContent=site.name;
    clear();
    const run=runs.get(site.name);
    if(run){render(run);schedule(run,site,revision);}
  };
  async function start(refresh=false) {
    if(!currentSite || starting.has(currentSite.name))return;
    const site=currentSite, token=revision;
    starting.add(site.name);el('analyze').disabled=true;el('refresh-analysis').disabled=true;
    el('investigation-status').textContent='Starting investigation…';
    try {
      const run=await api('investigate',site,{refresh});runs.set(site.name,run);
      starting.delete(site.name);
      if(token===revision){render(run);schedule(run,site,token);}
    } catch(error) {
      if(token===revision){el('investigation-status').textContent=error.message;el('analyze').disabled=false;el('refresh-analysis').disabled=false;}
    } finally {starting.delete(site.name);}
  }
  el('analyze').addEventListener('click',()=>start());
  el('refresh-analysis').addEventListener('click',()=>start(true));
  el('cancel-analysis').addEventListener('click',async()=>{
    const site=currentSite, run=runs.get(site?.name), token=revision;
    if(!run)return;
    try {const next=await api('cancel',site,{run_id:run.id});runs.set(site.name,next);if(token===revision){render(next);schedule(next,site,token);}}
    catch(error){if(token===revision)el('investigation-status').textContent=error.message;}
  });
  el('followup-form').addEventListener('submit',async event=>{
    event.preventDefault();const site=currentSite,run=runs.get(site?.name),token=revision;
    if(!run)return;
    el('ask-followup').disabled=true;
    try {const next=await api('followup',site,{run_id:run.id,question:el('followup-question').value});runs.set(site.name,next);if(token===revision){el('followup-question').value='';render(next);schedule(next,site,token);}}
    catch(error){if(token===revision){el('investigation-status').textContent=error.message;el('ask-followup').disabled=false;}}
  });
  window.investigationSelect(typeof selected==='undefined'?null:selected);
})();
