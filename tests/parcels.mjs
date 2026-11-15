import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source = await readFile(new URL('../public/parcels.js', import.meta.url), 'utf8');
const flush = async () => { for (let i=0;i<5;i++) await new Promise(setImmediate); };
const feature = (id, date='2026-01-01') => ({type:'Feature',id,properties:{label:'Parcel boundary',date},geometry:{type:'Polygon',coordinates:[]}});
function harness({zoom=15, saved=null}={}) {
  const elements = new Map(), requests = [], events = {}, timers = new Map(), storage = new Map();
  let timerID=0;
  const el = id => {
    if (!elements.has(id)) elements.set(id, {checked:true,hidden:false,textContent:'',events:{},addEventListener(n,f){this.events[n]=f;}});
    return elements.get(id);
  };
  const layer = {features:[],visible:false,clearLayers(){this.features=[];},addData(d){this.features=d.features;},addTo(){this.visible=true;return this;},remove(){this.visible=false;}};
  const map = {zoom,west:-118.2438,south:34.0521,east:-118.2436,north:34.0523,
    getZoom(){return this.zoom;},getBounds(){return {getWest:()=>this.west,getEast:()=>this.east,getSouth:()=>this.south,getNorth:()=>this.north};},
    createPane(){},getPane(){return {style:{}};},on(n,f){events[n]=f;}};
  const context = vm.createContext({map,document:{getElementById:el},L:{canvas:()=>({}),geoJSON:()=>layer},
    localStorage:{getItem:()=>saved,setItem:(k,v)=>storage.set(k,v)},AbortController,Date,
    setTimeout(f){timers.set(++timerID,f);return timerID;},clearTimeout(id){timers.delete(id);},
    fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,reject,resolve:(features=[],status='ready')=>resolve({ok:true,json:async()=>({type:'FeatureCollection',features,status})})}))});
  vm.runInContext(source,context);
  const move=()=>{events.moveend(); for(const [key,fn] of timers){timers.delete(key);fn();}};
  return {map,el,layer,requests,move,events,storage};
}
{
  const h=harness(); assert.equal(h.requests.length,0); assert.match(h.el('parcel-status').textContent,/16/);
  h.map.zoom=16; h.move(); assert.equal(h.requests.length,1);
  h.requests[0].resolve([feature('a')]); await flush(); assert.equal(h.layer.features.length,1);
  h.move(); assert.equal(h.requests.length,1,'same cells reuse cache');
  h.el('parcels').checked=false; h.el('parcels').events.change();
  assert.equal(h.layer.visible,false);assert.equal(h.storage.get('map-parcels-visible'),'false');
  h.el('parcels').checked=true;h.el('parcels').events.change();assert.equal(h.layer.features.length,1);assert.equal(h.requests.length,1);
  h.map.zoom=15;h.events.zoomend();assert.equal(h.layer.visible,false);
}
{
  const h=harness({zoom:16});const old=h.requests[0];
  h.map.west+=.03;h.map.east+=.03;h.move();const newer=h.requests[1];
  newer.resolve([feature('new')]);await flush();old.resolve([feature('old')]);await flush();
  assert.deepEqual(Array.from(h.layer.features,f=>f.id),['new'],'late response cannot replace new viewport');
  h.map.west-=.03;h.map.east-=.03;h.move();assert.equal(h.requests.length,2);assert.equal(h.layer.features[0].id,'old');
}
{
  const h=harness({zoom:16});h.el('parcels').checked=false;h.el('parcels').events.change();
  assert.ok(h.requests[0].options.signal.aborted);h.requests[0].resolve([feature('late')]);await flush();
  assert.equal(h.layer.visible,false);assert.equal(h.layer.features.length,0);
}
{
  const h=harness({zoom:16});h.requests[0].reject(new Error('unavailable'));await flush();
  assert.equal(h.el('parcel-retry').hidden,false);assert.match(h.el('parcel-status').textContent,/couldn’t load/);
  h.el('parcel-retry').events.click();assert.equal(h.requests.length,2);h.requests[1].resolve();await flush();
  assert.match(h.el('parcel-status').textContent,/No Vexcel/);assert.equal(h.el('parcel-retry').hidden,true);
}
{
  const h=harness({zoom:16});h.map.east+=.004;h.move();
  assert.equal(h.requests.length,2,'at most two concurrent requests');
  h.requests[0].resolve([feature('shared','2025-01-01')]);await flush();
  h.requests[1].resolve([feature('shared')]);await flush();
  // Drain the bounded viewport queue; duplicate parcels must render only once.
  for(let index=2;index<h.requests.length;index++){h.requests[index].resolve([feature('shared')]);await flush();}
  assert.equal(h.layer.features.length,1);assert.equal(h.layer.features[0].properties.date,'2026-01-01');
}
{
  const h=harness({zoom:16,saved:'false'});assert.equal(h.requests.length,0);assert.equal(h.el('parcels').checked,false);
}
console.log('PASS: parcel zoom gate, remembered toggle, viewport cache, stale responses, request limits, deduplication and retry');
