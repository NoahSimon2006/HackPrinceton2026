import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile(new URL('../public/road-concept.js',import.meta.url),'utf8');
const html=await readFile(new URL('../public/index.html',import.meta.url),'utf8');
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
function harness() {
  const elements=new Map(),layers=[],events=[],fits=[];
  const element=()=>({children:[],events:{},style:{},attributes:{},hidden:false,checked:false,disabled:false,value:'85',textContent:'',
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    addEventListener(name,fn){(this.events[name]??=[]).push(fn);},setAttribute(name,value){this.attributes[name]=String(value);},getAttribute(name){return this.attributes[name];}});
  const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const map={handlers:{},createPane(){},getPane(){return{style:{}};},on(name,fn){(this.handlers[name]??=[]).push(fn);},
    fire(name,event){events.push({name,event});for(const fn of this.handlers[name]??[])fn(event);},
    setView(){assert.fail('concept publication must preserve the existing map camera');},fitBounds(bounds,options){fits.push({bounds,options});}};
  const L={geoJSON(data,options){
    const layer={data,options,attached:false,features:[],addTo(){this.attached=true;return this;},remove(){this.attached=false;},
      setStyle(fn){this.styles=this.data.features.map(fn);},getBounds(){return{isValid:()=>true};}};
    for(const feature of data.features){const item={popup:null,bindPopup(node){this.popup=node;}};options.onEachFeature(feature,item);layer.features.push(item);}
    layer.setStyle(options.style);layers.push(layer);return layer;
  }};
  vm.runInNewContext(source,{$,map,L,document:{createElement:element},console});
  return{$,map,layers,events,fits,active:()=>layers.findLast(layer=>layer.attached),
    click(id,type='click'){for(const fn of $(id).events[type]??[])fn();},
    select(siteId='site',inputRevision=0,workflow='street'){map.fire('plannersite',{siteId,inputRevision,workflow});}};
}
const concept=(revision=1,input_revision=0)=>({schema_version:1,site_id:'site',workflow:'street',revision,input_revision,
  input_hash:String(revision).repeat(64),context_hash:'a'.repeat(64),status:'conceptual',
  components:[{id:'bike',kind:'bike_lane',length_m:30,width_m:2,anchor_id:'road-1',side:'right'},
    {id:'cross',kind:'crossing',length_m:8,width_m:3,anchor_id:'road-1',side:'center'}],
  geometry:[{type:'Feature',id:'bike-footprint',properties:{component_id:'bike',kind:'bike_lane',role:'proposed',revision,label:'Protected bike lane'},
    geometry:{type:'Polygon',coordinates:[[[-118.25,34.05],[-118.2499,34.05],[-118.2499,34.0501],[-118.25,34.05]]]}},
    {type:'Feature',id:'cross-stripe-1',properties:{component_id:'cross',kind:'crossing',role:'marking',revision,label:'Crossing stripe'},
    geometry:{type:'Polygon',coordinates:[[[-118.25,34.05],[-118.2499,34.05],[-118.2499,34.0501],[-118.25,34.05]]]}}],
  sources:[{label:'Mapped road centerline',url:'https://example.org/source'}],assumptions:['Lane width is a design assumption.'],checks:{access:'Keep-clear markings preserved'},
  evaluation:{status:'unassessed',reason:'Verified turning counts are unavailable.'}});
const event=(c=concept(),extra={})=>({projectId:'f'.repeat(32),siteId:'site',workflow:'street',revision:c.revision,inputRevision:c.input_revision,
  concept:c,conceptHistory:[],follow:true,...extra});
const intersection=(revision=2,input_revision=0)=>{
  const c=concept(revision,input_revision);
  c.components=[{id:'junction',kind:'intersection_redesign',label:'Coordinated intersection',approach_length_m:35,curb_extension_m:1.2,crossing_setback_m:4,crossing_width_m:3}];
  c.geometry=['roadway','sidewalk','curb','planting','centerline','crosswalk','stop_line','lane_arrow'].map((surface,index)=>({
    type:'Feature',id:`junction-${surface}`,geometry:c.geometry[0].geometry,
    properties:{component_id:'junction',kind:'intersection_redesign',surface,role:index<4?'proposed':'marking',revision,label:surface},
  }));
  c.checks=[{component_id:'junction',area_m2:500,roadway_area_m2:350,sidewalk_area_m2:150,approach_count:4,crossing_count:4,connected:true,road_fit:'checked',keep_clear:'no_markings',building_overlap:'unassessed'}];
  return c;
};

// Complete designs cover only their exact supplied plan geometry. Materials
// replace the aerial inside that plan, with crisp markings and no invented fill.
{
  const h=harness();h.select();const c=intersection();h.map.fire('roadconceptresult',event(c));
  const plan=h.active();assert.ok(plan);assert.deepEqual(plan.data.features,c.geometry,'backend order, holes and coordinates remain authoritative');
  assert.equal(h.$('road-concept-opacity').value,'100');assert.equal(h.$('road-concept-opacity-value').textContent,'100%');
  assert.ok(plan.styles.every(style=>style.fillOpacity===1));
  assert.equal(plan.styles[0].fillColor,'#3b4145');assert.equal(plan.styles[1].fillColor,'#dcd4c1');
  assert.equal(plan.styles[2].fillColor,'#f0e9d8');assert.equal(plan.styles[3].fillColor,'#7c956a');
  assert.equal(plan.styles[4].fillColor,'#e9c85b');assert.equal(plan.styles[5].fillColor,'#faf7ed');
  assert.ok(plan.styles.slice(4).every(style=>style.stroke===false),'marking strokes must not inflate the compiled lane widths');
  assert.equal(h.$('road-concept-title').textContent,'Intersection redesign');
  assert.equal(h.$('road-concept-scope').textContent,'COORDINATED CONCEPT');
  assert.match(text(h.$('road-concept-legend')),/Roadway.*Sidewalk.*Concrete curb.*Planting.*Centerlines.*Crossings/);
  assert.match(text(plan.features[0].popup),/Maximum approach length 35 m.*Maximum curb extension 1.2 m.*Crossing setback 4 m.*Crossing width 3 m/);
  assert.match(text(h.$('road-concept-basis')),/4 approaches.*4 crossings.*Road layout connected.*Roadway 350 m².*Sidewalk 150 m²/);
  h.click('road-concept-existing');assert.equal(h.active(),undefined);h.click('road-concept-proposed');assert.equal(h.active(),plan);
  assert.equal(h.fits.length,0,'comparison never changes the underlying map camera');
  h.$('road-concept-opacity').value='60';h.click('road-concept-opacity','input');assert.ok(plan.styles.every(style=>style.fillOpacity===.6));
  const bad=intersection(3);bad.geometry[0].properties.surface='arbitrary-overlay';h.map.fire('roadconceptresult',event(bad));
  assert.equal(h.active(),plan);assert.equal(h.$('road-concept-state').textContent,'Concept unavailable');
}
{
  const h=harness();h.select();const c=intersection(),old=concept();
  h.map.fire('roadconceptresult',event(c,{conceptHistory:[{concept:old}]}));
  h.$('road-concept-history').children[0].events.click[0]();
  assert.equal(h.$('road-concept-opacity').value,'85','legacy geometry retains its earlier display default');
  assert.match(h.$('road-concept-title').textContent,/Earlier component concept/);
  assert.equal(h.$('road-concept-scope').textContent,'COMPONENT CONCEPT');
  h.click('road-concept-return');assert.equal(h.$('road-concept-opacity').value,'100');
  assert.deepEqual(h.active().data.features,c.geometry);
}
for(const distance of [29.535,10]) {
  const h=harness();h.select();const c=intersection();c.components[0].junction_id='junction-selected';
  c.context={junctions:[{id:'junction-other',distance_m:300,approach_count:3},{id:'junction-selected',distance_m:distance,approach_count:4}]};
  h.map.fire('roadconceptresult',event(c));
  const location=h.$('road-concept-location');assert.equal(location.hidden,false);assert.match(location.textContent,/Connected junction · 4 approaches/);
  if(distance>10){assert.match(location.textContent,/30 m from your selected point/);assert.match(text(h.$('road-concept-basis')),/30 m from your selected point/);}
  else assert.doesNotMatch(location.textContent,/from your selected point/);
  assert.doesNotMatch(location.textContent,/300|3 approaches/,'the displayed offset belongs to the chosen junction, not another nearby node');
}

// A concept renders exact supplied geographic features even when no traffic
// evaluation exists. It never replaces the map or fetches another service.
{
  const h=harness();h.select();const c=concept();h.map.fire('roadconceptresult',event(c));
  const first=h.active();assert.ok(first);assert.deepEqual(first.data.features,c.geometry);
  assert.equal(first.data.features.length,2,'no invented street or crossing geometry is added');
  assert.equal(h.$('road-concept-state').textContent,'Concept ready');
  assert.match(h.$('road-concept-performance').textContent,/turning counts/);
  assert.match(text(first.features[0].popup),/30 m long × 2 m wide/);
  assert.match(text(first.features[0].popup),/design assumption/);
  assert.equal(first.features[0].popup.children.at(-1).children[0].children[0].href,'https://example.org/source');
  assert.match(text(h.$('road-concept-legend')),/Bike lane.*Crossing/);
  h.click('road-concept-existing');assert.equal(h.active(),undefined);
  h.click('road-concept-proposed');assert.equal(h.active(),first);assert.equal(h.layers.length,1);
  assert.equal(h.fits.length,0,'publication and comparison preserve the map camera');
  h.click('road-concept-focus');assert.equal(h.fits.length,1);assert.equal(h.fits[0].options.maxZoom,19,'the explicit focus action fits the design with room for controls');
  assert.ok(h.events.some(item=>item.name==='roadconceptfocus'),'focusing a concept asks discovery controls to collapse');
  h.$('road-concept-opacity').value='40';h.click('road-concept-opacity','input');
  assert.equal(first.styles[0].opacity,.4);assert.equal(first.styles[1].fillOpacity,.4*.96);
  h.$('show-road-concept').checked=false;h.click('show-road-concept','change');assert.equal(h.active(),undefined);
  h.$('show-road-concept').checked=true;h.click('show-road-concept','change');assert.equal(h.active(),first);
  h.map.fire('proposaldisplay',{proposal:{}});assert.equal(h.active(),undefined,'inspecting an evaluated layout hides the concept');
  h.click('road-concept-proposed');assert.equal(h.active(),first);
  h.$('show-proposal').checked=true;h.click('show-proposal','change');assert.equal(h.active(),undefined);
  h.click('road-concept-proposed');h.click('focus-proposal');assert.equal(h.active(),undefined,'focusing the evaluated footprint cannot leave both layouts visible');
}

// Invalid, old-input, canceled and foreign results preserve the last good map.
{
  const h=harness();h.select();h.map.fire('roadconceptresult',event());const first=h.active();
  h.map.fire('plannerinputs',{inputRevision:1});assert.equal(h.active(),first);assert.match(h.$('road-concept-warning').textContent,/Inputs changed/);
  h.map.fire('roadconceptresult',event(concept(2,0)));assert.equal(h.active(),first);
  const invalid=concept(2,1);invalid.geometry[0].properties.revision=99;
  h.map.fire('roadconceptresult',event(invalid));assert.equal(h.active(),first);assert.equal(h.$('road-concept-state').textContent,'Concept unavailable');
  const wrong=concept(2,1);wrong.site_id='other';h.map.fire('roadconceptresult',event(wrong));assert.equal(h.active(),first);
  h.map.fire('plannerinvestigation',{siteId:'site',workflow:'street',inputRevision:1,revision:2});
  h.map.fire('planneranalysisend',{siteId:'site',workflow:'street',revision:2,status:'canceled'});
  h.map.fire('roadconceptresult',event(concept(2,1)));assert.equal(h.active(),first,'late canceled completion cannot publish');
  const fresh=concept(3,1);h.map.fire('roadconceptresult',event(fresh));assert.notEqual(h.active(),first);
  const current=h.active();h.map.fire('roadconceptresult',event(concept(2,1)));assert.equal(h.active(),current);
  h.map.fire('roadconceptresult',event(concept(4,1),{concept:null,conceptGap:'No sourced placement fits the selected road.'}));
  assert.equal(h.active(),current);assert.equal(h.$('road-concept-state').textContent,'Placement needed');
  assert.match(h.$('road-concept-warning').textContent,/Previous concept remains/);
  h.select('another-site');assert.equal(h.active(),undefined);assert.equal(h.$('road-concept-review').hidden,true);
  h.map.fire('roadconceptresult',event(concept(5,1)));assert.equal(h.active(),undefined);
  h.select('site',1,'water');h.map.fire('roadconceptresult',event(concept(5,1)));assert.equal(h.active(),undefined);
}

// Historical inspections use their own saved geometry and source basis and can
// return to the latest concept without mutating either revision.
{
  const h=harness();h.select('site',2);
  const earlier=concept(1,0),latest=concept(3,2);earlier.assumptions=['Earlier placement assumption.'];
  h.map.fire('roadconceptresult',event(latest,{restored:true,conceptHistory:[{concept:earlier,savedAt:'2026-11-15T08:00:00Z'}]}));
  assert.equal(h.$('road-concept-history').children.length,1);
  h.$('road-concept-history').children[0].events.click[0]();
  assert.deepEqual(h.active().data.features,earlier.geometry);assert.match(text(h.$('road-concept-basis')),/Earlier placement/);
  assert.match(h.$('road-concept-warning').textContent,/read-only/);assert.equal(h.$('road-concept-return').hidden,false);
  h.click('road-concept-return');assert.deepEqual(h.active().data.features,latest.geometry);
  assert.equal(h.$('road-concept-return').hidden,true);
  h.select('site',4);
  h.map.fire('roadconceptresult',event(latest,{revision:5,inputRevision:4,restored:true,stale:true,historicalReference:true}));
  assert.deepEqual(h.active().data.features,latest.geometry);assert.match(h.$('road-concept-warning').textContent,/Saved reference/);
}
{
  const h=harness();h.select();h.map.fire('roadconceptresult',event(concept(),{concept:null,conceptGap:'Choose a road with a mapped centerline.'}));
  assert.equal(h.active(),undefined);assert.equal(h.$('road-concept-state').textContent,'Placement needed');assert.equal(h.$('road-concept-existing').disabled,true);
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  for(const match of source.matchAll(/\$\('([a-z-]+)'\)/g))assert.equal(ids.filter(id=>id===match[1]).length,1,`controller needs one #${match[1]}`);
  assert.match(html,/<script defer src="\/road-concept.js/);
}
console.log('PASS: sourced map concepts, exact geometry, independent performance, comparison controls, revision history, cancellation and site isolation');
// Optional compiler-to-controller check: pass a canonical JSON result generated
// by road_concept.build_road_concept, without requiring Python for JS unit tests.
if(process.argv[2]) {
  const c=JSON.parse(await readFile(process.argv[2],'utf8')),h=harness();h.select(c.site_id,c.input_revision);
  h.map.fire('roadconceptresult',event(c,{siteId:c.site_id}));
  assert.deepEqual(h.active()?.data.features,c.geometry,'actual compiler output renders unchanged');
  assert.equal(h.$('road-concept-state').textContent,'Concept ready');
  console.log('PASS: actual Python compiler JSON is accepted unchanged by the map controller');
}
