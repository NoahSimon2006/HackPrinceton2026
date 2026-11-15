/* Discovery is deterministic source data: browsing never calls an agent. */
(() => {
  map.createPane('discovery'); map.getPane('discovery').style.zIndex=420;
  const overlay=L.layerGroup();
  const cache=new Map(), choices=new Map(), visited=new Set(), views=new Map();
  let mode=planningMode, data=null, token=0, controller;
  const picker=$('discovery-layer'), featurePicker=$('discovery-feature');
  function expand(open) {
    $('discovery-body').hidden=!open;
    $('discovery-collapse').setAttribute('aria-expanded',String(open));
    $('discovery-collapse').textContent=open?'Hide layers':'Show layers';
  }
  function currentLayer() { return data?.layers.find(layer=>layer.id===picker.value); }
  function focusPilot() {
    if(!data)return;
    const b=data.bbox;
    map.fitBounds([[b[1],b[0]],[b[3],b[2]]],{padding:[35,35],maxZoom:mode==='water'?18:15});
  }
  function color(feature,layer) {
    if(layer.id==='counts')return feature.properties.value>=20000?'#ffcd80':feature.properties.value>=10000?'#8ed8a6':'#c4f5d4';
    if(layer.id==='turning')return '#f08bd2';
    if(layer.id==='rainfall')return '#72bcf5';
    if(layer.id==='catchments')return '#90c7f0';
    return feature.properties.kind==='collection'?'#f2c36b':'#65e3e9';
  }
  function select(feature, pan=false) {
    const layer=currentLayer();if(!layer || !data)return;
    const [lng,lat]=feature.properties.center;
    if(coverage && !insideCoverage(L.latLng(lat,lng))) {
      $('discovery-status').textContent='This feature is outside available imagery coverage.';return;
    }
    featurePicker.value=feature.id;
    map.fire('discoveryselect',{workflow:mode,feature,layer,source:data.sources[layer.source],reference:{version:data.version,layer:layer.id,feature:feature.id}});
    if(window.matchMedia('(max-width:760px)').matches)expand(false);
    if(pan)map.setView([lat,lng],mode==='water'?19:17,{animate:false});
    const popup=document.createElement('div');popup.className='discovery-popup';
    const title=document.createElement('strong');title.textContent=feature.properties.label;
    const value=document.createElement('p');value.textContent=`${typeof feature.properties.value==='number'?feature.properties.value.toLocaleString():feature.properties.value} ${layer.unit}`;
    const period=document.createElement('small');period.textContent=feature.properties.period || layer.period;
    const note=document.createElement('p');note.textContent=layer.id==='terrain'?'Inferred from bare-earth terrain. Not flood depth.':layer.id==='counts'?'Historical reported count; not an hourly rate.':layer.id==='turning'?'Official LADOT turning-movement sheet; totals checked. Ask the agent to compare redesigns here.':'Source context added to the site brief.';
    const source=document.createElement('small');source.textContent=data.sources[layer.source].label;
    popup.append(title,value,period,note,source);
    L.popup({maxWidth:290}).setLatLng([lat,lng]).setContent(popup).openOn(map);
  }
  function render() {
    map.closePopup();
    overlay.clearLayers();featurePicker.replaceChildren();
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Select on the map or choose here';featurePicker.append(placeholder);
    const layer=currentLayer();
    if(!layer) {
      choices.set(mode,'off');featurePicker.disabled=true;
      $('discovery-status').textContent='Discovery layer hidden.';
      $('discovery-legend').textContent='';$('discovery-limit').textContent='';return;
    }
    choices.set(mode,layer.id);
    $('discovery-legend').textContent=layer.id==='terrain'?'↘ Cyan · downhill paths   ● Gold · unresolved collection candidates':layer.id==='counts'?'● Green → amber · lower to higher reported count':layer.id==='turning'?'● Pink · intersections with a checked LADOT turning-movement sheet':layer.id==='rainfall'?'▧ Blue · design rainfall depth, inches':'▧ Dashed blue · county catchment context';
    $('discovery-limit').textContent=layer.id==='terrain'?'1 m USGS DEM · 240 m pilot. Inferred surface routing; no flood depth or verified drain connection.':layer.id==='counts'?'Historical data only. CO₂, NOₓ and delay remain unavailable without verified inputs.':layer.id==='turning'?'Counted left/through/right movements by approach. Signal timing is not on the sheets; simulations use generated timing.':layer.limitations;
    $('discovery-status').textContent=layer.status==='ready'?`${layer.features.length} ${layer.features.length===1?'feature':'features'} · ${layer.period}`:layer.status==='empty'?'No source features returned for this pilot.':`${layer.label} unavailable. ${layer.error || 'Rebuild the source snapshot.'}`;
    featurePicker.disabled=layer.status!=='ready';
    if(layer.status!=='ready')return;
    L.geoJSON({type:'FeatureCollection',features:layer.features},{pane:'discovery',
      style:f=>({color:color(f,layer),weight:layer.id==='terrain'?3:layer.id==='catchments'?2:1,
        dashArray:layer.id==='catchments'?'7 5':null,fillOpacity:layer.id==='rainfall'?.16:layer.id==='catchments'?.07:.8}),
      pointToLayer:(f,latlng)=>L.circleMarker(latlng,{pane:'discovery',radius:layer.id==='turning'?10:layer.id==='counts'?6+Math.min(5,Math.log10(1+f.properties.value)):6,
        color:'#142824',weight:2,fillColor:color(f,layer),fillOpacity:.9}),
      onEachFeature:(f,leaf)=>{
        const label=document.createElement('span');label.textContent=`${f.properties.label} · ${f.properties.value.toLocaleString()} ${layer.unit}`;
        leaf.bindTooltip(label);leaf.on('click',()=>{if(!document.getElementById('map').classList.contains('planner-capture'))select(f);});
      }}).addTo(overlay);
    for(const feature of layer.features) {
      const option=document.createElement('option');option.value=feature.id;
      const p=feature.properties;
      option.textContent=`${p.label}${p.value===p.label?'':` · ${p.value.toLocaleString()}`} · ${p.period || feature.id}`;
      featurePicker.append(option);
    }
  }
  async function load(workflow, retry=false) {
    map.closePopup();
    const changed=workflow!==mode;
    if(changed && data)views.set(mode,{center:map.getCenter(),zoom:map.getZoom()});
    mode=workflow;data=null;const request=++token;
    controller?.abort();controller=new AbortController();
    overlay.remove();overlay.clearLayers();
    picker.disabled=true;featurePicker.disabled=true;
    $('discovery-status').textContent='Loading source-backed discovery…';
    $('discovery-legend').textContent='';$('discovery-limit').textContent='';$('discovery-retry').hidden=true;
    try {
      const result=!retry&&cache.has(mode)?cache.get(mode):await json(`/api/discovery?workflow=${mode}`,{signal:controller.signal});
      if(request!==token)return;
      if(result.workflow!==mode || result.schema!==1 || !Array.isArray(result.layers))throw new Error('Discovery identity mismatch.');
      data=result;cache.set(mode,result);picker.replaceChildren();
      const off=document.createElement('option');off.value='off';off.textContent='Hide discovery layer';picker.append(off);
      for(const layer of data.layers) {const option=document.createElement('option');option.value=layer.id;option.textContent=layer.label+(layer.status==='ready'?'':' · unavailable');picker.append(option);}
      picker.value=choices.get(mode) || data.layers.find(layer=>layer.status==='ready')?.id || data.layers[0]?.id;
      picker.disabled=false;overlay.addTo(map);render();
      if(changed && views.has(mode)) {
        const view=views.get(mode);map.setView(view.center,view.zoom,{animate:false});
      } else if(changed || !visited.has(mode)){visited.add(mode);focusPilot();}
    } catch(error) {
      if(request!==token || error.name==='AbortError')return;
      $('discovery-status').textContent=`Discovery unavailable. ${error.message}`;
      $('discovery-retry').hidden=false;
    }
  }
  picker.addEventListener('change',render);
  featurePicker.addEventListener('change',()=>{const feature=currentLayer()?.features.find(f=>f.id===featurePicker.value);if(feature)select(feature,true);});
  $('discovery-focus').addEventListener('click',focusPilot);
  $('discovery-collapse').addEventListener('click',()=>expand($('discovery-body').hidden));
  $('discovery-retry').addEventListener('click',()=>load(mode,true));
  map.on('plannerworkspace',({mode})=>load(mode));
  map.attributionControl.addAttribution('Count locations © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Terrain: USGS · Hydrology: LA County');
  load(planningMode);
})();
