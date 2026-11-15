/* Area searches own their immutable boundary and history; map browsing is free. */
(() => {
  const defaults = {
    street: 'Find promising locations to reduce traffic-related emissions while preserving access.',
    water: 'Find promising stormwater improvements with useful runoff-interception potential.',
  };
  const areaLayer = L.layerGroup().addTo(map), candidateLayer = L.layerGroup().addTo(map);
  const colors = ['#b4e6a7', '#83cddd', '#ebc68b'];
  let mode = planningMode, bounds = null, search = null, generation = 0;
  let posting = false, selecting = false, pollTimer = null, expiryTimer = null, request = null;
  let freshnessItems = [];
  const post = (path, body) => json(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const el = (tag, text, className) => {
    const node = document.createElement(tag); if(text !== undefined) node.textContent = text;
    if(className) node.className = className; return node;
  };
  const button = (text, fn) => { const node=el('button',text); node.type='button'; node.addEventListener('click',fn); return node; };
  const running = () => posting || search?.status === 'running';
  const expiresAt = c => typeof c.expiresAt === 'number' ? (c.expiresAt < 1e12 ? c.expiresAt*1000 : c.expiresAt) : Date.parse(c.expiresAt);
  // A saved location remains a choice after its traffic reading stops being
  // current. Only old tombstones without their location are unavailable.
  const unavailable = c => c.available === false || !Array.isArray(c.center) || c.center.length!==2 || !c.center.every(Number.isFinite);
  function snapshotText(batch) {
    const at = batch.snapshotAt || batch.created;
    const date = new Date(at), timestamp = Number.isFinite(date.getTime())
      ? ` · traffic retrieved ${date.toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}` : '';
    const stale = batch.evidenceFreshness === 'snapshot' || (batch.candidates ?? []).some(c=>Number.isFinite(expiresAt(c)) && Date.now() >= expiresAt(c));
    return `Saved search${timestamp}. ${stale ? 'Traffic may have changed; your feedback and choices stay available.' : 'These readings describe conditions at search time.'} Refresh map traffic to check current conditions.`;
  }
  function updateFreshness() {
    clearTimeout(expiryTimer);
    for(const {batch,node} of freshnessItems) node.textContent=snapshotText(batch);
    const nextExpiry=Math.min(...freshnessItems.flatMap(({batch})=>batch.candidates ?? []).map(expiresAt).filter(at=>Number.isFinite(at) && at>Date.now()));
    // Update just the notice: never rebuild a card under someone reading it.
    if(Number.isFinite(nextExpiry)) expiryTimer=setTimeout(updateFreshness,Math.max(1,nextExpiry-Date.now()+20));
  }
  function savedId() { try { return localStorage.getItem(`planning-scout-${mode}`); } catch { return null; } }
  function remember() { try { localStorage.setItem(`planning-scout-${mode}`,search.id); } catch {} }
  function cancelRemote(id,runId) { if(id && runId) post('/api/scouts/cancel',{id,runId}).catch(()=>{}); }
  function invalidate(cancel=true) {
    ++generation; clearTimeout(pollTimer); clearTimeout(expiryTimer); request?.abort(); request=null;
    if(cancel && search?.status === 'running') cancelRemote(search.id,search.runId);
    posting=false; selecting=false;
    return generation;
  }
  function visibleBounds() {
    const b=map.getBounds(), values=[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()];
    if(values.some(v=>!Number.isFinite(v)) || values[2]-values[0]>.1 || values[3]-values[1]>.1)
      throw new Error('Zoom in to a neighborhood, then use the current map area. Searches are limited to 0.1° in each direction.');
    return values;
  }
  function paintArea() {
    areaLayer.clearLayers(); $('scout-view-area').hidden=!bounds;
    $('scout-area').textContent=bounds?'Update area':'Use current map area';
    if(!bounds) { $('scout-area-label').textContent='Search area: current map view.'; return; }
    const [w,s,e,n]=bounds;
    L.rectangle([[s,w],[n,e]],{color:'#d4e6bf',weight:2,dashArray:'7 6',fillOpacity:.025,interactive:false}).addTo(areaLayer);
    const width=(e-w)*111.32*Math.cos((s+n)/2*Math.PI/180),height=(n-s)*111.32;
    $('scout-area-label').textContent=`Fixed search area · ${width.toFixed(1)} × ${height.toFixed(1)} km`;
    // Screen-reader explanation of what "fixed" means; sighted users see the outlined area stay put.
    $('scout-area-label').append(el('span',' Panning the map keeps this area. Use Update area to change it.','visually-hidden'));
  }
  function setArea() {
    try {
      const next=visibleBounds(); invalidate(); bounds=next; search=null;
      paintArea(); render(); $('scout-status').textContent='Search area updated. Enter a goal and find locations.';
    } catch(error) { $('scout-status').textContent=error.message; }
  }
  function focus(candidate) {
    if(candidate.geometry) {
      const layer=L.geoJSON(candidate.geometry), extent=layer.getBounds();
      if(extent.isValid()) { map.fitBounds(extent,{padding:[55,55],maxZoom:18}); return; }
    }
    if(candidate.center) map.setView([candidate.center[1],candidate.center[0]],17);
  }
  function factText(fact) {
    const value = fact.value === undefined || fact.value === null ? '' : typeof fact.value === 'object' ? JSON.stringify(fact.value) : String(fact.value);
    return `${fact.label || fact.id || 'Evidence'}${value ? `: ${value}${fact.unit ? ` ${fact.unit}` : ''}` : ''}`;
  }
  function evidence(candidate) {
    const details=el('section',undefined,'scout-evidence'); details.append(el('h4','Evidence and source limits'));
    const facts=el('ol');
    for(const fact of candidate.evidence ?? []) {
      const item=el('li');item.id=`scout-evidence-${candidate.id}-${fact.id}`;item.append(el('strong',factText(fact)));
      const source=fact.source ?? {};
      if(source.provider || source.label) item.append(el('p',source.provider || source.label));
      if(source.observed_at) item.append(el('p',`Observed: ${source.observed_at}`));
      if(source.retrieved_at) item.append(el('p',`Retrieved: ${source.retrieved_at}`));
      if(fact.method) item.append(el('p',fact.method));
      if(fact.note) item.append(el('p',fact.note));
      if(source.url && /^https?:\/\//i.test(source.url)) {
        const link=el('a','View source ↗');link.href=source.url;link.target='_blank';link.rel='noopener';item.append(link);
      }
      facts.append(item);
    }
    details.append(facts);
    if(candidate.provenance?.method) details.append(el('p',candidate.provenance.method));
    if(candidate.provenance?.retrievedAt) details.append(el('p',`Retrieved ${new Date(candidate.provenance.retrievedAt).toLocaleString()}`));
    return details;
  }
  async function choose(candidate) {
    if(running() || selecting || unavailable(candidate)) return;
    const current=generation, id=search.id; selecting=true; render();
    $('scout-status').textContent='Saving this location and its investigation…';
    try {
      const result=await post('/api/scouts/select',{id,candidateId:candidate.id});
      if(current!==generation || search?.id!==id) return;
      if(result.search) search=result.search;
      selecting=false; render();
      map.fire('scoutselect',{project:result.project,candidate:result.candidate || candidate});
      $('scouting').open=false; $('scout-heading').textContent=`Locations · ${candidate.label || 'selected'}`;
      $('scout-status').textContent='Location selected. Review the site brief and ask the agent to develop a concept.';
    } catch(error) { if(current===generation) { selecting=false;render();$('scout-status').textContent=error.message; } }
  }
  function card(candidate,index,currentBatch,batch) {
    const missingLocation=unavailable(candidate), article=el('article',undefined,'scout-card');
    article.id=`scout-candidate-${candidate.id}`;
    const title=el('h3');title.append(el('span',String(index+1),'scout-number'),el('span',candidate.label || 'Previous traffic opportunity'));article.append(title);
    if(missingLocation) {
      article.append(el('p',candidate.resumeNotice || 'This older search did not save its location. Run a new search to recover a selectable place.','scout-readiness'));
      if(search?.selected?.candidateId===candidate.id) article.append(button('Open selected project',()=>map.fire('scoutselect',{project:{id:search.selected.projectId,snapshot:{workflow:mode}}})));
      return article;
    }
    const investigation=el('details',undefined,'scout-investigation');investigation.open=false;
    investigation.append(el('summary','Investigation and evidence'));
    const citations=evidence(candidate), facts=new Map((candidate.evidence ?? []).map((fact,index)=>[fact.id,{fact,index}]));
    function citedParagraph(value,ids=[]) {
      const paragraph=el('p',value);
      for(const id of ids.filter(id=>facts.has(id))) {
        const {fact,index}=facts.get(id),reference=button(`[${index+1}]`,()=>{
          investigation.open=true;document.getElementById(`scout-evidence-${candidate.id}-${id}`)?.scrollIntoView({block:'nearest'});
        });
        reference.className='scout-citation';reference.title=fact.label || id;reference.setAttribute('aria-label',`Inspect evidence: ${fact.label || id}`);paragraph.append(reference);
      }
      return paragraph;
    }
    // Saved searches can predate structured feedback. Their actual evidence and
    // next action still provide a useful card when specialist review is absent.
    const feedback=candidate.feedback ?? {}, street=mode==='street';
    article.append(el('h4',feedback.headline || (street?'Investigate this slow approach':'Explore this collection area'),'scout-feedback-title'));
    article.append(citedParagraph(feedback.observation || candidate.environmental?.summary ||
      (street?'Use this mapped location to check traffic flow and nearby access.':'Use this mapped location to trace where rainwater collects.'),feedback.factIds || []));
    const relevance=feedback.relevance || candidate.reason;
    if(relevance) article.append(el('h4','Why consider it'),el('p',relevance));
    const findings=batch.reviewStale ? [] : (batch.review?.findings ?? []).filter(finding=>
      finding.candidate_id===candidate.id && finding.text && finding.fact_ids?.length && finding.fact_ids.every(id=>facts.has(id)));
    if(findings.length) {
      const assessment=el('section',undefined,'scout-assessment');assessment.append(el('h4','Agent assessment'));
      for(const finding of findings) assessment.append(citedParagraph(finding.text,finding.fact_ids));
      article.append(assessment);
    }
    const nextStep=el('section',undefined,'scout-next-step');
    nextStep.append(el('h4','Start here'),el('p',feedback.nextStep || candidate.direction ||
      (street?'Choose this location, then check the slow approach, crossings and property entrances before proposing a change.':
        'Choose this location, then trace the nearest inlet and check space for planting before sizing a rain garden.')));
    article.append(nextStep);
    const tradeoff=feedback.tradeoff || candidate.disruption || candidate.feasibility;
    if(tradeoff) article.append(el('h4','What to weigh'),el('p',tradeoff));
    if(!candidate.propertyId && candidate.center?.every(Number.isFinite))
      investigation.append(el('p',`Map location ${index+1} · ${candidate.center[1].toFixed(5)}, ${candidate.center[0].toFixed(5)}`,'scout-basis'));
    investigation.append(el('p','Evidence availability is reported separately and does not raise a location’s priority.','scout-basis'));
    if(candidate.environmental?.basis) investigation.append(el('p',candidate.environmental.basis,'scout-basis'));
    if(candidate.readiness?.summary) investigation.append(el('h4','Evidence available'),el('p',candidate.readiness.summary));
    const considerations=el('dl',undefined,'scout-considerations');
    considerations.append(el('dt','Feasibility'),el('dd',candidate.feasibility || 'Not yet established.'),el('dt','Disruption'),el('dd',candidate.disruption || 'Requires site investigation.'));
    investigation.append(considerations);
    if(candidate.readiness?.missing?.length) investigation.append(el('h4','Data still needed'),el('p',candidate.readiness.missing.join('; ')));
    investigation.append(citations);article.append(investigation);
    const actions=el('div',undefined,'scout-actions');
    const chosen=search?.selected?.candidateId===candidate.id;
    const select=button(chosen?'Open selected site':'Choose this location',()=>choose(candidate));
    select.disabled=running() || selecting;actions.append(select,button('View on map',()=>focus(candidate)));article.append(actions);
    if(candidate.geometry && currentBatch) {
      L.geoJSON(candidate.geometry,{style:{color:colors[index%3],weight:4,fillOpacity:.2},
        pointToLayer:(_feature,latlng)=>L.circleMarker(latlng,{color:colors[index%3],radius:8,weight:3})}).addTo(candidateLayer);
      if(candidate.center) {
        const marker=L.marker([candidate.center[1],candidate.center[0]],{icon:L.divIcon({className:'scout-map-number',html:String(index+1),iconSize:[28,28]})});
        marker.bindTooltip(el('span',candidate.label || 'Opportunity'));
        marker.on('click',()=>{ $('scouting').open=true;article.scrollIntoView({block:'nearest',behavior:'smooth'}); }); marker.addTo(candidateLayer);
      }
    }
    return article;
  }
  function render() {
    clearTimeout(expiryTimer);freshnessItems=[];candidateLayer.clearLayers(); const output=$('scout-results');output.replaceChildren();
    const busy=running();$('scout-start').disabled=busy || selecting;$('scout-cancel').hidden=!busy;
    const batches=search?.batches ?? [], total=batches.reduce((n,b)=>n+(b.candidates?.length || 0),0);
    const selectable=batches.reduce((n,b)=>n+(b.candidates ?? []).filter(c=>!unavailable(c)).length,0);
    output.setAttribute('data-selectable-count',String(selectable));
    $('scout-more').hidden=!search || !batches.length || !!search.exhausted || !!batches.at(-1)?.exhausted;
    $('scout-more').disabled=busy || selecting;
    const events=search?.events ?? []; $('scout-activity').hidden=!events.length;
    $('scout-events').replaceChildren();
    for(const event of events.slice(-12)) $('scout-events').append(el('li',event.summary || event.message || event.title || `${event.specialist || 'Agent'} · ${event.stage || event.status || 'working'}`));
    if(!search) { $('scout-status').textContent=''; return; }
    if(busy) $('scout-status').textContent='Investigating the search area, checking sources and comparing distinct opportunities…';
    else if(search.status==='ready') $('scout-status').textContent=selectable ? `${selectable} researched ${selectable===1?'location':'locations'} across ${batches.length} ${batches.length===1?'search':'searches'}. Choose a location to continue.`
      : total ? 'This older search did not retain selectable locations. Find locations again, or pick a spot directly.'
      : 'No locations found with the available data. Try a smaller or nearby area, or pick a spot directly.';
    else $('scout-status').textContent=search.error || search.message || `Search ${search.status}. Previous research remains below.`;
    for(let index=batches.length-1;index>=0;index--) {
      const batch=batches[index], latest=index===batches.length-1;
      const section=el(latest?'section':'details',undefined,'scout-batch');
      if(!latest) section.append(el('summary',`Earlier locations · search ${index+1}`));
      else section.append(el('h3',batches.length>1?`More locations · search ${index+1}`:'Researched locations','scout-batch-title'));
      const goal=batch.feedbackGoal || search.goal;
      if(goal) section.append(el('p',`Your goal: ${goal}`,'scout-goal-context'));
      if(batch.summary) section.append(el('p',batch.summary));
      if(mode==='street' && (batch.candidates ?? []).some(c=>!unavailable(c))) {
        const notice=el('p',snapshotText(batch),'scout-snapshot');
        freshnessItems.push({batch,node:notice});section.append(notice);
      }
      if(batch.goalChecks?.length) {
        const checks=el('details',undefined,'scout-goal-checks');checks.open=false;
        checks.append(el('summary','Checks for your goal'));
        const items=el('ul');for(const check of batch.goalChecks) items.append(el('li',check));
        checks.append(items);section.append(checks);
      }
      if(batch.methodology || batch.warnings?.length || batch.agentStatus==='partial') {
        const method=el('details',undefined,'scout-method');method.open=false;
        method.append(el('summary','How locations were compared'));
        if(batch.methodology) method.append(el('p',batch.methodology,'scout-basis'));
        if(batch.agentStatus==='partial') method.append(el('p','The full agent review could not finish. Available specialist findings and source-based guidance are shown for each location.'));
        for(const warning of batch.warnings ?? []) method.append(el('p',warning,'scout-notice'));
        section.append(method);
      }
      if(!batch.candidates?.length) section.append(el('p',batch.resumeNotice || 'Try a smaller or nearby map area, or pick a spot directly to investigate a location you know.'));
      for(const [number,candidate] of (batch.candidates ?? []).entries()) section.append(card(candidate,number,latest,batch));
      output.append(section);
    }
    updateFreshness();
  }
  function schedulePoll(id,current) {
    clearTimeout(pollTimer);
    pollTimer=setTimeout(async()=>{
      if(current!==generation || search?.id!==id) return;
      request=new AbortController();
      try {
        const result=await json(`/api/scouts?id=${encodeURIComponent(id)}`,{signal:request.signal});
        if(current!==generation || result.workflow!==mode || search?.id!==id) return;
        search=result;render();if(search.status==='running') schedulePoll(id,current);
      } catch(error) {
        if(current!==generation || error.name==='AbortError') return;
        $('scout-status').textContent=`Connection interrupted. Retrying the saved search. ${error.message}`;
        schedulePoll(id,current);
      }
    },1500);
  }
  async function start(more=false) {
    if(selecting || running()) return;
    let next;
    try { next=more?search.bounds:bounds || visibleBounds(); } catch(error) { $('scout-status').textContent=error.message;return; }
    const goal=$('scout-goal').value.trim();if(!goal) { $('scout-status').textContent='Enter an environmental planning goal.';return; }
    const old=more?search:null, current=invalidate();bounds=next;search=old;posting=true;paintArea();render();
    $('scout-status').textContent='Starting a bounded location investigation…';
    try {
      const result=await post('/api/scouts',{workflow:mode,goal,bounds, ...(more?{searchId:old.id}:{})});
      // Do not abort POST: if the server accepted it, cancel the returned run
      // even when its response arrived after a change of area or workflow.
      if(current!==generation || result.workflow!==mode) { if(result.status==='running')cancelRemote(result.id,result.runId);return; }
      posting=false;search=result;remember();render();
      if(search.status==='running') schedulePoll(search.id,current);
    } catch(error) { if(current===generation) { posting=false;render();$('scout-status').textContent=error.message; } }
  }
  async function restore() {
    const id=savedId(),current=generation;if(!id)return;
    request=new AbortController();
    try {
      const value=await json(`/api/scouts?id=${encodeURIComponent(id)}`,{signal:request.signal});
      if(current!==generation || value.workflow!==mode)return;
      search=value;bounds=value.bounds;$('scout-goal').value=value.goal;paintArea();render();
      if(value.status==='running')schedulePoll(id,current);
    } catch(error) { if(current===generation && error.name!=='AbortError') $('scout-status').textContent='Saved search could not be opened. Start a new area investigation.'; }
  }
  $('scout-form').addEventListener('submit',event=>{event.preventDefault();start();});
  $('scout-more').addEventListener('click',()=>start(true));
  $('scout-area').addEventListener('click',setArea);
  $('scout-view-area').addEventListener('click',()=>{if(bounds)map.fitBounds([[bounds[1],bounds[0]],[bounds[3],bounds[2]]],{padding:[35,35]});});
  $('scout-cancel').addEventListener('click',()=>{invalidate();if(search)search={...search,status:'canceled'};render();$('scout-status').textContent='Search canceled. Previously completed locations remain available.';});
  $('scout-goal').addEventListener('input',()=>{
    if(!search && !posting)return;
    invalidate();search=null;render();$('scout-status').textContent='Goal changed. Find locations to investigate this request.';
  });
  map.on('plannerworkspace',({mode:next})=>{
    if(next===mode)return;invalidate();mode=next;search=null;bounds=null;
    $('scout-goal').value=defaults[mode];$('scouting').open=true;$('scout-heading').textContent='Find improvement opportunities';paintArea();render();restore();
  });
  $('scout-goal').value=defaults[mode];paintArea();render();restore();
})();
