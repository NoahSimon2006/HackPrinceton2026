/* Open a local 3D scene only for the validated footprint currently shown in 2D. */
(() => {
  const dialog=$('concept-scene-dialog'), open=$('open-concept-scene');
  let displayed=null, generation=0, controller=null, renderer=null, returnFocus=null, mode='proposed';
  const statusNames={draft:'Draft concept',conditional:'Conditional concept',recommended:'Recommended',tested:'Tested, eligible',rejected:'Tested, rejected'};
  const buttonIds=['existing','proposed','reset','top','left','right','zoom-in','zoom-out'];
  const textElement=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node;};
  const number=value=>Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:3}):'Not assessed';
  function controls(enabled) {
    for(const name of buttonIds)$(`concept-scene-${name}`).disabled=!enabled;
    $('concept-scene-context').disabled=!enabled;
  }
  function cleanup() {
    ++generation;controller?.abort();controller=null;
    renderer?.dispose();renderer=null;
    $('concept-scene-stage').replaceChildren();controls(false);
  }
  function closeView() {
    const active=dialog.open || Boolean(returnFocus);
    cleanup();
    if(dialog.open)dialog.close();
    const target=returnFocus;returnFocus=null;
    if(!active)return;
    if(target?.isConnected && !target.disabled && (!target.getClientRects || target.getClientRects().length))target.focus({preventScroll:true});
    else if(!open.disabled && !open.hidden)open.focus({preventScroll:true});
  }
  function setStatus(message,error=false) {
    $('concept-scene-status').textContent=message;
    $('concept-scene-status').setAttribute('data-error',String(error));
  }
  function setMode(next) {
    mode=next;renderer?.setMode(next);
    $('concept-scene-existing').setAttribute('aria-pressed',String(next==='existing'));
    $('concept-scene-proposed').setAttribute('aria-pressed',String(next==='proposed'));
    $('concept-scene-mode-label').textContent=next==='existing'?'Existing mapped context':'Proposed footprint';
    $('concept-scene-mode-note').textContent=next==='existing'
      ? 'The intervention is hidden. The viewpoint and surrounding context stay the same. Ground and building heights are conceptual.'
      : 'The footprint matches the selected 2D design. This view illustrates form; it does not add an engineering assessment.';
  }
  function identity(value,descriptor) {
    const p=descriptor.proposal, id=value?.identity;
    return value?.schemaVersion===1 && value.units==='m' && id?.projectId===descriptor.projectId &&
      id.siteId===p.site_id && id.workflow===p.workflow && id.revision===p.revision &&
      id.inputRevision===p.input_revision && id.inputHash===p.input_hash &&
      id.geometryId===p.proposed_geometry_ids?.[0] && Array.isArray(value.features) &&
      value.features.some(feature=>feature.kind==='intervention') && Number.isFinite(value.areaM2);
  }
  function fill(data,descriptor) {
    const p=descriptor.proposal;
    $('concept-scene-title').textContent=p.workflow==='water'?'Stormwater concept':String(p.design?.new_use || 'Street design').replaceAll('_',' ');
    $('concept-scene-identity').textContent=`${descriptor.historical?'Earlier saved design · ':''}Revision ${p.revision} · ${p.input_hash.slice(0,8)}`;
    $('concept-scene-verdict').textContent=statusNames[data.status] || 'Conceptual design';
    $('concept-scene-verdict').setAttribute('data-status',data.status);
    $('concept-scene-stale').hidden=!descriptor.stale && !descriptor.historical;
    $('concept-scene-stale').textContent=descriptor.historical?'Earlier saved design · read-only inspection. The current project is unchanged.':'Saved reference · inputs or evidence have changed. This view has not been reevaluated.';
    const metrics=$('concept-scene-metrics');metrics.replaceChildren(textElement('dt','Design footprint'),textElement('dd',`${number(data.areaM2)} m²`));
    for(const [id,label] of [['storage_volume','Ponding storage'],['direct_rain_volume','Rain onto treatment']]) {
      const metric=p.metrics?.find(item=>item.id===id);
      if(metric)metrics.append(textElement('dt',label),textElement('dd',`${number(metric.proposed)} ${metric.unit}`));
    }
    const date=typeof data.savedAt==='string'?Date.parse(data.savedAt):NaN;
    $('concept-scene-saved').textContent=Number.isFinite(date)
      ? `Saved evaluation · ${new Date(date).toISOString().replace('T',' ').replace(/\.\d{3}Z$/,' UTC')}. Opening 3D does not rerun it.`
      : 'Original save time unavailable. Opening 3D does not rerun the evaluation.';
    $('concept-scene-info').hidden=false;
    $('concept-scene-context-note').textContent=data.context?.message || 'Surrounding source geometry is unavailable for this saved design.';
    const heightNotes=[...new Set(data.features.filter(feature=>['building','intervention'].includes(feature.kind)).map(feature=>feature.heightBasis).filter(Boolean))];
    $('concept-scene-assumptions').replaceChildren(...[...heightNotes,...(data.assumptions ?? [])].map(value=>textElement('li',String(value))));
    const origin=data.origin ?? {};
    $('concept-scene-coordinates').textContent=`${origin.crs || 'Local metric coordinates'} · meters. Origin ${number(origin.easting)} E, ${number(origin.northing)} N. The same origin and camera are used in both views.`;
    $('concept-scene-sources').replaceChildren(...(data.context?.sources ?? []).map(value=>textElement('li',typeof value==='string'?value:[value.provider || value.source || value.label,value.collection,value.date].filter(Boolean).join(' · '))));
  }
  async function openView() {
    if(!displayed || open.disabled)return;
    cleanup();
    const descriptor=displayed, token=generation;
    controller=new AbortController();
    returnFocus=document.activeElement || open;
    if(!dialog.open)dialog.showModal();
    $('concept-scene-close').focus({preventScroll:true});
    $('concept-scene-retry').hidden=true;
    $('concept-scene-info').hidden=true;
    $('concept-scene-stage').setAttribute('aria-busy','true');
    setStatus('Building the selected design in local metric coordinates…');
    const p=descriptor.proposal;
    $('concept-scene-title').textContent='Selected design';
    $('concept-scene-identity').textContent=`Revision ${p.revision} · ${p.input_hash.slice(0,8)}`;
    $('concept-scene-stale').hidden=!descriptor.stale && !descriptor.historical;
    $('concept-scene-stale').textContent=descriptor.historical?'Earlier saved design · read-only inspection. The current project is unchanged.':'Saved reference · inputs or evidence have changed. This view has not been reevaluated.';
    const query=new URLSearchParams({projectId:descriptor.projectId,revision:String(p.revision),inputHash:p.input_hash,geometryId:p.proposed_geometry_ids[0]});
    try {
      const [data,module]=await Promise.all([json(`/api/concept-scene?${query}`,{signal:controller.signal}),import('/concept-scene-renderer.js')]);
      if(token!==generation || displayed!==descriptor || !dialog.open)return;
      if(!identity(data,descriptor))throw new Error('The saved scene does not match the selected footprint.');
      fill(data,descriptor);
      renderer=module.createConceptScene($('concept-scene-stage'),data,{onError(message){
        if(token!==generation || !dialog.open)return;
        setStatus(message || '3D rendering is unavailable. The 2D design is still available.',true);
        renderer?.dispose();renderer=null;controls(false);$('concept-scene-retry').hidden=false;
      }});
      $('concept-scene-context').checked=true;
      setMode('proposed');controls(true);
      setStatus(data.status==='rejected'?'Tested, rejected · inspect the geometry; this design is not recommended.':'Conceptual view ready · exact design footprint, illustrative surroundings.');
    } catch(error) {
      if(token!==generation || error.name==='AbortError')return;
      renderer?.dispose();renderer=null;controls(false);
      setStatus(`3D view unavailable: ${error.message} The 2D design remains available.`,true);
      $('concept-scene-retry').hidden=false;
    } finally {
      if(token===generation)$('concept-scene-stage').setAttribute('aria-busy','false');
    }
  }
  function updateDisplay(event) {
    closeView();
    displayed=event.proposal && !event.proposal.development_fixture && event.projectId && event.proposal.proposed_geometry_ids?.length
      ? {...event} : null;
    open.disabled=!displayed;
    $('concept-scene-entry').textContent=displayed
      ? `${event.historical?'Earlier design':event.displayStatus==='rejected'?'Rejected alternative':'Selected footprint'} · conceptual 3D available${event.stale?' as a saved reference':''}.`
      : 'A saved, published footprint enables its conceptual 3D view.';
  }
  function invalidate(event={}) {
    if(!displayed || event.siteId && event.siteId!==displayed.siteId || event.workflow && event.workflow!==displayed.workflow)return;
    if(Number.isInteger(event.inputRevision) && event.inputRevision<displayed.proposal.input_revision)return;
    if(Number.isInteger(event.revision) && event.revision<=displayed.proposal.revision)return;
    closeView();displayed={...displayed,stale:true};
    $('concept-scene-entry').textContent='Inputs or evidence changed. The earlier 3D design remains available as a saved reference.';
  }
  map.on('proposaldisplay',updateDisplay);
  map.on('plannersite',()=>updateDisplay({proposal:null}));
  map.on('plannerinputs',invalidate);map.on('plannerinvestigation',invalidate);
  open.addEventListener('click',openView);
  $('concept-scene-retry').addEventListener('click',openView);
  $('concept-scene-close').addEventListener('click',closeView);
  dialog.addEventListener('cancel',event=>{event.preventDefault();closeView();});
  dialog.addEventListener('close',()=>{if(renderer || controller)cleanup();});
  $('concept-scene-existing').addEventListener('click',()=>setMode('existing'));
  $('concept-scene-proposed').addEventListener('click',()=>setMode('proposed'));
  $('concept-scene-reset').addEventListener('click',()=>renderer?.reset());
  $('concept-scene-top').addEventListener('click',()=>renderer?.top());
  $('concept-scene-left').addEventListener('click',()=>renderer?.rotate('left'));
  $('concept-scene-right').addEventListener('click',()=>renderer?.rotate('right'));
  $('concept-scene-zoom-in').addEventListener('click',()=>renderer?.zoom(1.25));
  $('concept-scene-zoom-out').addEventListener('click',()=>renderer?.zoom(.8));
  $('concept-scene-context').addEventListener('change',()=>renderer?.setContextVisible($('concept-scene-context').checked));
  controls(false);
})();
