/* Saved road concepts use the supplied map geometry. Rendering never evaluates traffic. */
(() => {
  const kinds = {
    curb_extension: {label:'Curb extension', color:'#e7a84b'},
    crossing: {label:'Crossing', color:'#f8f5dc'},
    pedestrian_island: {label:'Pedestrian island', color:'#dbb56b'},
    bike_lane: {label:'Bike lane', color:'#3fa580'},
    pedestrian_space: {label:'Pedestrian space', color:'#bd8878'},
    lane_marking: {label:'Lane marking', color:'#fff7dc'},
    intersection_redesign: {label:'Intersection redesign', color:'#3b4145'},
  };
  const surfaces={
    roadway:{label:'Roadway',color:'#3b4145',edge:'#292e31',weight:.75},
    sidewalk:{label:'Sidewalk',color:'#dcd4c1',edge:'#b5ad99',weight:.65},
    curb:{label:'Concrete curb',color:'#f0e9d8',edge:'#aaa38e',weight:.65},
    planting:{label:'Planting',color:'#7c956a',edge:'#506944',weight:.8},
    centerline:{label:'Centerlines',color:'#e9c85b',edge:'#e9c85b',weight:0},
    lane_separator:{label:'One-way lane dividers',color:'#faf7ed',edge:'#faf7ed',weight:0},
    crosswalk:{label:'Crossings',color:'#faf7ed',edge:'#faf7ed',weight:0},
    stop_line:{label:'Stop lines',color:'#faf7ed',edge:'#faf7ed',weight:0},
    lane_arrow:{label:'Lane arrows',color:'#faf7ed',edge:'#faf7ed',weight:0},
  };
  const card=$('road-concept-review'), show=$('show-road-concept');
  let selected=null, current=null, displayed=null, layer=null, history=[], latestRevision=0, blockedRevision=0, mode='proposed';
  map.createPane('road-concept'); map.getPane('road-concept').style.zIndex=615;
  const element=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=String(text);return node;};
  const number=value=>Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:2}):'Not specified';
  const text=value=>typeof value==='string'?value:value?.label || value?.title || value?.reason || value?.text || value?.provider || value?.source || value?.id || '';
  const key=c=>`${c.revision}:${c.input_hash}`;
  const wholePlan=c=>c?.components?.some(component=>component.kind==='intersection_redesign');
  const opacityByRevision=new Map();
  function setOpacity(value) {
    $('road-concept-opacity').value=String(value);
    $('road-concept-opacity-value').textContent=`${value}%`;
  }
  function state(label) {
    card.hidden=false;card.setAttribute('data-state',label);
    $('road-concept-state').textContent=label;
    map.fire('roadconceptstate',{state:label,siteId:selected?.siteId});
  }
  function notify() {
    map.fire('roadconceptdisplay',{concept:displayed?.concept ?? null,visible:Boolean(displayed && show.checked && mode==='proposed'),
      historical:Boolean(displayed?.historical),stale:Boolean(displayed?.stale)});
  }
  function visible() {
    if(layer){if(show.checked && mode==='proposed')layer.addTo(map);else layer.remove();}
    $('road-concept-existing').setAttribute('aria-pressed',String(mode==='existing'));
    $('road-concept-proposed').setAttribute('aria-pressed',String(mode==='proposed'));
    $('road-concept-mode-note').textContent=mode==='existing'?'Existing aerial imagery · the proposed plan is hidden.':wholePlan(displayed?.concept)?'Coordinated intersection plan · select a surface to inspect it.':'Individual proposed treatments over the existing aerial imagery.';
    notify();
  }
  function controls(enabled) {
    for(const id of ['road-concept-existing','road-concept-proposed','road-concept-opacity','show-road-concept','road-concept-focus'])$(id).disabled=!enabled;
  }
  function clear(event) {
    selected=event.workflow==='street' && event.siteId?{...event}:null;
    layer?.remove();layer=null;current=null;displayed=null;history=[];latestRevision=0;blockedRevision=0;
    card.hidden=true;show.checked=true;mode='proposed';controls(false);
    card.setAttribute('data-plan','none');$('road-concept-scope').textContent='ROAD CONCEPT';
    $('road-concept-location').hidden=true;
    $('road-concept-warning').hidden=true;$('road-concept-history-box').hidden=true;
    $('road-concept-return').hidden=true;$('road-concept-legend').replaceChildren();
    $('road-concept-components').replaceChildren();$('road-concept-basis').replaceChildren();
    notify();
  }
  function validate(c) {
    if(!selected || c?.schema_version!==1 || c.site_id!==selected.siteId || c.workflow!=='street' || c.status!=='conceptual' ||
      !Number.isInteger(c.revision) || c.revision<1 || !Number.isInteger(c.input_revision) || c.input_revision<0 ||
      !/^[a-f0-9]{64}$/.test(c.input_hash) || !/^[a-f0-9]{64}$/.test(c.context_hash) ||
      c.evaluation?.status!=='unassessed' || !Array.isArray(c.components) || !c.components.length || c.components.length>40 ||
      !Array.isArray(c.geometry) || !c.geometry.length || c.geometry.length>1000)throw new Error('The concept does not match this site or a supported saved revision.');
    const components=new Map(c.components.map(component=>[component.id,component]));
    if(components.size!==c.components.length || c.components.some(component=>typeof component.id!=='string' || !component.id || !kinds[component.kind]))throw new Error('The concept contains an unsupported road feature.');
    let coordinates=0;
    const point=p=>Array.isArray(p) && p.length>=2 && p.slice(0,2).every(Number.isFinite) && Math.abs(p[0])<=180 && Math.abs(p[1])<=90 && ++coordinates<=50000;
    const line=(v,ring=false)=>Array.isArray(v) && v.length>=(ring?4:2) && v.every(point) && (!ring || v[0][0]===v.at(-1)[0] && v[0][1]===v.at(-1)[1]);
    const polygon=v=>Array.isArray(v) && v.length>0 && v.every(r=>line(r,true));
    for(const f of c.geometry) {
      const p=f?.properties,g=f?.geometry,component=components.get(p?.component_id);
      const valid=g?.type==='Polygon'?polygon(g.coordinates):g?.type==='MultiPolygon'?Array.isArray(g.coordinates) && g.coordinates.length>0 && g.coordinates.every(polygon):
        g?.type==='LineString'?line(g.coordinates):g?.type==='MultiLineString'?Array.isArray(g.coordinates) && g.coordinates.length>0 && g.coordinates.every(v=>line(v)):false;
      if(f.type!=='Feature' || !component || p.kind!==component.kind || p.revision!==c.revision || !['proposed','marking'].includes(p.role) || !valid)throw new Error('The saved road geometry is invalid or belongs to another revision.');
      if(component.kind==='intersection_redesign' && !Object.hasOwn(surfaces,p.surface))throw new Error('The intersection plan contains an unsupported surface.');
    }
    return c;
  }
  function style(feature) {
    const p=feature.properties, color=kinds[p.kind].color, opacity=Number($('road-concept-opacity').value)/100;
    if(p.kind==='intersection_redesign') {
      const surface=surfaces[p.surface];
      return {color:surface.edge,weight:surface.weight,stroke:surface.weight>0,
        opacity,fillColor:surface.color,fillOpacity:opacity,lineCap:'butt',lineJoin:'round',smoothFactor:0};
    }
    const marking=p.role==='marking' || p.kind==='lane_marking';
    return {color:marking?'#fffbed':p.kind==='bike_lane'?'#12694e':'#705d39',weight:marking?1.4:1.6,
      opacity,fillColor:marking?'#fffbed':color,fillOpacity:opacity*(p.kind==='crossing' && !marking ? .25 : marking ? .96 : .78),
      lineCap:'butt',lineJoin:'round'};
  }
  function sourceList(parent,values) {
    for(const item of Array.isArray(values)?values:[]) {
      const label=text(item);if(!label)continue;
      const li=element('li'), url=typeof item==='object'?item.url || item.source_url:null;
      if(typeof url==='string' && /^https?:\/\//i.test(url)) {
        const a=element('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';li.append(a);
      } else li.textContent=label;
      parent.append(li);
    }
  }
  function popup(c,feature) {
    const component=c.components.find(item=>item.id===feature.properties.component_id), box=element('div');box.className='road-concept-popup';
    if(component.kind==='intersection_redesign') {
      box.append(element('small','PROPOSED INTERSECTION'),element('strong',surfaces[feature.properties.surface].label));
      const dimensions=componentDimensions(component);if(dimensions)box.append(element('p',dimensions));
      box.append(element('p','Part of this coordinated concept, aligned to the saved road geometry.'));
      const details=element('details'),summary=element('summary','Source & design basis'),basis=element('ul');
      sourceList(basis,component.sources || c.sources);sourceList(basis,component.assumptions || c.assumptions);
      details.append(summary,basis);box.append(details);return box;
    }
    box.append(element('strong',feature.properties.label || kinds[component.kind].label),
      element('p',`${number(component.length_m)} m long × ${number(component.width_m)} m wide`),
      element('p',`Conceptual placement · ${component.side || 'center'} of mapped road. Traffic performance is unassessed.`));
    const basis=element('ul');sourceList(basis,component.sources || c.sources);sourceList(basis,component.assumptions || c.assumptions);box.append(basis);
    return box;
  }
  function prepare(c) {
    return L.geoJSON({type:'FeatureCollection',features:c.geometry},{pane:'road-concept',style,
      onEachFeature(feature,item){item.bindPopup(popup(c,feature),{maxWidth:300});}});
  }
  function componentDimensions(component) {
    if(component.kind!=='intersection_redesign')return `${number(component.length_m)} × ${number(component.width_m)} m`;
    const fields=[['approach_length_m','Maximum approach length'],['curb_extension_m','Maximum curb extension'],['crossing_setback_m','Crossing setback'],['crossing_width_m','Crossing width']];
    return fields.filter(([key])=>Number.isFinite(component[key])).map(([key,label])=>`${label} ${number(component[key])} m`).join(' · ');
  }
  function planLocation(c) {
    const component=c.components.find(item=>item.kind==='intersection_redesign');
    const junction=c.context?.junctions?.find(item=>item.id===component?.junction_id);
    if(!junction)return '';
    const check=Array.isArray(c.checks)?c.checks.find(item=>item.component_id===component.id):null;
    const parts=[check?.connected===true?'Connected junction':'Mapped junction'];
    const approaches=check?.approach_count ?? junction.approach_count;
    if(Number.isInteger(approaches) && approaches>0)parts.push(`${approaches} approaches`);
    if(Number.isFinite(junction.distance_m) && junction.distance_m>10)parts.push(`${Math.round(junction.distance_m)} m from your selected point`);
    return parts.join(' · ');
  }
  function checkDescription(c,check) {
    if(!check.component_id)return check;
    const component=c.components.find(item=>item.id===check.component_id);
    const parts=[`${component?.label || check.component_id}: ${number(check.area_m2)} m².`];
    if(component?.kind==='intersection_redesign') {
      if(Number.isFinite(check.approach_count))parts.push(`${check.approach_count} approaches.`);
      if(Number.isFinite(check.crossing_count))parts.push(`${check.crossing_count} crossings.`);
      if(check.one_way_approach_count>0)parts.push(`${check.one_way_approach_count} one-way approaches; source lane counts and directions preserved.`);
      if(check.connected===true)parts.push('Road layout connected.');
      if(Number.isFinite(check.roadway_area_m2))parts.push(`Roadway ${number(check.roadway_area_m2)} m².`);
      if(Number.isFinite(check.sidewalk_area_m2))parts.push(`Sidewalk ${number(check.sidewalk_area_m2)} m².`);
    }
    parts.push(check.road_fit==='checked'?'Mapped corridor fit checked.':'User-marked alignment.',
      check.keep_clear==='checked'?'Keep-clear markings checked.':'No keep-clear markings supplied.',
      `Building overlap ${check.building_overlap==='checked'?'checked':'not assessed'}.`);
    return parts.join(' ');
  }
  function historyButtons() {
    const list=$('road-concept-history');list.replaceChildren();
    for(const record of [...history].sort((a,b)=>b.concept.revision-a.concept.revision)) {
      const c=record.concept;if(current && key(c)===key(current.concept))continue;
      const button=element('button',`View revision ${c.revision}`);button.type='button';
      button.addEventListener('click',()=>{
        try {publish({...record,historical:true,stale:c.input_revision!==selected?.inputRevision});}
        catch(error){warning(`Earlier concept unavailable: ${error.message}`);}
      });list.append(button);
    }
    $('road-concept-history-box').hidden=!list.children.length;
    $('road-concept-return').hidden=!displayed?.historical || !current;
  }
  function warning(message) {$('road-concept-warning').textContent=message;$('road-concept-warning').hidden=!message;}
  function publish(record,prepared=null) {
    const c=validate(record.concept), replacement=prepared || prepare(c);
    setOpacity(opacityByRevision.get(key(c)) ?? (wholePlan(c)?100:85));
    replacement.setStyle(style);
    layer?.remove();layer=replacement;displayed=record;controls(true);
    card.setAttribute('data-plan',wholePlan(c)?'intersection':'components');
    state('Concept ready');
    $('road-concept-title').textContent=wholePlan(c)?(record.historical?`Earlier intersection plan · revision ${c.revision}`:'Intersection redesign'):(record.historical?`Earlier component concept · revision ${c.revision}`:'Individual road treatments');
    const presentSurfaces=[...new Set(c.geometry.map(feature=>feature.properties.surface).filter(Boolean))];
    $('road-concept-summary').textContent=c.summary || (wholePlan(c)
      ? 'One continuous redesign aligned with the mapped intersection.'
      : 'This saved revision contains separate treatments. Generate a coordinated redesign to see the roadway, corners and crossings together.');
    const location=planLocation(c);
    $('road-concept-location').textContent=location;$('road-concept-location').hidden=!location;
    $('road-concept-scope').textContent=wholePlan(c)?'COORDINATED CONCEPT':'COMPONENT CONCEPT';
    $('road-concept-performance').textContent=c.evaluation.reason || 'Traffic and emissions have not been evaluated for this concept.';
    $('road-concept-revision').textContent=`Revision ${c.revision}${record.savedAt?` · saved ${new Date(record.savedAt).toLocaleString()}`:''}`;
    warning(record.historical?'Earlier saved concept · read-only view. The current project is unchanged.':record.stale?'Saved reference · inputs or evidence changed. This concept has not been updated.':'');
    const legend=$('road-concept-legend');legend.replaceChildren();
    const legendEntries=wholePlan(c)?Object.entries(surfaces).filter(([name])=>presentSurfaces.includes(name)).map(([,entry])=>entry):[...new Set(c.components.map(component=>component.kind))].map(kind=>kinds[kind]);
    for(const entry of legendEntries) {
      const item=element('li'),swatch=element('span');swatch.className='road-concept-swatch';swatch.setAttribute('aria-hidden','true');
      swatch.style.backgroundColor=entry.color;
      item.append(swatch,element('span',entry.label));legend.append(item);
    }
    const parts=$('road-concept-components');parts.replaceChildren();
    for(const component of c.components)parts.append(element('li',[component.label || kinds[component.kind].label,componentDimensions(component)].filter(Boolean).join(' · ')));
    const basis=$('road-concept-basis');basis.replaceChildren();if(location)sourceList(basis,[location]);sourceList(basis,c.sources);sourceList(basis,c.assumptions);
    sourceList(basis,Array.isArray(c.checks)?c.checks.map(check=>checkDescription(c,check)):
      Object.entries(c.checks || {}).map(([name,value])=>typeof value==='string'?`${name.replaceAll('_',' ')}: ${value}`:value));
    $('road-concept-details').hidden=false;
    historyButtons();visible();
  }
  function receive(event) {
    if(!selected || event.siteId!==selected.siteId || event.workflow!=='street' || !Number.isInteger(event.revision) ||
      event.revision<latestRevision || !event.restored && (event.inputRevision!==selected.inputRevision || event.revision<=blockedRevision))return;
    try {
      const fresh=event.concept?validate(event.concept):null;
      if(fresh && (fresh.revision>event.revision || fresh.input_revision>selected.inputRevision ||
        !event.restored && (fresh.revision!==event.revision || fresh.input_revision!==event.inputRevision)))throw new Error('The concept was generated for different inputs.');
      const replacement=fresh?prepare(fresh):null;
      const saved=(event.conceptHistory ?? []).filter(record=>{
        try {validate(record.concept);return record.concept.revision<=event.revision && record.concept.input_revision<=selected.inputRevision;}catch{return false;}
      });
      // Prepare everything first; an invalid response never removes a working map.
      latestRevision=event.revision;
      const byKey=new Map(history.map(record=>[key(record.concept),record]));
      for(const record of saved)byKey.set(key(record.concept),record);
      if(current)byKey.set(key(current.concept),current);
      history=[...byKey.values()];
      if(fresh) {
        current={concept:fresh,savedAt:event.conceptSavedAt || event.savedAt,stale:Boolean(event.stale || event.historicalReference || fresh.input_revision!==selected.inputRevision)};
        show.checked=true;mode='proposed';publish(current,replacement);
      }
      if(event.conceptGap) {
        state('Placement needed');$('road-concept-summary').textContent=text(event.conceptGap) || 'A supported road placement could not be established.';
        if(displayed){displayed={...displayed,stale:true};if(current)current={...current,stale:true};warning('Previous concept remains visible as a saved reference; this attempt did not replace it.');}
        else {$('road-concept-title').textContent='A road concept needs placement';$('road-concept-details').hidden=true;controls(false);}
        $('road-concept-performance').textContent='Traffic and emissions remain unassessed.';
      }
      historyButtons();
      map.fire('roadconceptready',{siteId:selected.siteId,revision:event.revision,available:Boolean(fresh),restored:Boolean(event.restored),follow:Boolean(event.follow)});
    } catch(error) {
      state('Concept unavailable');warning(`The road concept could not be displayed: ${error.message}${displayed?' The previous concept is preserved.':''}`);
    }
  }
  map.on('plannersite',clear);
  map.on('roadconceptresult',receive);
  map.on('plannerinputs',event=>{
    if(!selected || !Number.isInteger(event.inputRevision) || event.inputRevision<selected.inputRevision)return;
    selected.inputRevision=event.inputRevision;
    if(displayed){displayed={...displayed,stale:true};if(current)current={...current,stale:true};warning('Inputs changed. The displayed concept is a saved reference; run the revised brief to update it.');notify();}
  });
  map.on('plannerinvestigation',event=>{
    if(!selected || event.siteId!==selected.siteId || event.workflow!=='street')return;
    latestRevision=Math.max(latestRevision,event.revision || 0);
    if(displayed){displayed={...displayed,stale:true};if(current)current={...current,stale:true};warning('Updating this road concept. The earlier revision remains visible until a new concept is ready.');}
  });
  map.on('planneranalysisend',event=>{
    if(!selected || event.siteId!==selected.siteId || event.workflow!=='street' || !['canceled','failed'].includes(event.status))return;
    blockedRevision=Math.max(blockedRevision,event.revision || 0);
    if(displayed)warning('The latest attempt stopped. The previous road concept is still available as a saved reference.');
  });
  map.on('proposaldisplay',event=>{if(event.proposal && displayed){show.checked=false;visible();}});
  $('show-proposal').addEventListener('change',()=>{if($('show-proposal').checked && displayed){show.checked=false;visible();}});
  $('focus-proposal').addEventListener('click',()=>{if(displayed){show.checked=false;visible();}});
  show.addEventListener('change',visible);
  $('road-concept-existing').addEventListener('click',()=>{mode='existing';visible();});
  $('road-concept-proposed').addEventListener('click',()=>{mode='proposed';show.checked=true;visible();});
  $('road-concept-focus').addEventListener('click',()=>{
    const bounds=layer?.getBounds?.();
    if(bounds?.isValid()){mode='proposed';show.checked=true;visible();map.fire('roadconceptfocus',{});map.fitBounds(bounds,{maxZoom:19,paddingTopLeft:[40,40],paddingBottomRight:[60,110]});}
  });
  $('road-concept-opacity').addEventListener('input',()=>{const value=Number($('road-concept-opacity').value);if(displayed)opacityByRevision.set(key(displayed.concept),value);layer?.setStyle(style);setOpacity(value);});
  $('road-concept-return').addEventListener('click',()=>{if(current)publish(current);});
  controls(false);
})();
