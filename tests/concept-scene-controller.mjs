import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile(new URL('../public/concept-scene.js',import.meta.url),'utf8');
// Only the GPU/module boundary is replaced. The production controller, identity
// checks, requests, dialog lifecycle and publication listeners run unchanged.
const controllerSource=source.replace(/import\((['"])[^'"]*concept-scene-renderer\.js[^'"]*\1\)/g,'loadRenderer()');
assert.notEqual(controllerSource,source,'the renderer module boundary must be explicit');
const flush=()=>new Promise(setImmediate);
const projectId='a'.repeat(32),inputHash='b'.repeat(64);
const published=()=>({projectId,siteId:'water-site',workflow:'water',inputRevision:2,stale:false,historical:false,
  proposal:{schema_version:1,development_fixture:false,site_id:'water-site',workflow:'water',revision:5,input_revision:2,input_hash:inputHash,
    status:'conditional',design:{kind:'bioretention',storage_depth_m:.15},proposed_geometry_ids:['water-option-1'],existing_geometry_ids:[],
    geometry:[{id:'water-option-1',type:'Feature',properties:{role:'proposed',revision:5},geometry:{type:'Polygon',coordinates:[]}}],
    metrics:[{id:'footprint_area',proposed:20,unit:'m²',revision:5,input_hash:inputHash}],recommendation:'Source-informed concept.'}});
const scene=()=>({schemaVersion:1,identity:{projectId,siteId:'water-site',workflow:'water',revision:5,inputRevision:2,inputHash,geometryId:'water-option-1'},
  origin:{crs:'EPSG:32611',easting:379000,northing:3770000,lon:-118.302,lat:34.059},units:'m',status:'conditional',savedAt:'2026-11-15T09:53:46Z',
  design:{kind:'bioretention',storage_depth_m:.15},areaM2:20,bounds:[-10,-10,10,10],focusBounds:[0,0,4,5],
  features:[{id:'water-option-1',kind:'intervention',geometry:{type:'Polygon',coordinates:[[[0,0],[4,0],[4,5],[0,5],[0,0]]]},heightM:.15,heightBasis:'Assumed effective ponding depth.'}],
  context:{status:'unavailable',sources:[],message:'No matching surrounding source geometry was archived.'},
  assumptions:['Flat reference ground; no surveyed elevations.']});

function harness({deferModule=false,rendererFails=false}={}) {
  const elements=new Map(),requests=[],renders=[],imports=[];
  const document={activeElement:null};
  const element=tag=>({tag,events:{},children:[],attributes:{},dataset:{},style:{},disabled:false,hidden:false,open:false,isConnected:true,textContent:'',checked:true,
    classList:{add(){},remove(){},toggle(){}},
    addEventListener(name,fn){this.events[name]=fn;},removeEventListener(name){delete this.events[name];},
    setAttribute(name,value){this.attributes[name]=String(value);},getAttribute(name){return this.attributes[name]??null;},
    removeAttribute(name){delete this.attributes[name];},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    focus(){if(!this.disabled)document.activeElement=this;},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},
    getClientRects(){return this.hidden?[]:[{}];},getBoundingClientRect(){return{left:0,right:1200,top:0,bottom:700,width:1200,height:700};}});
  const $=id=>{if(!elements.has(id))elements.set(id,element('div'));return elements.get(id);};
  document.createElement=element;document.getElementById=$;
  const map={handlers:{},on(name,fn){(this.handlers[name]??=[]).push(fn);},fire(name,event){for(const fn of this.handlers[name]??[])fn(event);}};
  const rendererModule={createConceptScene(container,data,options){
    if(rendererFails)throw new Error('WebGL unavailable');
    const rendered={data,options,disposed:false,modes:[],camera:{position:[20,30,20],target:[0,0,0],zoom:1},
      setMode(mode){this.modes.push(mode);},reset(){},top(){},rotate(){},zoom(){},setContextVisible(){},
      cameraState(){return structuredClone(this.camera);},geometrySummary(){return{areaM2:20,interventions:1};},
      dispose(){this.disposed=true;}};
    renders.push(rendered);return rendered;
  }};
  const loadRenderer=()=>deferModule?new Promise(resolve=>imports.push({resolve:()=>resolve(rendererModule)})):Promise.resolve(rendererModule);
  const json=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
  $('open-concept-scene').focus();
  vm.runInNewContext(controllerSource,{$,map,json,loadRenderer,document,URLSearchParams,AbortController,structuredClone,console,
    window:{},setTimeout,clearTimeout});
  return{$,map,document,requests,renders,imports};
}

async function open(h,data=scene()) {
  h.$('open-concept-scene').focus();
  const pending=h.$('open-concept-scene').events.click();
  assert.equal(h.requests.length>0,true);
  h.requests.at(-1).resolve(data);await pending;await flush();
  return h.renders.at(-1);
}

// User initiation and one shared renderer/camera across the comparison modes.
{
  const h=harness();h.$('planning-brief').focus();h.map.fire('proposaldisplay',published());
  assert.equal(h.document.activeElement,h.$('planning-brief'),'publishing a footprint must not steal focus before 3D was opened');
  assert.equal(h.requests.length,0,'publication must not fetch/render a scene automatically');
  assert.equal(h.$('open-concept-scene').disabled,false);
  const rendered=await open(h);
  const query=new URL(h.requests[0].url,'http://localhost').searchParams;
  assert.equal(query.get('projectId'),projectId);assert.equal(query.get('inputHash'),inputHash);
  assert.equal(query.get('revision'),'5');assert.equal(query.get('geometryId'),'water-option-1');
  assert.equal(h.$('concept-scene-dialog').open,true);
  const camera=rendered.cameraState();
  h.$('concept-scene-existing').events.click();h.$('concept-scene-proposed').events.click();
  assert.deepEqual(rendered.modes.slice(-2),['existing','proposed']);
  assert.equal(h.renders.length,1,'switching views must reuse the same scene/camera');
  assert.deepEqual(rendered.cameraState(),camera);
  h.$('concept-scene-close').events.click();
  assert.equal(h.$('concept-scene-dialog').open,false);assert.equal(rendered.disposed,true);
  assert.equal(h.document.activeElement,h.$('open-concept-scene'));
}

// Backend identity must still match the exact displayed publication at resolve.
for(const change of [
  d=>{d.identity.projectId='c'.repeat(32);},d=>{d.identity.siteId='another-site';},
  d=>{d.identity.workflow='street';},d=>{d.identity.revision=4;},
  d=>{d.identity.inputRevision=1;},d=>{d.identity.inputHash='d'.repeat(64);},
  d=>{d.identity.geometryId='another-footprint';},
]) {
  const h=harness();h.map.fire('proposaldisplay',published());const data=scene();change(data);
  await open(h,data);assert.equal(h.renders.length,0,'mismatched scene identity cannot render');
  assert.match(h.$('concept-scene-status').textContent,/unavailable|match|changed|invalid/i);
}

// No drawing fixtures, no implicit selection from an all-rejected comparison.
{
  const h=harness(),fixture=published();fixture.proposal.development_fixture=true;
  h.map.fire('proposaldisplay',fixture);assert.equal(h.$('open-concept-scene').disabled,true);
  h.map.fire('proposaldisplay',{proposal:null});assert.equal(h.$('open-concept-scene').disabled,true);
  assert.equal(h.requests.length,0);assert.equal(h.renders.length,0);
}

// Closing or changing the selected site while geometry loads invalidates the
// response; a completed network request cannot reopen the old scene.
for(const action of [
  h=>h.$('concept-scene-close').events.click(),
  h=>h.map.fire('plannersite',{siteId:'another-site',workflow:'water',inputRevision:0}),
  h=>h.map.fire('proposaldisplay',{proposal:null}),
  h=>{const next=published();next.proposal={...next.proposal,revision:6};h.map.fire('proposaldisplay',next);},
]) {
  const h=harness();h.map.fire('proposaldisplay',published());
  const pending=h.$('open-concept-scene').events.click();const request=h.requests[0];
  action(h);request.resolve(scene());await pending;await flush();
  assert.equal(h.renders.length,0);assert.equal(h.$('concept-scene-dialog').open,false);
  assert.equal(request.options.signal.aborted,true);
}

// The same generation guard applies after geometry has loaded, while the local
// renderer module is still importing.
{
  const h=harness({deferModule:true});h.map.fire('proposaldisplay',published());
  const pending=h.$('open-concept-scene').events.click();h.requests[0].resolve(scene());await flush();
  assert.equal(h.imports.length,1);h.$('concept-scene-close').events.click();
  h.imports[0].resolve();await pending;await flush();
  assert.equal(h.renders.length,0);assert.equal(h.$('concept-scene-dialog').open,false);
}

// Revision starts and input edits invalidate an open 3D rendering immediately.
for(const event of [
  ['plannerinputs',{inputRevision:3}],
  ['plannerinvestigation',{siteId:'water-site',workflow:'water',inputRevision:2,revision:6}],
]) {
  const h=harness();h.map.fire('proposaldisplay',published());const rendered=await open(h);
  h.map.fire(...event);
  assert.equal(rendered.disposed,true);assert.equal(h.$('concept-scene-dialog').open,false);
}

// Missing WebGL is confined to the optional view and remains actionable.
{
  const h=harness({rendererFails:true});h.map.fire('proposaldisplay',published());await open(h);
  assert.match(h.$('concept-scene-status').textContent,/unavailable|WebGL/i);
  assert.equal(h.$('concept-scene-retry').hidden,false);
  h.$('concept-scene-close').events.click();assert.equal(h.$('open-concept-scene').disabled,false);
}
console.log('PASS: conceptual scene identity, explicit initiation, shared comparison instance, stale/late isolation, disposal, focus and WebGL failure');
