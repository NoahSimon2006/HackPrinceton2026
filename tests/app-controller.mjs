import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
// Execute the actual map/coverage/property controller; the archived emissions
// implementation below ROAD_COLORS is intentionally outside this harness.
const source=(await readFile(new URL('../public/app.js',import.meta.url),'utf8')).split('const ROAD_COLORS')[0];
const flush=()=>new Promise(setImmediate);
function harness() {
  const els=new Map(),requests=[],markers=[];
  const element=()=>({value:'',checked:false,hidden:false,disabled:false,textContent:'',children:[],events:{},style:{},
    classList:{toggle(){},contains(){return false;}},append(...c){this.children.push(...c);},replaceChildren(...c){this.children=c;},setAttribute(){},addEventListener(n,f){this.events[n]=f;}});
  const $=id=>{if(!els.has(id))els.set(id,element());return els.get(id);};
  const point=(x,y)=>({x,y,add(p){return point(x+p.x,y+p.y);},subtract(p){return point(x-p.x,y-p.y);},multiplyBy(n){return point(x*n,y*n);},divideBy(n){return point(x/n,y/n);},distanceTo(p){return Math.hypot(x-p.x,y-p.y);},equals(p){return x===p.x&&y===p.y;}});
  const latLng=(a,b)=>Array.isArray(a)?{lat:a[0],lng:a[1]}:typeof a==='object'?a:{lat:a,lng:b};
  const layer=()=>({addTo(){return this;},remove(){},clearLayers(){markers.length=0;},on(){},bindPopup(){return this;},openPopup(){}});
  const map={center:latLng([34.05,-118.25]),zoom:17,events:{},dragging:{_draggable:{on(){}},disable(){},enable(){}},
    setView(p,z){this.center=latLng(p);this.zoom=z;return this;},getCenter(){return this.center;},getZoom(){return this.zoom;},getMinZoom(){return 10;},getMaxZoom(){return 20;},createPane(){},getPane(){return{style:{}};},
    getSize(){return point(2000,1000);},project(p){p=latLng(p);return point(p.lng,p.lat);},unproject(p){return latLng(p.y,p.x);},
    getContainer(){return element();},on(n,f){this.events[n]=f;},fire(){},getBounds(){return{getWest:()=>-118.4,getSouth:()=>34,getEast:()=>-118.1,getNorth:()=>34.2};}};
  const L={map:()=>map,control:{zoom:()=>layer()},tileLayer:layer,layerGroup:layer,canvas:()=>({}),point,latLng,DomUtil:{getPosition:()=>point(0,0)},divIcon:()=>({}),marker:(position)=>{const m=layer();m.position=position;markers.push(m);return m;}};
  const context=vm.createContext({L,loadEmissions(){},syncEmissionsVisibility(){},document:{getElementById:$,createElement:element},window:{addEventListener(){}},AbortController,setTimeout,clearTimeout,
    fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve:d=>resolve({ok:true,json:async()=>d}),reject}))});
  vm.runInContext(source,context);
  const covered={bounds:[-118.67,33.7,-118.1,34.35],features:[{geometry:{type:'Polygon',coordinates:[[[-118.4,34],[-118.1,34],[-118.1,34.3],[-118.4,34.3],[-118.4,34]]]}}]};
  return {context,$,map,requests,markers,covered};
}
{
 const h=harness();const p=h.context.loadCoverage();h.requests[0].resolve(h.covered);await p;
 // Former hand-authored northeast curve and full-viewport guard rejected this
 // covered center even though the user explicitly chose center-only limits.
 h.context.selectProperty({id:'edge',name:'Covered edge',lat:34.28,lon:-118.11});
 assert.equal(h.map.center.lat,34.28);assert.equal(h.map.center.lng,-118.11);assert.equal(h.map.zoom,17);
 const count=h.requests.length;h.context.selectProperty({id:'outside',name:'Outside',lat:34.31,lon:-118.11});
 assert.equal(h.requests.length,count);assert.match(h.$('status-title').textContent,/outside/);
}
{
 const h=harness();const p=h.context.loadCoverage();h.requests[0].resolve({...h.covered,status:'partial',excludedFeatures:1});await p;
 assert.equal(h.$('status-title').textContent,'Imagery ready');
 assert.match(h.$('status-detail').textContent,/invalid and excluded/);
 h.map.zoom=17;h.$('properties').checked=true;const refresh=h.context.updateProperties();
 h.requests[1].resolve({properties:[],total:0});await refresh;
 assert.match(h.$('status-detail').textContent,/invalid and excluded/,'a property refresh preserves the coverage warning');
 h.context.selectProperty({id:'excluded-area',name:'Excluded area',lat:34.05,lon:-118.5});
 assert.match(h.$('status-title').textContent,/outside/,'excluded source coverage cannot authorize navigation');
}
{
 const h=harness();h.map.zoom=17;h.$('properties').checked=true;
 const old=h.context.updateProperties(), newer=h.context.updateProperties();
 h.requests[1].resolve({properties:[{id:'new',name:'New',lat:34.05,lon:-118.25}],total:1});await newer;
 h.requests[0].resolve({properties:[{id:'old',name:'Old',lat:34.06,lon:-118.26}],total:99});await old;
 assert.equal(h.markers.length,1);assert.match(h.$('status-detail').textContent,/1 CoStar/);
 const pending=h.context.updateProperties();h.$('properties').checked=false;await h.context.updateProperties();
 h.requests[2].resolve({properties:[{id:'late',name:'Late',lat:34.05,lon:-118.25}],total:1});await pending;
 assert.equal(h.markers.length,0,'disabled properties cannot return from a late request');
}
{
 const h=harness();h.$('search').value='Kipling';const old=h.context.search(), newer=h.context.search();
 h.requests[1].resolve({results:[{id:'new',name:'Newest',address:'Address'}]});await newer;
 h.requests[0].resolve({results:[{id:'old',name:'Outdated',address:'Address'}]});await old;
 assert.equal(h.$('results').children[0].children[0].textContent,'Newest');
 const pending=h.context.search();h.context.selectProperty({id:'selected',name:'Kipling',lat:34.05,lon:-118.25});
 h.requests[2].resolve({results:[{id:'late',name:'Kipling',address:'Address'}]});await pending;
 assert.equal(h.$('results').hidden,true,'selection must not reopen a matching in-flight search');
}
console.log('PASS: center-only sourced coverage, property request generations and stale search isolation');

// Removing a workflow must not remove shared nodes used during real page boot.
{
  const html=await readFile(new URL('../public/index.html',import.meta.url),'utf8');
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  const available=new Set(ids);
  assert.equal(available.size,ids.length,'HTML ids must be unique');
  for(const file of ['planner.js','proposal.js','site-view.js']) {
    const script=await readFile(new URL('../public/'+file,import.meta.url),'utf8');
    for(const match of script.matchAll(/\$\("([^"]+)"\)/g)) assert.ok(available.has(match[1]),`${file} needs #${match[1]} in the page`);
  }
}
console.log('PASS: shared controller elements remain present after workflow removal');
