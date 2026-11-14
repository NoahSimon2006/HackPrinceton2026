import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('../public/discovery.js',import.meta.url),'utf8');
const flush=()=>new Promise(setImmediate);
function harness(mobile=false) {
  const elements=new Map(),requests=[],events=[],rendered=[];
  const element=()=>({value:'',disabled:false,hidden:false,children:[],events:{},textContent:'',
    classList:{contains:()=>false},setAttribute(){},append(...children){this.children.push(...children);},
    replaceChildren(){this.children=[];},addEventListener(name,fn){this.events[name]=fn;}});
  const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const overlay={attached:false,clearLayers(){rendered.length=0;},addTo(){this.attached=true;},remove(){this.attached=false;}};
  const map={handlers:{},createPane(){},getPane:()=>({style:{}}),fitBounds(){},setView(){},closePopup(){},getCenter:()=>({lat:34.05,lng:-118.25}),getZoom:()=>17,
    fire(name,event){events.push({name,event});this.handlers[name]?.(event);},on(name,fn){this.handlers[name]=fn;},attributionControl:{addAttribution(){}}};
  const popup={setLatLng(){return this;},setContent(content){this.content=content;return this;},openOn(){return this;}};
  const json=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
  vm.runInNewContext(source,{$,map,json,planningMode:'street',coverage:null,AbortController,window:{matchMedia:()=>({matches:mobile})},
    document:{createElement:element,getElementById:$},
    L:{latLng:(lat,lng)=>({lat,lng}),layerGroup:()=>overlay,popup:()=>popup,circleMarker:()=>({}),
      geoJSON:(data,options)=>{for(const feature of data.features){const leaf={bindTooltip(){},on(name,fn){this[name]=fn;}};options.onEachFeature(feature,leaf);rendered.push({feature,leaf});}return{addTo(){}};}}});
  return{$,map,requests,events,rendered,overlay};
}
function data(workflow='street',id='counts') {
  return{schema:1,workflow,version:`${workflow}-hash`,bbox:[-118.26,34.04,-118.24,34.06],
    sources:{public:{label:'Official dataset',url:'https://example.org/source'}},
    layers:[{id,label:'Source layer',source:'public',status:'ready',unit:'vehicles reported',period:'2014-01-16',
      limitations:'Historical only',features:[{id:'one',type:'Feature',geometry:{type:'Point',coordinates:[-118.25,34.05]},
        properties:{label:'First & Alameda',center:[-118.25,34.05],value:18102,period:'2014-01-16'}}]}]};
}
{
  const h=harness();
  assert.equal(h.requests[0].url,'/api/discovery?workflow=street');
  h.requests[0].resolve(data());await flush();
  assert.equal(h.rendered.length,1);
  assert.match(h.$('discovery-limit').textContent,/CO₂, NOₓ and delay remain unavailable/);
  h.rendered[0].leaf.click();
  const selection=h.events.find(x=>x.name==='discoveryselect').event;
  assert.deepEqual(JSON.parse(JSON.stringify(selection.reference)),{version:'street-hash',layer:'counts',feature:'one'});
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
  assert.equal(h.$('discovery-retry').hidden,false);
  h.$('discovery-retry').events.click();
  h.requests[2].resolve(data('water','terrain'));await flush();
  h.requests[0].resolve(data());await flush();
  assert.equal(h.$('discovery-layer').value,'terrain','late traffic response cannot repaint stormwater');
  assert.equal(h.$('discovery-retry').hidden,true);
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
