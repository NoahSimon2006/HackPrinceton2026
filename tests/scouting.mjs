import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../public/scouting.js',import.meta.url),'utf8');
const flush=()=>new Promise(setImmediate);
function harness(saved=null) {
  const elements=new Map(),requests=[],events=[],timers=new Map(),groups=[];let timer=0;
  const clock={now:Date.now()};class TestDate extends Date {static now(){return clock.now;}}
  function element(tag='div') {return {tag,children:[],events:{},value:'',hidden:false,disabled:false,textContent:'',open:true,
    append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;},
    addEventListener(type,fn){this.events[type]=fn;},setAttribute(key,value){this[key]=value;},scrollIntoView(){this.scrolled=true;}};}
  const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const map={handlers:{},fitBounds(){},setView(){},getBounds:()=>({getWest:()=>-118.30,getSouth:()=>34.055,getEast:()=>-118.295,getNorth:()=>34.07}),
    on(type,fn){this.handlers[type]=fn;},fire(type,data){events.push({type,data});this.handlers[type]?.(data);}};
  const layer=()=>({items:[],addTo(group){group.items?.push(this);return this;},clearLayers(){this.items=[];},getBounds:()=>({isValid:()=>true}),bindTooltip(){return this;},on(){return this;}});
  const L={layerGroup:()=>{const value=layer();groups.push(value);return value;},rectangle:layer,geoJSON:layer,circleMarker:layer,marker:layer,divIcon:x=>x};
  const storage=new Map(saved?[['planning-scout-street',saved]]:[]);
  vm.runInNewContext(source,{$,map,L,planningMode:'street',json:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject})),
    document:{createElement:element},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},Date:TestDate,AbortController,
    setTimeout:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clearTimeout:id=>timers.delete(id)});
  return {$,map,requests,events,timers,groups,clock,storage,
    start:()=> $('scout-form').events.submit({preventDefault(){}}),
    poll:async()=>{const entry=[...timers].find(([,v])=>v.ms===1500);assert.ok(entry,'expected a polling timer');timers.delete(entry[0]);entry[1].fn();await flush();}};
}
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
function find(node,predicate) {if(predicate(node))return node;for(const child of node.children){const result=find(child,predicate);if(result)return result;}return null;}
const findButton=(h,label)=>find(h.$('scout-results'),n=>n.tag==='button' && n.textContent===label);
const candidate=(id='c1')=>({id,label:`Location ${id}`,center:[-118.298,34.06],geometry:{type:'Point',coordinates:[-118.298,34.06]},
  environmental:{summary:'Terrain collection warrants investigation.',basis:'Screening, not measured runoff capture.'},feasibility:'Parcel overlap needs checking.',disruption:'Preserve access.',
  readiness:{summary:'Can investigate; drainage connection unknown.',missing:['Field drainage']},direction:'Rain garden',reason:'Distinct terrain signal.',evidence:[{id:'terrain',label:'Terrain area',value:500,unit:'m²',source:{provider:'USGS'}}]});
function result(status='running',candidates=[]) {return {id:'search1',runId:'run1',workflow:'street',status,goal:'Find improvements',bounds:[-118.30,34.055,-118.295,34.07],
  batches:status==='running'?[]:[{id:'batch1',candidates,summary:'Supported opportunity screening.',methodology:'Environmental screen first; readiness separate.'}],events:[]};}

{
  const h=harness();h.start();assert.equal(h.requests[0].url,'/api/scouts');
  h.requests[0].resolve(result());await flush();assert.equal(h.$('scout-start').disabled,true);
  await h.poll();h.requests[1].resolve(result('ready',[candidate()]));await flush();
  assert.match(text(h.$('scout-results')),/Data readiness · separate from priority/);
  assert.match(text(h.$('scout-results')),/USGS/);assert.equal(h.groups[1].items.length,2,'extent and numbered marker shown');
  assert.equal(h.events.filter(e=>e.type==='scoutselect').length,0,'publishing a shortlist does not choose or design a site');
  findButton(h,'Choose this location').events.click();assert.equal(h.requests[2].url,'/api/scouts/select');
  h.requests[2].resolve({project:{id:'project1',snapshot:{workflow:'street'}},candidate:candidate(),search:{...result('ready',[candidate()]),selected:{candidateId:'c1',projectId:'project1'}}});await flush();
  assert.equal(h.events.find(e=>e.type==='scoutselect').data.project.id,'project1');assert.equal(h.$('scouting').open,false);
  assert.equal(h.requests.some(r=>r.url.includes('/site-analysis')),false,'choosing never triggers design analysis');
}
{
  const h=harness();h.start();h.$('scout-area').events.click();
  h.requests[0].resolve(result());await flush();
  assert.equal(h.$('scout-results').children.length,0,'area change invalidates a late start response');
  assert.equal(h.requests[1].url,'/api/scouts/cancel','accepted late POST is canceled server-side');
  assert.equal(JSON.parse(h.requests[1].options.body).runId,'run1','late cancellation targets its own run');
}
{
  const h=harness();h.start();h.requests[0].resolve(result());await flush();await h.poll();
  h.$('scout-cancel').events.click();assert.equal(h.requests[1].options.signal.aborted,true);
  h.requests[1].resolve(result('ready',[candidate()]));await flush();
  assert.equal(h.$('scout-results').children.length,0,'canceled poll cannot republish candidates');
  assert.equal(h.$('scout-start').disabled,false);
}
{
  const h=harness();h.start();h.requests[0].resolve(result());await flush();await h.poll();
  h.map.fire('plannerworkspace',{mode:'water'});h.requests[1].resolve(result('ready',[candidate()]));await flush();
  assert.equal(h.$('scout-results').children.length,0,'previous workflow cannot repaint current search');
  assert.match(h.$('scout-goal').value,/stormwater/);
}
{
  const h=harness();h.start();h.requests[0].resolve(result('ready',[candidate()]));await flush();
  h.$('scout-more').events.click();assert.equal(JSON.parse(h.requests[1].options.body).searchId,'search1');
  const next={...result(),batches:result('ready',[candidate()]).batches};h.requests[1].resolve(next);await flush();
  assert.match(text(h.$('scout-results')),/Location c1/,'previous batch remains while more research runs');
  await h.poll();h.requests[2].resolve({...result('ready',[candidate()]),batches:[...next.batches,{id:'batch2',candidates:[candidate('c2')]}]});await flush();
  assert.match(text(h.$('scout-results')),/Earlier locations/);assert.match(text(h.$('scout-results')),/Location c1/);assert.match(text(h.$('scout-results')),/Location c2/);
  assert.equal(h.$('scout-results').children.length,2,'new and previous batches retained');
}
{
  const h=harness('search1');assert.equal(h.requests[0].url,'/api/scouts?id=search1');
  h.requests[0].resolve(result('ready',[{id:'old',available:false,resumeNotice:'Refresh current traffic before choosing.'}]));await flush();
  assert.match(text(h.$('scout-results')),/Refresh current traffic/);assert.equal(findButton(h,'Choose this location'),null);
  assert.equal(h.groups[1].items.length,0,'archived traffic has no stale map geometry');
}
{
  const h=harness();const c={...candidate(),expiresAt:new Date(h.clock.now+5000).toISOString()};
  h.start();h.requests[0].resolve(result('ready',[c]));await flush();assert.ok(findButton(h,'Choose this location'));
  h.clock.now+=6000;const expiry=[...h.timers.values()].find(t=>t.ms!==1500);assert.ok(expiry);expiry.fn();
  assert.equal(findButton(h,'Choose this location'),null);assert.equal(h.groups[1].items.length,0);
}
{
  const h=harness();h.start();h.requests[0].resolve(result('ready',[]));await flush();
  assert.match(h.$('scout-status').textContent,/No supported locations/);
  h.map.getBounds=()=>({getWest:()=>-119,getSouth:()=>34,getEast:()=>-118,getNorth:()=>35});
  h.$('scout-area').events.click();assert.match(h.$('scout-status').textContent,/Zoom in/);
}
{
  const h=harness();h.start();const value=result('ready',[candidate()]);
  value.batches[0].review={findings:[{candidate_id:'c1',text:'A goal-specific investigation finding.',fact_ids:['terrain']},
    {candidate_id:'c1',text:'Invalid citation must not display.',fact_ids:['unknown']}]};value.batches[0].exhausted=true;
  h.requests[0].resolve(value);await flush();
  assert.match(text(h.$('scout-results')),/Agent assessment/);assert.match(text(h.$('scout-results')),/goal-specific/);
  assert.doesNotMatch(text(h.$('scout-results')),/Invalid citation/);assert.ok(findButton(h,'[1]'));
  assert.equal(findButton(h,'[1]').title,'Terrain area');assert.equal(h.$('scout-more').hidden,true);
  const card=find(h.$('scout-results'),n=>n.tag==='article'),investigation=find(card,n=>n.className==='scout-investigation');
  assert.equal(investigation.open,false,'full investigation starts collapsed for desktop scanning');
  assert.match(text(investigation),/goal-specific/);assert.match(text(investigation),/Feasibility/);assert.match(text(investigation),/Field drainage/);
  assert.ok(card.children.find(n=>n.className==='scout-readiness'),'readiness remains visible outside investigation');
  assert.ok(card.children.find(n=>n.className==='scout-actions'),'selection actions remain visible outside investigation');
  assert.match(text(card),/Map location 1 · 34.06000, -118.29800/,'unmatched locations remain unambiguous');
  assert.equal(find(h.$('scout-results'),n=>n.className==='scout-method').open,false,'comparison method does not dominate the shortlist');
}
{
  const h=harness();h.start();const value=result('ready',[candidate()]);
  value.batches[0].review={findings:[{candidate_id:'c1',text:'Stale agent interpretation.',fact_ids:['terrain']}]};value.batches[0].reviewStale=true;
  h.requests[0].resolve(value);await flush();assert.doesNotMatch(text(h.$('scout-results')),/Stale agent interpretation/);
}
{
  const h=harness();h.start();h.requests[0].resolve(result('ready',[candidate()]));await flush();
  h.$('scout-more').events.click(); // A delayed show-more response shares the saved search id.
  h.$('scout-cancel').events.click();h.$('scout-more').events.click();
  h.requests[2].resolve({...result(),runId:'newer-run',batches:result('ready',[candidate()]).batches});await flush();
  h.requests[1].resolve({...result(),runId:'older-run',batches:result('ready',[candidate()]).batches});await flush();
  assert.equal(h.requests[3].url,'/api/scouts/cancel');assert.equal(JSON.parse(h.requests[3].options.body).runId,'older-run');
  assert.equal(h.$('scout-start').disabled,true,'late old response does not change current running UI');
}
console.log('PASS: scouting publication, explicit selection, area/cancel/workflow races, history, restore, live expiry and empty coverage');
