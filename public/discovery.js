/* Discovery is deterministic source data: browsing never calls an agent. */
(() => {
  map.createPane('discovery'); map.getPane('discovery').style.zIndex=420;
  const overlay=L.layerGroup(), contextOverlay=L.layerGroup().addTo(map);
  const cache=new Map(), choices=new Map(), visited=new Set(), views=new Map();
  let mode=planningMode, data=null, token=0, controller, expiryTimer;
  const picker=$('discovery-layer'), featurePicker=$('discovery-feature');
  function expand(open) {
    $('discovery-body').hidden=!open;
    $('discovery-collapse').setAttribute('aria-expanded',String(open));
    $('discovery-collapse').textContent=open?'Collapse':'Expand';
    $('discovery-collapse').setAttribute('aria-label',open?'Collapse map layers':'Expand map layers');
  }
  const flowLayer=layer=>['flow','approaches'].includes(layer?.id);
  // The dropdown must not keep calling an expired or failed layer usable.
  const optionText=layer=>layer.label+(usable(layer)?layer.status==='partial'?' · partial':'':layer.status==='expired'?' · expired':' · unavailable');
  const options=[];
  // Show source timestamps as a local clock time; the full value stays in Layer details.
  const shortTime=text=>String(text ?? '').replace(/\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)/g,stamp=>{
    const date=new Date(stamp);return Number.isFinite(date.getTime())?date.toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}):stamp;
  });
  function currentLayer() { return data?.layers.find(layer=>layer.id===picker.value); }
  const usable=layer=>['ready','partial'].includes(layer?.status);
  function valueText(feature,layer) {
    const p=feature.properties,d=p.scalar_detail || {};
    if(layer.id==='approaches')return `${d.speed_min_kmh}–${d.speed_max_kmh} km/h · ${d.member_count} connected portions`;
    if(layer.id==='flow')return d.road_closure?'Road closed':`${d.speed_kmh} km/h · ${p.value}% of free flow`;
    return `${typeof p.value==='number'?p.value.toLocaleString():p.value} ${layer.unit}`;
  }
  function expireFlow() {
    if(!data || mode!=='street')return;
    const flow=data.layers.find(layer=>['flow','approaches'].includes(layer.id));
    if(!flow || !data.flow_expires_epoch || Date.now()/1000<data.flow_expires_epoch)return;
    const version=flow.version;
    for(const layer of data.layers.filter(x=>['flow','approaches'].includes(x.id))) {layer.status='expired';layer.features=[];layer.error='This snapshot expired. Refresh current traffic.';}
    // One expiry message, in the status line; the freshness note no longer applies.
    $('discovery-freshness').hidden=true;
    for(const [option,layer] of options)option.textContent=optionText(layer);
    if(['flow','approaches'].includes(picker.value))render();
    map.fire('discoveryexpired',{version});
  }
  // The key is drawn, not written: swatches in the map's own colours. Exact
  // thresholds and units live in Layer details.
  function paintLegend(layer) {
    const legend=$('discovery-legend');legend.replaceChildren();
    const node=(tag,className,style,text)=>{const item=document.createElement(tag);if(className)item.className=className;
      if(style)item.setAttribute('style',style);if(text)item.textContent=text;return item;};
    const key=(style,label,shape='')=>{const item=node('span','legend-key');item.append(node('i',shape,style),node('span','','',label));return item;};
    if(flowLayer(layer)) {
      const scale=node('span','legend-scale');
      for(const shade of ['#fa7869','#f7b357','#f2d77a','#74d5b0'])scale.append(node('i','',`background:${shade}`));
      const ends=node('span','legend-ends');ends.append(node('span','','','Slow'),node('span','','','Free flow'));
      legend.append(scale,ends,key('background:#d783eb','Closed','line'));
      legend.setAttribute('aria-label','Road colour shows current speed, from red for slow to green for free flow. Purple roads are closed.');
      return;
    }
    legend.setAttribute('aria-label','Map key');
    if(layer.id==='terrain')legend.append(key('background:#65e3e9','Downhill path','line'),key('background:#f2c36b','Collection point','dot'));
    else if(layer.id==='rainfall')legend.append(key('background:#72bcf5','Design rainfall depth (inches)'));
    else if(layer.id==='properties')legend.append(key('background:#e9b6ef','Property','dot'));
    else if(layer.id==='surfaces')legend.append(key('background:#c7beff','Parcel'),key('background:#b7df8c','Building'));
    else if(layer.legend)legend.append(node('span','','',layer.legend));
    else legend.append(key('border-color:#90c7f0','County catchment','dashed'));
  }
  function focusPilot() {
    if(!data)return;
    const b=data.bbox;
    map.fitBounds([[b[1],b[0]],[b[3],b[2]]],{padding:[35,35],maxZoom:mode==='water'?18:15});
  }
  function color(feature,layer) {
    if(['flow','approaches'].includes(layer.id))return feature.properties.scalar_detail?.road_closure?'#d783eb':feature.properties.value<40?'#fa7869':feature.properties.value<70?'#f7b357':feature.properties.value<90?'#f2d77a':'#74d5b0';
    if(layer.id==='rainfall')return '#72bcf5';
    if(layer.id==='catchments')return '#90c7f0';
    if(layer.id==='properties')return '#e9b6ef';
    if(layer.id==='surfaces')return feature.properties.kind==='building'?'#b7df8c':'#c7beff';
    return feature.properties.kind==='collection'?'#f2c36b':'#65e3e9';
  }
  function select(feature, pan=false) {
    expireFlow();
    const layer=currentLayer();if(!usable(layer) || !data)return;
    const [lng,lat]=feature.properties.center;
    if(coverage && !insideCoverage(L.latLng(lat,lng))) {
      $('discovery-status').textContent='This feature is outside available imagery coverage.';return;
    }
    featurePicker.value=feature.id;
    contextOverlay.clearLayers();
    if(feature.properties.contributing_geometry) {
      L.geoJSON({type:'Feature',geometry:feature.properties.contributing_geometry,properties:{}},{pane:'discovery',interactive:false,style:{color:'#c0e8f2',weight:1,fillOpacity:.16,dashArray:'3 4'}}).addTo(contextOverlay);
    }
    map.fire('discoveryselect',{workflow:mode,feature,layer,source:data.sources[layer.source],expiresAt:['flow','approaches'].includes(layer.id)?data.flow_expires_at:null,reference:{version:layer.version || data.version,layer:layer.id,feature:feature.id}});
    if(window.matchMedia('(max-width:760px)').matches)expand(false);
    if(pan)map.setView([lat,lng],mode==='water'?19:17,{animate:false});
    const popup=document.createElement('div');popup.className='discovery-popup';
    const title=document.createElement('strong');title.textContent=feature.properties.label;
    const value=document.createElement('p');value.textContent=valueText(feature,layer);
    const period=document.createElement('small');period.textContent=feature.properties.period || layer.period;
    const note=document.createElement('p');note.textContent=feature.properties.summary || (['flow','approaches'].includes(layer.id)?'Current estimate. Inspect speed, free-flow comparison, direction and retrieval time in the sidebar.':layer.id==='terrain'?'Terrain-inferred collection area; inspect its outline. Drainage and ponding remain unverified.':'Source context added to the site brief.');
    const source=document.createElement('small');source.textContent=data.sources[layer.source].label;
    popup.append(title,value,period,note,source);
    L.popup({maxWidth:290}).setLatLng([lat,lng]).setContent(popup).openOn(map);
  }
  function render() {
    map.closePopup();
    overlay.clearLayers();contextOverlay.clearLayers();featurePicker.replaceChildren();
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Select on the map or choose here';featurePicker.append(placeholder);
    const layer=currentLayer();
    if(!layer) {
      choices.set(mode,'off');featurePicker.disabled=true;
      $('discovery-status').textContent='No overlay shown.';
      $('discovery-legend').textContent='';$('discovery-limit').textContent='';$('discovery-count').textContent='';return;
    }
    choices.set(mode,layer.id);
    paintLegend(layer);
    $('discovery-limit').textContent=['flow','approaches'].includes(layer.id)?'Colour is current speed as a share of free-flow speed: red under 40%, amber 40–70%, yellow 70–90%, green 90% or more; purple is a closed road. One snapshot of surface-street conditions. Gaps are unknown; traffic volume and emissions are not measured. Select a road for its speed and free-flow comparison.':layer.id==='terrain'?'Select a path or collection point to see the terrain area feeding it. Actual drains, flooding and runoff capture remain unverified.':layer.limitations;
    $('discovery-status').textContent=usable(layer)?`${layer.id==='terrain'?'Terrain estimate · ':''}${shortTime(layer.period)}${layer.status==='partial'?' · Partial coverage':''}`
      :layer.status==='expired'?'Traffic expired. Refresh to update.'
      :layer.status==='empty'?'No source features returned for this pilot.':`${layer.label} unavailable. ${layer.error || 'Rebuild the source snapshot.'}`;
    $('discovery-count').textContent=usable(layer)?`${layer.features.length} ${layer.features.length===1?'feature':'features'} · ${layer.period}${layer.status==='partial'?' · Partial coverage; some records could not be validated.':''}`:'';
    featurePicker.disabled=!usable(layer);
    if(!usable(layer))return;
    L.geoJSON({type:'FeatureCollection',features:layer.features},{pane:'discovery',
      style:f=>({color:color(f,layer),weight:['flow','approaches'].includes(layer.id)?5:layer.id==='terrain'?3:layer.id==='catchments'?2:1,
        dashArray:layer.id==='catchments'?'7 5':null,fillOpacity:layer.id==='surfaces'?.08:layer.id==='rainfall'?.16:layer.id==='catchments'?.07:.8}),
      pointToLayer:(f,latlng)=>L.circleMarker(latlng,{pane:'discovery',radius:6,
        color:'#142824',weight:2,fillColor:color(f,layer),fillOpacity:.9}),
      onEachFeature:(f,leaf)=>{
        const label=document.createElement('span');label.textContent=`${f.properties.label} · ${valueText(f,layer)}`;
        leaf.bindTooltip(label);leaf.on('click',()=>{if(!document.getElementById('map').classList.contains('planner-capture'))select(f);});
      }}).addTo(overlay);
    for(const feature of layer.features) {
      const option=document.createElement('option');option.value=feature.id;
      const p=feature.properties;
      option.textContent=`${p.label} · ${valueText(feature,layer)}${['flow','approaches'].includes(layer.id)?'':` · ${p.period || ''}`}`;
      featurePicker.append(option);
    }
  }
  async function load(workflow, retry=false) {
    map.closePopup();
    const changed=workflow!==mode;
    if(changed && data)views.set(mode,{center:map.getCenter(),zoom:map.getZoom()});
    mode=workflow;data=null;const request=++token;
    clearTimeout(expiryTimer);contextOverlay.clearLayers();
    controller?.abort();controller=new AbortController();
    overlay.remove();overlay.clearLayers();
    picker.disabled=true;featurePicker.disabled=true;
    $('discovery-status').textContent='Loading source-backed discovery…';
    $('discovery-legend').textContent='';$('discovery-limit').textContent='';$('discovery-count').textContent='';
    // One recovery action per state: refresh live traffic, or retry a failed load.
    $('discovery-refresh').hidden=mode!=='street';$('discovery-refresh').disabled=true;$('discovery-refresh').textContent='Refresh traffic';
    $('discovery-freshness').hidden=true;
    try {
      const cached=cache.get(mode);
      const reusable=cached && (mode!=='street' || !cached.flow_expires_epoch || Date.now()/1000<cached.flow_expires_epoch);
      const result=!retry&&reusable?cached:await json(`/api/discovery?workflow=${mode}`,{signal:controller.signal,cache:'no-store'});
      if(request!==token)return;
      if(result.workflow!==mode || result.schema!==1 || !Array.isArray(result.layers))throw new Error('Discovery identity mismatch.');
      data=result;cache.set(mode,result);picker.replaceChildren();
      const off=document.createElement('option');off.value='off';off.textContent='No overlay';picker.append(off);
      options.length=0;
      for(const layer of data.layers) {const option=document.createElement('option');option.value=layer.id;option.textContent=optionText(layer);picker.append(option);options.push([option,layer]);}
      picker.value=choices.get(mode) || data.layers.find(usable)?.id || data.layers[0]?.id;
      picker.disabled=false;overlay.addTo(map);render();
      $('discovery-refresh').disabled=false;
      if(mode==='street' && data.flow_expires_epoch) {
        $('discovery-freshness').hidden=false;
        $('discovery-freshness').textContent=`Current estimate, valid until ${new Date(data.flow_expires_at).toLocaleTimeString()}. The time shown is retrieval time; the provider supplies no confidence or observation time.`;
        expiryTimer=setTimeout(expireFlow,Math.max(1,data.flow_expires_epoch*1000-Date.now()+50));
      }
      if(changed && views.has(mode)) {
        const view=views.get(mode);map.setView(view.center,view.zoom,{animate:false});
      } else if(changed || !visited.has(mode)){visited.add(mode);focusPilot();}
    } catch(error) {
      if(request!==token || error.name==='AbortError')return;
      $('discovery-status').textContent=`Discovery unavailable. ${error.message}`;
      $('discovery-refresh').hidden=false;$('discovery-refresh').disabled=false;$('discovery-refresh').textContent='Retry';
    }
  }
  picker.addEventListener('change',render);
  featurePicker.addEventListener('change',()=>{const feature=currentLayer()?.features.find(f=>f.id===featurePicker.value);if(feature)select(feature,true);});
  $('discovery-focus').addEventListener('click',focusPilot);
  $('discovery-collapse').addEventListener('click',()=>expand($('discovery-body').hidden));
  $('discovery-refresh').addEventListener('click',()=>load(mode,true));
  document.addEventListener?.('visibilitychange',expireFlow);
  // Back/forward restoration resumes this script instead of running startup again.
  window.addEventListener('pageshow',event=>{if(event.persisted && mode==='street')load(mode,true);});
  map.on('plannerworkspace',({mode})=>load(mode));
  map.attributionControl.addAttribution('Traffic © TomTom · Street context © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Terrain: USGS · Hydrology: LA County');
  load(planningMode,true);
})();
