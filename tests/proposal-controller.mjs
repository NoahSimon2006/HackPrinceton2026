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
assert.equal($('proposal-review').hidden,true);
assert.equal($('proposal-result-message').textContent,'Which driveway should stay clear?');
console.log('PASS: draft screening metrics, unknown capture and specific placement question');
