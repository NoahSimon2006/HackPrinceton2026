import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const elements=new Map(), requests=[], layers=[];
const element=()=>({events:{},children:[],hidden:false,checked:false,disabled:false,textContent:'',attributes:{},
  addEventListener(n,f){this.events[n]=f;},setAttribute(n,v){this.attributes[n]=v;},
  append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;}});
const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
const map={setView(){},getZoom(){return 17;},handlers:{},createPane(){},getPane(){return{style:{}};},on(n,f){this.handlers[n]=f;},fire(n,e){this.handlers[n]?.(e);}};
const L={geoJSON(data,options){if(data.features.some(f=>f.geometry?.type==='Bad'))throw new Error('Invalid GeoJSON object.');const l={data,options,attached:false,addTo(){this.attached=true;},remove(){this.attached=false;}};layers.push(l);return l;}};
vm.runInNewContext(await readFile(new URL('../public/proposal.js',import.meta.url),'utf8'),{$,map,L,document:{createElement:element},URLSearchParams,AbortController,json:(url,opts)=>new Promise((resolve,reject)=>requests.push({url,opts,resolve,reject}))});
const select=(siteId='a',workflow='street',inputRevision=0)=>map.fire('plannersite',{siteId,workflow,center:{lat:34.03758,lng:-118.25313},inputRevision});
const response=(revision=1,site_id='a',workflow='street')=>({schema_version:1,site_id,workflow,revision,input_revision:0,input_hash:'hash'+revision,development_fixture:true,status:'fixture',geometry:[{properties:{revision}}],metrics:[{id:'footprint_area',proposed:revision*24,unit:'m²',revision,input_hash:'hash'+revision}],recommendation:'UI test only'});
const flush=()=>new Promise(setImmediate);
const text=el=>[el.textContent,...el.children.map(text)].join(' ');
select();$('load-proposal-fixture').events.click();requests[0].resolve(response());await flush();
assert.equal(layers[0].attached,true);assert.equal($('proposal-area').textContent,'24.0 m²');
assert.equal($('proposal-kind').textContent,'Development fixture');
$('show-proposal').checked=false;$('show-proposal').events.change();assert.equal(layers[0].attached,false);
$('show-proposal').checked=true;$('show-proposal').events.change();
$('revise-proposal-fixture').events.click();assert.equal(layers[0].attached,true,'keep old geometry until ready');requests[1].resolve(response(2));await flush();assert.equal(layers[0].attached,false);assert.equal(layers[1].attached,true);assert.equal($('proposal-area').textContent,'48.0 m²');
map.fire('plannerinputs',{inputRevision:1});assert.equal($('proposal-stale').hidden,false);
$('revise-proposal-fixture').events.click();select('b','water');requests[2].resolve(response(3));await flush();assert.equal($('proposal-review').hidden,true);assert.equal(layers[1].attached,false,'changing site removes prior design');
$('load-proposal-fixture').events.click();requests[3].resolve(response(1,'b','water'));await flush();assert.equal($('proposal-title').textContent,'Test treatment footprint');
$('revise-proposal-fixture').events.click();const bad=response(2,'b','water');bad.metrics[0].revision=1;requests[4].resolve(bad);await flush();assert.match($('proposal-message').textContent,/mismatch/);assert.equal(layers[2].attached,true,'bad revision cannot replace published geometry');
console.log('PASS: fixture toggles, atomic revisions, stale inputs, site/workflow isolation and rejected mixed revisions');

const result=(revision=1,input_revision=0,recommended='layout_a')=>{
  const proposal={...response(revision),development_fixture:false,status:recommended?'recommended':'rejected',
    input_revision,recommendation:recommended?'A simulated recommendation':'Keep-clear conflict',
    geometry:[{properties:{revision,layout:'layout_a'}}],access:{text:'Not assessed'},overlap:{text:'Mapped overlap checked'}};
  const rejected={...proposal,status:'rejected',recommendation:'Demand stranded',geometry:[{properties:{revision,layout:'layout_b'}}]};
  const comparison={site_id:'a',workflow:'street',revision,input_revision,input_hash:proposal.input_hash,
    count_date:'2011-11-08',peak_hour:'17:00',sheet_url:'https://example.org/official.pdf',
    results:{baseline:{co2_kg_per_hour:120,completion_share:.99,max_queue_m:{nb:43},max_noise_db:{nb:null}},
      layout_a:{co2_kg_per_hour:100,completion_share:.99,max_queue_m:{nb:40},max_noise_db:{nb:null}},
      layout_b:{co2_kg_per_hour:95,completion_share:.60,max_queue_m:{nb:70},max_noise_db:{nb:64}}},
    ranking:{recommended,reason:recommended?'Option meets rules':'No design improves the baseline without unacceptable tradeoffs.',verdicts:{
      layout_a:{eligible:!!recommended,ineligible_reasons:recommended?[]:['Keep-clear conflict'],tradeoffs:[]},
      layout_b:{eligible:false,ineligible_reasons:['Demand stranded'],tradeoffs:['Queue worsened']}}},
    checks:{layout_a:{parcel_overlap_m2:12,building_overlap_m2:0,access_conflicts:null,keep_clear_conflict:!recommended}},
    descriptions:{layout_a:'One lane reallocated',layout_b:'Alternate approach'},assumptions:['Generated signal timing; actual plan unavailable.']};
  return {siteId:'a',workflow:'street',inputRevision:input_revision,revision,
    proposal:recommended?structuredClone(proposal):null,comparison,alternatives:{layout_a:proposal,layout_b:rejected}};
};
select();map.fire('plannerresult',result());
const activeLayer=()=>layers.findLast(layer=>layer.attached);
const real=activeLayer();
assert.equal(real.attached,true);
assert.equal(real.options.style.dashArray,undefined,'real designs have a distinct solid style');
assert.equal($('proposal-kind').textContent,'Recommended');
assert.equal($('traffic-comparison').hidden,false);
assert.match(text($('comparison-table')),/Total CO₂/);
assert.match(text($('comparison-table')),/Not assessed/,'unknown metrics do not turn into zeros');
assert.match(text($('comparison-alternatives')),/Demand stranded/);
assert.match(text($('comparison-alternatives')),/Mapped access conflicts: Not assessed/);
assert.match(text($('comparison-assumptions')),/Generated signal timing/);
assert.match($('comparison-period').textContent,/2011-11-08/);
assert.equal($('revise-proposal-fixture').disabled,true,'real design revisions come through analysis');
map.fire('plannerinputs',{inputRevision:1});
assert.equal(real.attached,true,'old proposal remains visible while revision is pending');
assert.equal($('proposal-stale').hidden,false);assert.equal($('comparison-stale').hidden,false);
map.fire('plannerresult',result(2,0));assert.equal(activeLayer(),real,'late results from old markings cannot replace the design');
let mismatched=result(2,1);mismatched.comparison.input_hash='wrong';map.fire('plannerresult',mismatched);
assert.equal(activeLayer(),real);assert.match($('proposal-message').textContent,/mismatch/);
mismatched=result(2,1);mismatched.proposal.geometry[0].properties.layout='other';map.fire('plannerresult',mismatched);
assert.equal(activeLayer(),real,'a different layout cannot be presented as the recommendation');
mismatched=result(2,1);mismatched.proposal.development_fixture=true;map.fire('plannerresult',mismatched);
assert.equal(activeLayer(),real,'analysis results cannot masquerade as a fixture');
map.fire('plannerresult',result(2,1));assert.equal(real.attached,false);assert.equal(activeLayer()?.attached,true);
assert.equal($('proposal-stale').hidden,true);assert.equal($('comparison-stale').hidden,true);
const latest=activeLayer();map.fire('plannerresult',result(1,1));assert.equal(activeLayer(),latest,'older revisions cannot replace newer ones');
const unavailable=result(3,1,null);unavailable.comparison.status='unavailable';unavailable.comparison.results={};unavailable.comparison.ranking.reason='Verified count sheet unavailable';
map.fire('plannerresult',unavailable);
assert.equal(latest.attached,true,'source failure preserves the previous published geometry');
assert.equal($('traffic-comparison').hidden,false,'source failure preserves the previous comparison');
assert.match($('proposal-result-message').textContent,/Verified count sheet unavailable/);
assert.match($('proposal-map-caption').textContent,/previous result/);
map.fire('plannerinputs',{inputRevision:2});map.fire('plannerresult',result(4,2,null));
assert.equal(latest.attached,false,'valid no-recommendation result removes the old design');
assert.equal($('show-proposal').disabled,true);assert.equal($('proposal-review').hidden,true);
assert.equal($('traffic-comparison').hidden,false);assert.equal($('comparison-title').textContent,'No layout recommended');
assert.equal($('proposal-result-message').hidden,true,'completed comparisons clear earlier errors');
assert.match(text($('comparison-alternatives')),/Keep-clear conflict/);
const rejectedCard=$('comparison-alternatives').children[1];
rejectedCard.children.find(child=>child.textContent==='Show footprint on map').events.click();
const rejectedLayer=activeLayer();
assert.equal(rejectedLayer.attached,true);
assert.equal(rejectedLayer.data.features[0].properties.layout,'layout_b');
assert.equal($('proposal-kind').textContent,'Tested, rejected');
assert.equal($('proposal-summary').textContent,'Demand stranded');
$('show-proposal').checked=false;$('show-proposal').events.change();
assert.equal(rejectedLayer.attached,false);
select('b');map.fire('plannerresult',result(4,0));assert.equal($('traffic-comparison').hidden,true,'another site cannot receive this result');
select('a','water');map.fire('plannerresult',result(4,0));assert.equal($('traffic-comparison').hidden,true,'another workflow cannot receive this result');
console.log('PASS: real comparison, unknown metrics, strict verdicts, identity/hash matching, stale revisions and honest no-recommendation outcome');

// Explicit UI fixture: compare every displayed cell and the exact overlay geometry
// against one published revision, without requiring live providers or a favorable design.
select();
const parity=result(5,0);
parity.proposal.geometry[0].type='Feature';
parity.proposal.geometry[0].geometry={type:'Polygon',coordinates:[[[-118.25,34.03],[-118.2499,34.03],[-118.2499,34.0301],[-118.25,34.03]]]};
parity.alternatives.layout_a=structuredClone(parity.proposal);
parity.comparison.results.baseline={co2_kg_per_hour:467.1,co2_g_per_completed_vehicle:123.5,nox_g_per_hour:157.8,
  mean_delay_s:1233.5,completion_share:.6719,unable_to_enter_share:.3195,max_queue_m:{nb:207,eb:191.4},max_noise_db:{nb:76.61,eb:75.2}};
parity.comparison.checks.layout_a={detection_status:'unavailable',candidate_crosswalk_overlaps:null,candidate_driveway_overlaps:null};
map.fire('plannerresult',parity);
assert.deepEqual(JSON.parse(JSON.stringify(activeLayer().data.features)),parity.proposal.geometry,'overlay must use the published revision geometry unchanged');
const displayed=$('comparison-table').children[0].children[1].children.map(row=>row.children[1].textContent);
assert.deepEqual(displayed,['467.1','123.5','157.8','1,233.5','67.2','32','207','76.6']);
assert.match(text($('comparison-alternatives')),/Crossing\/driveway detection: Unavailable\. Overlapping crosswalk candidates: Not assessed\. Driveway candidates: Not assessed/);
assert.match($('comparison-revision').textContent,/Revision 5 · inputs 0 · hash5/);
assert.match($('proposal-revision').textContent,/Revision 5 · inputs 0 · hash5/);
console.log('PASS: published metric/geometry parity and unavailable detection display');

const beforeBadLayer=activeLayer(), beforeBadTable=text($('comparison-table'));
const badGeometry=result(6,0);badGeometry.alternatives.layout_b.geometry[0].geometry={type:'Bad'};
map.fire('plannerresult',badGeometry);
assert.equal(beforeBadLayer.attached,true);assert.equal(text($('comparison-table')),beforeBadTable,'geometry errors cannot publish new metrics beside old geometry');
assert.match($('comparison-revision').textContent,/Revision 5/);
const incomplete=result(6,0);incomplete.comparison.results.baseline.max_queue_m={nb:200,eb:null};incomplete.comparison.results.baseline.max_noise_db={nb:70,eb:null};
map.fire('plannerresult',incomplete);
const incompleteValues=$('comparison-table').children[0].children[1].children.map(row=>row.children[1].textContent);
assert.equal(incompleteValues[6],'Not assessed');assert.equal(incompleteValues[7],'Not assessed');
assert.match($('comparison-revision').textContent,/Revision 6/,'rejected geometry did not consume its revision');

// Retired manual water comparisons cannot publish a layout.
select('water-site','water');
map.fire('plannerresult',{siteId:'water-site',workflow:'water',inputRevision:0,revision:1,
  comparison:{site_id:'water-site',workflow:'water',input_revision:0,revision:1,input_hash:'a'.repeat(64),ranking:{},results:{baseline:{}}}});
assert.match($('proposal-result-message').textContent,/Only traffic comparisons/);

select('water','water');
const draft={...response(1,'water','water'),development_fixture:false,status:'draft',
  assumptions:['Ponding depth is a screening assumption.'],access:{text:'Keep-clear checked'},overlap:{text:'Mapped buildings avoided'}};
draft.metrics.push({id:'storage_volume',unit:'m³',proposed:1.2,revision:1,input_hash:draft.input_hash});
map.fire('plannerresult',{siteId:'water',workflow:'water',inputRevision:0,revision:1,proposal:draft});
assert.equal($('proposal-kind').textContent,'Draft concept');
assert.match(text($('proposal-water-metrics')),/Ponding storage 1.2 m³/);
assert.match(text($('proposal-water-metrics')),/Capture Not assessed/);
assert.match(text($('proposal-checks')),/Keep-clear checked/);
assert.match(text($('proposal-assumptions')),/Ponding depth/);
map.fire('plannerresult',{siteId:'water',workflow:'water',inputRevision:0,revision:2,draftQuestion:'Which driveway should stay clear?'});
assert.equal($('proposal-review').hidden,false,'a failed new placement keeps the previous footprint as a labeled reference');
assert.match($('proposal-result-message').textContent,/Which driveway should stay clear/);
assert.match($('proposal-map-caption').textContent,/previous result/);
console.log('PASS: draft screening metrics, unknown capture and specific placement question');

// Source-backed polygon concepts and their internal alternatives publish one
// coherent revision. History is read-only and never becomes the current study.
select('water','water',1);
const waterProposal=(revision,input_revision=1,area=30)=>({...response(revision,'water','water'),
  development_fixture:false,status:'conditional',input_revision,design:{kind:'bioretention'},
  geometry:[{properties:{revision},geometry:{type:'Polygon',coordinates:[]}}],
  metrics:[{id:'footprint_area',proposed:area,unit:'m²',revision,input_hash:'hash'+revision},
    {id:'storage_volume',proposed:area*.15,unit:'m³',revision,input_hash:'hash'+revision},
    {id:'captured_volume',proposed:null,unit:'m³',status:'unassessed',revision,input_hash:'hash'+revision}],
  recommendation:'Mapped planting area; drainage remains unverified.',assumptions:['No verified drainage connection.'],access:{text:'Mapped access avoided'},overlap:{text:'Mapped buildings avoided'}});
const previous=waterProposal(1,0,12),current=waterProposal(2,1,30),alternative=waterProposal(2,1,20);
const study={siteId:'water',workflow:'water',inputRevision:1,revision:2,proposal:current,alternatives:{compact:current,linear:alternative},
  waterPlan:{settings:{drainageAssumption:'unknown'},comparison:{selected:'compact',selectionBasis:'Comparable impact is unknown; this footprint avoids mapped operational constraints.',
    scenario:{name:'County rainfall screen',drainageAssumption:'unknown'},results:[{id:'compact',label:'Compact garden',status:'selected',reason:'Fits mapped open space.'},{id:'linear',label:'Linear strip',status:'eligible',reason:'Preserves the entrance.',
      decisions:[{source:'CoStar loading',decision:'The linear footprint stays outside the loading corridor on its own host.',evidence_ids:['other-host-loading']}]}]},
    decisions:[{source:'CoStar frontage',decision:'Preserved the mapped curb-cut frontage buffer.',evidence_ids:['frontage-1']}]},
  designHistory:[{revision:1,inputRevision:0,proposal:previous,savedAt:'2026-11-14T14:05:00+00:00'}]};
map.fire('plannerresult',study);
assert.equal($('water-design-review').hidden,false);
assert.equal($('proposal-title').textContent,'Bioretention concept');
assert.match(text($('proposal-water-metrics')),/Capture Not assessed/);
assert.match($('water-design-scenario').textContent,/Drainage connection is unknown/);
assert.match(text($('water-design-decisions')),/CoStar frontage: Preserved/);
assert.match(text($('water-design-decisions')),/frontage-1/);
assert.doesNotMatch($('proposal-revision').textContent,/Saved result/,'new live results are not labeled as replay');
$('water-design-alternatives').children[1].children.find(c=>c.textContent==='Inspect this footprint').events.click();
assert.equal($('proposal-area').textContent,'20.0 m²');
assert.match($('proposal-map-caption').textContent,/Alternative preview/);
assert.match(text($('water-design-decisions')),/CoStar loading: The linear footprint/);
assert.doesNotMatch(text($('water-design-decisions')),/Preserved the mapped curb-cut frontage buffer/);
assert.doesNotMatch(text($('water-design-decisions')),/Inspect source evidence/,'an alternative must not link its own refs to the selected concept facts');
assert.match($('water-design-selection').textContent,/Inspecting Linear strip/);
assert.match($('water-design-scenario').textContent,/saved concept and its constraints are unchanged/);
assert.equal($('water-design-alternatives').children.length,2,'alternative inspection keeps study controls available');
$('water-return-current').events.click();assert.equal($('proposal-area').textContent,'30.0 m²');
assert.match(text($('water-design-decisions')),/Preserved the mapped curb-cut frontage buffer/);
assert.doesNotMatch(text($('water-design-decisions')),/CoStar loading/);
assert.match(text($('water-design-decisions')),/Inspect source evidence/);
$('water-design-history').children[0].events.click();
assert.equal($('proposal-area').textContent,'12.0 m²');
assert.match($('proposal-map-caption').textContent,/Earlier revision 1 · read-only/);
assert.match($('water-design-scenario').textContent,/current concept is unchanged/);
assert.match($('proposal-revision').textContent,/Saved result · published 2026-11-14 14:05:00 UTC/);
assert.match($('water-design-scenario').textContent,/reopening does not rerun/);
$('water-return-current').events.click();assert.equal($('proposal-area').textContent,'30.0 m²');
assert.doesNotMatch($('proposal-revision').textContent,/Saved result/,'returning to the live result clears the history label');
map.fire('plannerinputs',{inputRevision:2});assert.equal($('water-design-stale').hidden,false);
map.fire('plannerresult',{...study,revision:3});assert.equal($('proposal-area').textContent,'30.0 m²','old inputs cannot publish a new study');
const scenarioProposal=waterProposal(3,2,40);scenarioProposal.metrics[2]={...scenarioProposal.metrics[2],proposed:1.2,status:'calculated'};
map.fire('plannerresult',{...study,revision:3,inputRevision:2,proposal:scenarioProposal,alternatives:{},waterPlan:{settings:{drainageAssumption:'marked_connected'},comparison:{scenario:{name:'One-inch explicit scenario'}}}});
assert.match($('water-design-scenario').textContent,/What-if: marked runoff areas are assumed connected/);
assert.match(text($('proposal-water-metrics')),/Capture 1.2 m³/);
select('other','water');assert.equal($('water-design-review').hidden,true);
console.log('PASS: stormwater alternatives, separate unknown/assumed capture, source decisions, read-only history and revision isolation');

select('water','water',3);
map.fire('plannerrestore',{...study,savedAt:'2026-11-14T14:10:00+00:00',historicalReference:true});
assert.equal($('proposal-area').textContent,'30.0 m²');
assert.equal($('proposal-stale').hidden,false);
assert.match($('proposal-map-caption').textContent,/saved previous result/);
assert.match($('proposal-revision').textContent,/Saved result · published 2026-11-14 14:10:00 UTC/);
assert.match(text($('water-design-decisions')),/frontage-1/,'historical source IDs remain readable');
assert.doesNotMatch(text($('water-design-decisions')),/Inspect source evidence/,'a failed attempt ledger cannot inspect historical design evidence');
map.fire('plannerrestore',{...study,savedAt:'invalid',historicalReference:true});
assert.match($('proposal-revision').textContent,/Saved result · original publication time unavailable/);
const next=waterProposal(3,3,60),rejected=waterProposal(3,3,15);
const nextStudy={...study,revision:3,inputRevision:3,proposal:next,
  alternatives:{compact:waterProposal(3,3,22),linear:rejected},
  waterPlan:{...study.waterPlan,comparison:{...study.waterPlan.comparison,results:[
    {id:'compact',label:'Compact',status:'selected',inputHash:next.input_hash,revision:3},
    {id:'linear',label:'Linear',status:'rejected',reason:'Overlaps the protected loading entrance.'}]}}};
map.fire('plannerresult',nextStudy);
assert.equal($('proposal-area').textContent,'30.0 m²','mismatched selected alternative cannot replace the prior footprint');
assert.match($('proposal-result-message').textContent,/selection and geometry mismatch/);
nextStudy.alternatives.compact=next;map.fire('plannerresult',nextStudy);
assert.equal($('proposal-area').textContent,'60.0 m²');
assert.doesNotMatch($('proposal-revision').textContent,/Saved result/,'a successful live revision clears the replay notice');
assert.doesNotMatch($('water-design-scenario').textContent,/Saved result/);
$('water-design-alternatives').children[1].children.find(c=>c.textContent==='Inspect this footprint').events.click();
assert.match($('proposal-kind').textContent,/rejected/);
assert.match($('proposal-summary').textContent,/Rejected: Overlaps the protected loading entrance/);
assert.equal(activeLayer().options.style.color,'#ffaf98');
assert.match(text($('water-design-decisions')),/No separate sponsor decision ledger/);
assert.doesNotMatch(text($('water-design-decisions')),/Preserved the mapped curb-cut frontage buffer/,'missing alternative decisions cannot borrow the selected ledger');
$('water-return-current').events.click();assert.equal($('proposal-area').textContent,'60.0 m²');
map.fire('plannerrestore',{...study,siteId:'wrong'});assert.equal($('proposal-area').textContent,'60.0 m²');
console.log('PASS: restored stale geometry, selected-alternative parity and clearly rejected footprint inspection');

// CP6 keeps complete earlier evaluations inspectable without replacing the
// canonical current result, and separates priority from source readiness.
select('a','street',2);
const olderTraffic=result(7,1,null), latestTraffic=result(8,2);
latestTraffic.comparison.ranking.policy='environmental-priority-v1';
latestTraffic.comparison.ranking.selection_order=['Total CO₂ reduction','Feasibility and disruption'];
latestTraffic.trafficPlan={revisionSummary:'Shortened the eastbound reallocation while preserving keep-clear areas.',
  readiness:{status:'partial',label:'The count cohort is reproducible; field access remains unresolved.',missing:['Confirm loading access.']},
  sourceDecisions:[{source:'Vexcel and CoStar',decision:'The eastbound footprint avoids the mapped operational frontage.',fact_id:'traffic-frontage'}]};
latestTraffic.trafficDesignHistory=[{revision:7,inputRevision:1,savedAt:'2026-11-14T15:00:00Z',proposal:null,comparison:olderTraffic.comparison,alternatives:olderTraffic.alternatives,
  trafficPlan:{readiness:{label:'Earlier count-based evaluation.'}}}];
map.fire('plannerresult',latestTraffic);
assert.match($('comparison-policy').textContent,/Total CO₂ reduction → Feasibility and disruption/);
assert.match($('comparison-readiness').textContent,/count cohort is reproducible/);
assert.match(text($('comparison-missing')),/Confirm loading access/);
assert.match(text($('comparison-alternatives')),/Environmental result: 100 kg CO₂/);
assert.match(text($('comparison-alternatives')),/Feasibility & disruption/);
assert.match(text($('traffic-design-decisions')),/mapped operational frontage/);
assert.doesNotMatch($('comparison-revision-summary').textContent,/Saved result/);
$('traffic-design-history').children[0].events.click();
assert.match($('comparison-revision').textContent,/Revision 7 · inputs 1 · hash7/);
assert.equal($('proposal-review').hidden,true,'an earlier no-winner evaluation cannot retain the current winner overlay');
assert.equal($('comparison-stale').hidden,true,'intentional history inspection is read-only, not a request to rerun');
assert.match($('comparison-revision-summary').textContent,/Earlier evaluation · read-only inspection/);
assert.match($('comparison-revision-summary').textContent,/Saved result · published 2026-11-14 15:00:00 UTC/);
assert.match($('comparison-period').textContent,/2011-11-08/,'the observation date remains distinct from publication time');
$('comparison-alternatives').children[1].children.find(c=>c.textContent==='Show footprint on map').events.click();
assert.match($('proposal-map-caption').textContent,/Earlier evaluation 7 · Tested, rejected/);
assert.match($('proposal-revision').textContent,/Saved result · published 2026-11-14 15:00:00 UTC/);
assert.equal($('proposal-stale').hidden,true);
$('traffic-return-current').events.click();
assert.match($('comparison-revision').textContent,/Revision 8 · inputs 2 · hash8/);
assert.equal($('proposal-kind').textContent,'Recommended');
assert.doesNotMatch($('comparison-revision-summary').textContent,/Saved result/);
map.fire('plannerinputs',{inputRevision:3});
select('a','street',3);map.fire('plannerrestore',{...latestTraffic,savedAt:'2026-11-14T15:10:00Z'});
assert.match($('comparison-revision').textContent,/Revision 8/);
assert.equal($('comparison-stale').hidden,false);
assert.match($('proposal-map-caption').textContent,/saved previous result/);
assert.match($('comparison-revision-summary').textContent,/Saved result · published 2026-11-14 15:10:00 UTC/);
select('a','street',2);map.fire('plannerresult',{...latestTraffic,savedAt:'2026-11-14T15:10:00Z',restored:true});
assert.match($('proposal-revision').textContent,/Saved result · published 2026-11-14 15:10:00 UTC/,'an unchanged saved result also displays the original publication time');
map.fire('plannerinputs',{inputRevision:3});map.fire('plannerresult',result(9,3));
assert.doesNotMatch($('proposal-revision').textContent,/Saved result/);
assert.doesNotMatch($('comparison-revision-summary').textContent,/Saved result/);
select('a','street',4);const firstUnavailable=result(9,4,null);
firstUnavailable.comparison.status='unavailable';firstUnavailable.comparison.results={};firstUnavailable.comparison.ranking.reason='Verified turning demand is missing.';
firstUnavailable.trafficPlan={readiness:{label:'Turning demand is required.',missing:['A source-verified count sheet.']}};
map.fire('plannerresult',firstUnavailable);
assert.equal($('traffic-comparison').hidden,false);
assert.equal($('comparison-title').textContent,'Traffic evaluation needs evidence');
assert.equal($('comparison-table').hidden,true);
assert.match($('comparison-readiness').textContent,/Turning demand is required/);
assert.equal($('proposal-review').hidden,true);
console.log('PASS: traffic environmental/readiness separation, whole-evaluation history, stale restoration and actionable unavailable state');

// A live continuation can replace facts before publishing any geometry. Detach
// the retained design's links immediately, including retries with unchanged inputs.
{
  const inspections=[];map.on('plannerinspectevidence',event=>inspections.push(event));
  select('water','water',1);map.fire('plannerresult',study);
  const waterButton=$('water-design-decisions').children[0].children.find(c=>c.textContent==='Inspect source evidence');
  waterButton.events.click();assert.equal(inspections.length,1);
  map.fire('plannerinvestigation',{siteId:'another-site',workflow:'water',inputRevision:1,revision:3});
  map.fire('plannerinvestigation',{siteId:'water',workflow:'street',inputRevision:1,revision:3});
  map.fire('plannerinvestigation',{siteId:'water',workflow:'water',inputRevision:0,revision:3});
  map.fire('plannerinvestigation',{siteId:'water',workflow:'water',inputRevision:1,revision:2});
  assert.equal(waterButton.hidden,false,'unrelated or old investigation events cannot invalidate this result');
  const previousLayer=activeLayer();
  map.fire('plannerinvestigation',{siteId:'water',workflow:'water',inputRevision:1,revision:3});
  assert.equal(activeLayer(),previousLayer,'starting a revision preserves the displayed geometry');
  assert.equal(waterButton.hidden,true);assert.equal(waterButton.disabled,true);
  waterButton.events.click();assert.equal(inspections.length,1,'a retained handler cannot inspect the next run’s ledger');
  assert.equal($('proposal-stale').hidden,false);assert.equal($('water-design-stale').hidden,false);
  $('water-design-alternatives').children[1].children.find(c=>c.textContent==='Inspect this footprint').events.click();
  assert.equal($('proposal-area').textContent,'20.0 m²');assert.equal($('proposal-stale').hidden,false);
  assert.match($('proposal-map-caption').textContent,/stale inputs/);
  $('water-return-current').events.click();
  assert.equal($('proposal-area').textContent,'30.0 m²');
  assert.equal($('proposal-stale').hidden,false);assert.equal($('water-design-stale').hidden,false);
  assert.doesNotMatch(text($('water-design-decisions')),/Inspect source evidence/);
  const freshWater={...study,revision:3,proposal:waterProposal(3,1,35),alternatives:{},waterPlan:{decisions:study.waterPlan.decisions}};
  map.fire('plannerresult',freshWater);
  assert.equal($('proposal-area').textContent,'35.0 m²','starting a run does not consume its publication revision');
  assert.equal($('proposal-stale').hidden,true);assert.equal($('water-design-stale').hidden,true);
  $('water-design-decisions').children[0].children.find(c=>c.textContent==='Inspect source evidence').events.click();
  assert.equal(inspections.length,2,'newly validated results regain their own evidence inspection');

  select('a','street',2);map.fire('plannerresult',latestTraffic);
  const trafficButton=$('traffic-design-decisions').children[0].children.find(c=>c.textContent==='Inspect source evidence');
  map.fire('plannerinvestigation',{siteId:'a',workflow:'street',inputRevision:2,revision:9});
  assert.equal(trafficButton.hidden,true);assert.equal(trafficButton.disabled,true);
  trafficButton.events.click();assert.equal(inspections.length,2);
  assert.equal($('comparison-stale').hidden,false);
  $('comparison-alternatives').children[1].children.find(c=>c.textContent==='Show footprint on map').events.click();
  assert.equal($('proposal-stale').hidden,false,'same-input historical alternatives remain stale');
  $('traffic-return-current').events.click();
  assert.equal($('proposal-stale').hidden,false);assert.equal($('comparison-stale').hidden,false);
  const unavailable=result(9,2,null);unavailable.comparison.status='unavailable';unavailable.comparison.results={};
  map.fire('plannerresult',unavailable);
  assert.match($('comparison-revision').textContent,/Revision 8/);
  assert.doesNotMatch(text($('traffic-design-decisions')),/Inspect source evidence/,'an unavailable continuation keeps historical links detached');
  map.fire('plannerresult',{...result(10,2),trafficPlan:latestTraffic.trafficPlan});
  assert.equal($('proposal-stale').hidden,true);assert.equal($('comparison-stale').hidden,true);
  $('traffic-design-decisions').children[0].children.find(c=>c.textContent==='Inspect source evidence').events.click();
  assert.equal(inspections.length,3);
}
console.log('PASS: live same-input retries detach historical evidence links and preserve stale geometry through previews until valid publication');
