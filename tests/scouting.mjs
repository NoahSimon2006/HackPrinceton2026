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
    document:{createElement:element,getElementById:id=>find($('scout-results'),node=>node.id===id)},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},Date:TestDate,AbortController,
    setTimeout:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clearTimeout:id=>timers.delete(id)});
  return {$,map,requests,events,timers,groups,clock,storage,
    start:()=> $('scout-form').events.submit({preventDefault(){}}),
    poll:async()=>{const entry=[...timers].find(([,v])=>v.ms===1500);assert.ok(entry,'expected a polling timer');timers.delete(entry[0]);entry[1].fn();await flush();}};
}
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
const visibleText=node=>[node.textContent,...(node.tag==='details' && !node.open?node.children.filter(child=>child.tag==='summary'):node.children).map(visibleText)].join(' ');
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
  assert.match(visibleText(h.$('scout-results')),/Check turning queues/);
  assert.match(visibleText(h.$('scout-results')),/Terrain area: 500 m²/);
  assert.doesNotMatch(visibleText(h.$('scout-results')),/Terrain collection warrants investigation/);
  assert.doesNotMatch(visibleText(h.$('scout-results')),/impact unassessed|Evidence available/);
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
  assert.equal(h.$('scout-results')['data-selectable-count'],'0');
  assert.doesNotMatch(h.$('scout-status').textContent,/Choose a location/);
}
{
  const h=harness();const c={...candidate(),expiresAt:new Date(h.clock.now+5000).toISOString()};
  h.start();h.requests[0].resolve(result('ready',[c]));await flush();assert.ok(findButton(h,'Choose this location'));
  h.clock.now+=6000;const expiry=[...h.timers.values()].find(t=>t.ms!==1500);assert.ok(expiry);expiry.fn();
  assert.ok(findButton(h,'Choose this location'),'a source reading expiring never removes the place choice');
  assert.equal(h.groups[1].items.length,2,'the saved place remains on the map');
  assert.match(visibleText(h.$('scout-results')),/Traffic may have changed/);
  findButton(h,'Choose this location').events.click();
  assert.equal(h.requests[1].url,'/api/scouts/select','a saved location can be chosen after traffic expires');
}
{
  const h=harness();h.start();h.requests[0].resolve(result('ready',[]));await flush();
  assert.match(h.$('scout-status').textContent,/No locations found with the available data/);
  assert.match(visibleText(h.$('scout-results')),/pick a spot directly/);
  h.map.getBounds=()=>({getWest:()=>-119,getSouth:()=>34,getEast:()=>-118,getNorth:()=>35});
  h.$('scout-area').events.click();assert.match(h.$('scout-status').textContent,/Zoom in/);
}
{
  const h=harness();h.start();const value=result('ready',[candidate()]);
  value.batches[0].review={findings:[{candidate_id:'c1',summary:'Trace the drainage route for your goal.',text:'A goal-specific investigation finding.',fact_ids:['terrain']},
    {candidate_id:'c1',text:'Invalid citation must not display.',fact_ids:['unknown']}]};value.batches[0].exhausted=true;
  h.requests[0].resolve(value);await flush();
  assert.match(text(h.$('scout-results')),/Agent assessment/);assert.match(text(h.$('scout-results')),/goal-specific/);
  assert.doesNotMatch(text(h.$('scout-results')),/Invalid citation/);assert.ok(findButton(h,'[1]'));
  assert.equal(findButton(h,'[1]').title,'Terrain area');assert.equal(h.$('scout-more').hidden,true);
  const card=find(h.$('scout-results'),n=>n.tag==='article'),investigation=find(card,n=>n.className==='scout-investigation');
  assert.equal(investigation.open,false,'full investigation starts collapsed for desktop scanning');
  assert.match(visibleText(card),/Trace the drainage route/,'compact agent advice is visible without opening evidence');
  assert.match(text(investigation),/goal-specific/,'full agent finding remains in the details');assert.match(text(investigation),/Feasibility/);assert.match(text(investigation),/Field drainage/);
  assert.match(text(investigation),/Evidence available/,'readiness belongs with detailed evidence');
  assert.ok(card.children.find(n=>n.className==='scout-next-step'),'next action remains visible outside investigation');
  findButton(h,'[1]').events.click();
  assert.equal(investigation.open,true,'citation opens the supporting evidence');
  assert.ok(find(investigation,n=>n.id==='scout-evidence-c1-terrain').scrolled,'citation brings its exact fact into view');
  assert.ok(card.children.find(n=>n.className==='scout-actions'),'selection actions remain visible outside investigation');
  assert.match(text(card),/Map location 1 · 34.06000, -118.29800/,'unmatched locations remain unambiguous');
  assert.equal(find(h.$('scout-results'),n=>n.className==='scout-method').open,false,'comparison method does not dominate the shortlist');
}
{
  const h=harness();h.start();const value=result('ready',[candidate()]);
  value.batches[0].review={findings:[{candidate_id:'c1',text:'Stale agent interpretation.',fact_ids:['terrain']}]};value.batches[0].reviewStale=true;
  value.batches[0].candidates[0].feedback={headline:'Check the current slowdown',observation:'Speed is now 45% of free flow.',relevance:'Compare the slow approach with your access goal.',nextStep:'Check the loading entrance first.',tradeoff:'Keep deliveries possible.',factIds:['terrain']};
  h.requests[0].resolve(value);await flush();assert.doesNotMatch(text(h.$('scout-results')),/Stale agent interpretation/);
  assert.match(text(h.$('scout-results')),/Speed is now 45%/,'source guidance survives stale agent review in the details');
  assert.match(visibleText(h.$('scout-results')),/Check the loading entrance first/);
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
{
  const h=harness();h.start();const first=candidate(),second=candidate('c2');
  first.feedback={headline:'Investigate the loading approach',observation:'A specific current slowdown.',relevance:'This helps target your delivery-access investigation.',nextStep:'Inspect curb activity at the entrance.',tradeoff:'Retain access for delivery vehicles.',factIds:['terrain']};
  second.feedback={headline:'Check the second approach',observation:'A different source observation.',relevance:'A second option for the same goal.',nextStep:'Observe the crossing before changing signals.',tradeoff:'Retain pedestrian crossing time.',factIds:['unknown']};
  const value=result('ready',[first,second]);
  value.goal='Keep delivery access <script>alert(1)</script>';
  value.batches[0].feedbackGoal=value.goal;value.batches[0].agentStatus='partial';
  value.batches[0].goalChecks=['Keep delivery entrances clear.'];
  value.batches[0].warnings=['Only part of this map area has traffic data.'];
  value.batches[0].review={findings:[{candidate_id:'c1',summary:'Check the entrance for delivery conflicts.',text:'The entrance deserves attention for this goal.',fact_ids:['terrain']}]};
  h.requests[0].resolve(value);await flush();
  const output=h.$('scout-results'),visible=visibleText(output),method=find(output,n=>n.className==='scout-method');
  assert.match(text(method),/Your goal: Keep delivery access <script>alert\(1\)<\/script>/,'the submitted goal is rendered as plain text inside search details');
  assert.equal(find(output,n=>n.tag==='script'),null);
  assert.equal(text(output).split('Keep delivery entrances clear.').length-1,1,'shared goal checks appear once per search');
  for(const phrase of ['A specific current slowdown.','delivery-access investigation','Inspect curb activity','Retain access','The entrance deserves attention','A different source observation.','Observe the crossing']) assert.ok(text(output).includes(phrase),phrase);
  assert.match(visible,/Check the entrance for delivery conflicts/,'one short agent summary leads the compact card');
  assert.doesNotMatch(visible,/delivery-access investigation|Retain access|Inspect curb activity/,'the card does not repeat the full source advice beside its agent summary');
  assert.doesNotMatch(visible,/Only part of this map area|specialist reviews could not finish|partial agent assessment/,'data limits do not obscure advice');
  assert.match(text(method),/Only part of this map area|agent review could not finish/);
  const secondCard=find(output,n=>n.id==='scout-candidate-c2');
  assert.equal(find(secondCard,n=>n.className==='scout-citation'),null,'unknown source feedback citations are omitted');
}
{
  const h=harness();h.start();const c=candidate();
  c.expiresAt=h.clock.now+1000;c.feedback={headline:'Saved slowdown',observation:'At search time, traffic was slower here.',nextStep:'Check the entrances along this stretch.',factIds:['terrain']};
  const value=result('ready',[c]);value.batches[0].summary='Saved speed comparison.';
  value.batches[0].snapshotAt='2026-11-15T12:32:31Z';
  value.batches[0].review={findings:[{candidate_id:'c1',text:'Saved specialist finding.',fact_ids:['terrain']}]};
  h.requests[0].resolve(value);await flush();
  const article=find(h.$('scout-results'),n=>n.tag==='article');
  const investigation=find(article,n=>n.className==='scout-investigation');
  findButton(h,'[1]').events.click();
  assert.equal(investigation.open,true);
  assert.match(visibleText(h.$('scout-results')),/At search time, traffic was slower here/);
  h.clock.now+=2000;[...h.timers.values()].find(t=>t.ms!==1500).fn();
  assert.strictEqual(find(h.$('scout-results'),n=>n.tag==='article'),article,'source expiry updates only its notice, leaving reading position and focus intact');
  assert.equal(investigation.open,true,'expiry does not close supporting evidence');
  for(const phrase of ['Saved speed comparison.','Saved specialist finding.','At search time, traffic was slower here.','Check the entrances along this stretch.','Terrain area'])
    assert.ok(text(h.$('scout-results')).includes(phrase),`expiry retains ${phrase}`);
  assert.match(visibleText(h.$('scout-results')),/Saved results/);
  assert.match(visibleText(h.$('scout-results')),/Traffic may have changed/);
  assert.ok(findButton(h,'Choose this location'));
  assert.equal(h.requests.length,1,'source expiry makes no automatic provider or agent request');
  const restored=harness('search1');value.batches[0].evidenceFreshness='snapshot';
  restored.requests[0].resolve(value);await flush();
  assert.match(text(restored.$('scout-results')),/Saved specialist finding/,'reload preserves the saved answer in details');
  assert.match(visibleText(restored.$('scout-results')),/Check the entrances along this stretch/,'the source action stays visible when an older finding has no compact summary');
  assert.match(visibleText(restored.$('scout-results')),/Traffic may have changed/);
  assert.equal(restored.$('scout-results')['data-selectable-count'],'1');
  findButton(restored,'Choose this location').events.click();
  assert.equal(restored.requests[1].url,'/api/scouts/select','restored source snapshots remain selectable');
}
{
  const h=harness('search1'),first=candidate('compact'),legacy=candidate('legacy');
  first.evidence=[{id:'compact-signal',label:'Speed relative to free flow',value:53,unit:'%',source:{provider:'Traffic source'}}];
  first.feedback={headline:'Full source headline',observation:'The complete source observation includes measurements and explanation.',
    relevance:'A detailed explanation of the relationship to the goal.',nextStep:'The complete source investigation plan.',tradeoff:'The full loading access tradeoff.',factIds:['compact-signal'],
    brief:{headline:'Longest mapped slow stretch',metric:'Traffic was 47% slower than uncongested speed.',action:'Check queues along the full stretch before changing signals.'}};
  const longFinding='This detailed saved assessment describes the evidence and the checks needed at this candidate. '.repeat(5);
  const summary='Protect residential access here. Check queues at the driveways before changing signal timing.';
  legacy.evidence=[{id:'legacy-signal',label:'Speed relative to free flow',value:18,unit:'%',source:{provider:'Traffic source'}},
    {id:'legacy-length_m',label:'Mapped slow stretch',value:600,unit:'m',source:{provider:'Traffic source'}}];
  legacy.feedback={headline:'A legacy headline',observation:'A detailed old observation. '.repeat(20),nextStep:'An extensive saved investigation plan. '.repeat(20),factIds:['legacy-signal']};
  const value=result('ready',[first,legacy]);value.batches[0].summary='A long batch summary. '.repeat(20);
  value.batches[0].review={findings:[{candidate_id:'compact',summary,text:longFinding,fact_ids:['compact-signal']},
    {candidate_id:'legacy',text:longFinding,fact_ids:['legacy-signal']}]};
  h.requests[0].resolve(value);await flush();
  const output=h.$('scout-results'),compact=find(output,n=>n.id==='scout-candidate-compact'),old=find(output,n=>n.id==='scout-candidate-legacy');
  for(const card of [compact,old]) {
    assert.ok(visibleText(card).trim().split(/\s+/).length<=90,'the closed card stays within a readable word budget');
    assert.equal(card.children.filter(n=>n.className==='scout-metric').length,1,'the card leads with only one metric');
    assert.equal(card.children.filter(n=>n.tag==='details').length,1,'one disclosure holds all detail');
    assert.match(visibleText(card),/Details and sources/);
    assert.doesNotMatch(visibleText(card),/This detailed saved assessment/,'long findings are preserved without being sliced into previews');
    assert.ok(text(find(card,n=>n.className==='scout-investigation')).includes(longFinding),'the complete original agent answer is still accessible');
  }
  assert.ok(visibleText(compact).includes(summary),'a purpose-written compact agent summary is visible');
  assert.doesNotMatch(visibleText(compact),/Longest mapped slow stretch|Check queues along the full stretch/,'source reasoning is not repeated next to agent advice');
  assert.match(visibleText(old),/Traffic was 82% slower/,'older saved cards receive a metric derived from their structured evidence');
  assert.match(visibleText(old),/Walk the mapped stretch/,'older long source prose gets a complete concise action, not a cut-off sentence');
  assert.ok(text(output).includes(legacy.feedback.nextStep),'the full old investigation plan remains accessible');
  assert.doesNotMatch(visibleText(output),/A long batch summary/,'batch prose does not overwhelm the shortlist');
  assert.ok(text(output).includes(value.batches[0].summary),'the saved batch summary remains in search details');
}
{
  const h=harness(),c=candidate('no-metric');c.evidence=[];
  c.feedback={brief:{headline:'Keep deliveries moving',metric:'',action:'Check the loading entrance during deliveries before changing curb access.'}};
  h.start();h.requests[0].resolve(result('ready',[c]));await flush();
  const card=find(h.$('scout-results'),n=>n.id==='scout-candidate-no-metric');
  assert.match(visibleText(card),/Keep deliveries moving/);
  assert.match(visibleText(card),/Check the loading entrance during deliveries/,'missing measurements do not discard meaningful goal-specific guidance');
  assert.equal(card.children.filter(n=>n.className==='scout-metric').length,0,'missing metrics do not create an empty or invented metric');
  assert.ok(findButton(h,'Choose this location'));
}
console.log('PASS: scouting publication, explicit selection, area/cancel/workflow races, saved feedback across expiry and reload, and empty coverage');
