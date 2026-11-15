import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('../public/discovery.js',import.meta.url),'utf8');
const flush=()=>new Promise(setImmediate);
function harness(mobile=false) {
  const elements=new Map(),requests=[],events=[],rendered=[],timers=[],windowEvents={},clock={now:Date.now()};
  class TestDate extends Date {static now(){return clock.now;}}
  const element=()=>({value:'',disabled:false,hidden:false,children:[],events:{},textContent:'',
    classList:{contains:()=>false},setAttribute(){},append(...children){this.children.push(...children);},
    replaceChildren(){this.children=[];},addEventListener(name,fn){this.events[name]=fn;}});
  const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const overlay={attached:false,clearLayers(){rendered.length=0;},addTo(){this.attached=true;return this;},remove(){this.attached=false;}};
  const map={handlers:{},createPane(){},getPane:()=>({style:{}}),fitBounds(){},setView(){},closePopup(){},getCenter:()=>({lat:34.05,lng:-118.25}),getZoom:()=>17,
    fire(name,event){events.push({name,event});this.handlers[name]?.(event);},on(name,fn){this.handlers[name]=fn;},attributionControl:{addAttribution(){}}};
  const popup={setLatLng(){return this;},setContent(content){this.content=content;return this;},openOn(){return this;}};
  const json=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
  vm.runInNewContext(source,{$,map,json,planningMode:'street',coverage:null,AbortController,setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},Date:TestDate,window:{matchMedia:()=>({matches:mobile}),addEventListener:(name,fn)=>{windowEvents[name]=fn;}},
    document:{createElement:element,getElementById:$},
    L:{latLng:(lat,lng)=>({lat,lng}),layerGroup:()=>overlay,popup:()=>popup,circleMarker:()=>({}),
      geoJSON:(data,options)=>{for(const feature of data.features){const leaf={bindTooltip(){},on(name,fn){this[name]=fn;}};options.onEachFeature(feature,leaf);rendered.push({feature,leaf});}return{addTo(){}};}}});
  return{$,map,requests,events,rendered,overlay,timers,clock,windowEvents};
}
function data(workflow='street',id='flow') {
  return{schema:1,workflow,version:`${workflow}-hash`,bbox:[-118.26,34.04,-118.24,34.06],
    sources:{public:{label:'Official dataset',url:'https://example.org/source'}},
    layers:[{id,label:'Source layer',source:'public',status:'ready',unit:'vehicles reported',period:'2014-01-16',
      limitations:'Historical only',features:[{id:'one',type:'Feature',geometry:{type:'Point',coordinates:[-118.25,34.05]},
        properties:{label:'First & Alameda',center:[-118.25,34.05],value:18102,period:'2014-01-16'}}]}]};
}
{
  const h=harness();
  assert.equal(h.requests[0].url,'/api/discovery?workflow=street');
  assert.equal(h.requests[0].options.cache,'no-store','page load must request current data without browser caching');
  h.requests[0].resolve(data());await flush();
  assert.equal(h.rendered.length,1);
  assert.match(h.$('discovery-limit').textContent,/traffic volume and emissions are not measured/);
  h.rendered[0].leaf.click();
  const selection=h.events.find(x=>x.name==='discoveryselect').event;
  assert.deepEqual(JSON.parse(JSON.stringify(selection.reference)),{version:'street-hash',layer:'flow',feature:'one'});
  assert.equal(selection.feature.properties.value,18102);
  assert.equal(h.requests.length,1,'browsing/selecting discovery never invokes an agent');
  h.$('discovery-layer').value='off';h.$('discovery-layer').events.change();
  assert.equal(h.rendered.length,0);
  h.map.fire('plannerworkspace',{mode:'water'});
  const water=data('water','rainfall');water.layers.unshift({...water.layers[0],id:'terrain',status:'unavailable',features:[],error:'DEM offline'});
  h.requests[1].resolve(water);await flush();
  assert.equal(h.$('discovery-layer').value,'rainfall','a failed source does not hide the usable layer');
  h.$('discovery-layer').value='terrain';h.$('discovery-layer').events.change();
  assert.match(h.$('discovery-status').textContent,/DEM offline/);
  assert.equal(h.rendered.length,0,'failed terrain cannot be replaced by a fixture');
  h.map.fire('plannerworkspace',{mode:'street'});await flush();
  assert.equal(h.$('discovery-layer').value,'off','per-mode preference survives switching');
  assert.equal(h.requests.length,2,'cached source is reused');
}
{
  const h=harness();
  h.map.fire('plannerworkspace',{mode:'water'});
  assert.equal(h.requests[0].options.signal.aborted,true);
  h.requests[1].reject(new Error('Restart server'));await flush();
  assert.equal(h.$('discovery-refresh').hidden,false,'a failed stormwater load still offers recovery');
  assert.equal(h.$('discovery-refresh').textContent,'Retry','one recovery action per failed fetch');
  h.$('discovery-refresh').events.click();
  h.requests[2].resolve(data('water','terrain'));await flush();
  h.requests[0].resolve(data());await flush();
  assert.equal(h.$('discovery-layer').value,'terrain','late traffic response cannot repaint stormwater');
  assert.equal(h.$('discovery-refresh').hidden,true,'stormwater has no live refresh once loaded');
  h.$('discovery-feature').value='one';h.$('discovery-feature').events.change();
  assert.equal(h.events.find(x=>x.name==='discoveryselect').event.workflow,'water');
}
console.log('PASS: source-only discovery, selection, off toggle, partial failure, retry and stale-response isolation');
{
  const h=harness(true);h.requests[0].resolve(data());await flush();
  h.rendered[0].leaf.click();
  assert.equal(h.$('discovery-body').hidden,true,'selection frees up map space on narrow screens');
  h.$('discovery-collapse').events.click();
  assert.equal(h.$('discovery-body').hidden,false,'layer controls can always be reopened');
}
console.log('PASS: narrow-screen controls collapse after selection and reopen on request');

{
  const h=harness();h.requests[0].resolve(data());await flush();
  h.windowEvents.pageshow({persisted:false});
  assert.equal(h.requests.length,1,'ordinary page load must not request traffic twice');
  h.windowEvents.pageshow({persisted:true});
  assert.equal(h.requests.length,2,'restoring a saved page must refresh even a cached traffic layer');
  assert.equal(h.requests[1].options.cache,'no-store');
  h.requests[1].resolve(data());await flush();
  h.map.fire('plannerworkspace',{mode:'water'});
  h.requests[2].resolve(data('water','terrain'));await flush();
  h.windowEvents.pageshow({persisted:true});
  assert.equal(h.requests.length,3,'restoring stormwater must not fetch traffic');
}
console.log('PASS: fresh traffic request on page load and browser restoration without duplicate startup requests');

{
  const h=harness();const current=data();
  const live={...current.layers[0],id:'flow',version:'flow-current',status:'partial',unit:'% of free-flow speed',
    features:[{...current.layers[0].features[0],id:'slow-road',properties:{...current.layers[0].features[0].properties,
      value:50,scalar_detail:{speed_kmh:20,relative_speed:.5,road_closure:false}}}]};
  current.layers=[live,{...live,id:'approaches',features:[...live.features]}];current.flow_expires_epoch=h.clock.now/1000+60;
  current.flow_expires_at=new Date(current.flow_expires_epoch*1000).toISOString();
  h.requests[0].resolve(current);await flush();
  assert.equal(h.$('discovery-layer').value,'flow');
  h.rendered[0].leaf.click();
  assert.equal(h.events.find(e=>e.name==='discoveryselect').event.reference.version,'flow-current');
  h.clock.now+=61000;h.timers[0]();
  assert.equal(h.rendered.length,0,'expired flow must disappear');
  assert.match(h.$('discovery-status').textContent,/expired/);
  assert.equal(h.requests.length,1,'expiry must not create automatic provider polling');
  h.$('discovery-layer').value='approaches';h.$('discovery-layer').events.change();
  assert.equal(h.rendered.length,0,'both current-traffic layers expire without historical fallback');
  h.$('discovery-refresh').events.click();
  assert.equal(h.requests.length,2,'refresh is explicitly initiated');
  assert.equal(h.requests[1].options.cache,'no-store','manual refresh also bypasses browser caching');
  h.map.fire('plannerworkspace',{mode:'water'});
  h.requests[2].resolve(data('water','rainfall'));await flush();
  h.requests[1].resolve(data());await flush();
  assert.equal(h.$('discovery-layer').value,'rainfall','late flow refresh cannot replace stormwater');
}
console.log('PASS: separately versioned flow, partial coverage, expiry removal, explicit refresh without retired historical layers');
