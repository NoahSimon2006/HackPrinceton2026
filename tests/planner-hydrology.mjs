// Run with: node tests/planner-hydrology.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../public/planner.js', import.meta.url), 'utf8');
const transportSource = await readFile(new URL('../public/analysis-stream.js', import.meta.url), 'utf8');
function harness(mode = 'water', options = {}) {
  const elements = new Map();
  const element = tagName => ({ tagName, hidden: false, open: false, checked: false, disabled: false, value: '', textContent: '',
    events: {}, children: [], attributes: {}, style: { setProperty() {} }, classList: { toggle() {} },
    setAttribute(name, value) {this.attributes[name]=value;}, replaceChildren(...children) {this.children=children;}, append(...children) {this.children.push(...children);}, scrollIntoView() {}, focus() {},
    click() { this.events.click?.(); },
    addEventListener(name, handler) { this.events[name] = handler; } });
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  $('show-watershed').checked = true;
  const layers = [];
  const layer = (value) => {
    const result = { data: [], attached: false, addTo() { this.attached = true; return this; },
      remove() { this.attached = false; }, clearLayers() { this.data = []; },
      addData(data) { this.data.push(data); }, bindTooltip() { return this; }, events:{},
      on(name,handler){this.events[name]=handler;}, getLatLng(){return this.latlng;},latlng:value,
      eachLayer(){},setLatLngs(){} };
    layers.push(result);
    return result;
  };
  const map = { handlers: {}, events: [], center:{lat:34.05,lng:-118.25},createPane() {}, getPane: () => ({ style: {} }),
    on(name, handler) { this.handlers[name] = handler; },
    fire(name, event) { this.events.push({name,event}); this.handlers[name]?.(event); }, setView(point) {this.center=Array.isArray(point)?{lat:point[0],lng:point[1]}:point;},getCenter(){return this.center;}, closePopup() {}, getZoom: () => 17 };
  const requests = [], identityRequests = [], saves=[];
  const json = (url, requestOptions = {}) => {
    if (url === '/api/projects') return Promise.resolve({projects:[]});
    if (url.startsWith('/api/projects?id=')) return Promise.resolve(options.savedProject ?? {id:'a'.repeat(32),version:1,artifacts:[],status:'ready'});
    if (url.startsWith('/api/site-resolution')) {
      if (!options.captureIdentity) return Promise.resolve({status:'unmatched',property:null,candidates:[],message:'No unique property match.'});
      return new Promise((resolve,reject)=>identityRequests.push({url,options:requestOptions,resolve,reject}));
    }
    return new Promise((resolve, reject) => requests.push({ url, options:requestOptions, resolve, reject }));
  };
  vm.runInNewContext((options.streamResponses ? transportSource + '\n' : '') + source, { $, map, json, planningMode: mode, coverage: options.coverage ?? null,
    insideCoverage: options.insideCoverage ?? (()=>true),
    cancelSiteAnalysis: () => {},
    streamSiteAnalysis: (payload, options) => json("/api/site-analysis", {body:JSON.stringify(payload), ...options}),
    TextDecoder, fetch: async (url, requestOptions) => {
      requests.push({url, options:requestOptions});
      const events = options.streamResponses.shift();
      assert.ok(events, 'every analysis request has an explicit test response');
      if (events instanceof Error) throw events;
      const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event)).join('\n') + '\n');
      let position = 0;
      return {ok:true, headers:{get:()=> 'application/x-ndjson'}, body:new ReadableStream({pull(controller) {
        if (position >= bytes.length) {controller.close();return;}
        controller.enqueue(bytes.slice(position, position + 13));position += 13;
      }})};
    },
    URLSearchParams, AbortController, setTimeout:()=>1,clearTimeout(){},window:{addEventListener(){}},
    localStorage:{getItem:()=>null,setItem(){}}, SavedProject:class{constructor(value=null){this.value=value;}async save(snapshot){saves.push(snapshot);return this.value={id:'a'.repeat(32),version:1,snapshot,artifacts:[],status:'ready'};}}, document: { createElement: element },
    L: { latLng: (lat,lng) => {if(!Number.isFinite(lat)||!Number.isFinite(lng))throw Error('Invalid LatLng');return {lat,lng};}, layerGroup: layer, geoJSON: layer, circleMarker: layer,
      polyline:layer,polygon:layer,marker:layer,divIcon:()=>({}),Polyline:function(){} } });
  function select(lat, lng) {
    $('pick-site').events.click();
    map.fire('click', { latlng: { lat, lng } });
  }
  function workspace(mode, visible = true) {
    $('planner').hidden = !visible;
    map.fire('plannerworkspace', { mode, visible });
  }
  return { $, map, layers, requests, identityRequests, saves,select, workspace };
}
const watershed = (name) => ({ type: 'FeatureCollection', features: [{ type: 'Feature',
  properties: { WATERSHED: name, NAME: ' ' }, geometry: { type: 'Polygon', coordinates: [] } }] });
const rainfall = { estimate: { inches: .99, method: 'interpolated', depth_range: [.9, 1] } };
const flush = () => new Promise(setImmediate);

// Real UI events drive the controller: direct links, partial failure, retry,
// user input preservation, layer visibility and per-site caching.
{
  const h = harness();
  h.select(34.051, -118.2521);await flush();
  assert.equal(h.requests.length, 2, 'selecting a water site loads both sources without an agent');
  h.requests[1].resolve(watershed('lariver'));
  h.requests[0].reject(new Error('Service offline'));
  await flush();
  assert.equal(h.$('watershed-name').textContent, 'Los Angeles River');
  assert.equal(h.$('watershed-legend').hidden, false, 'boundary survives rainfall failure');
  assert.equal(h.$('retry-hydrology').hidden, false);
  h.$('rain-depth').events.input({ target: { value: '1.5' } });
  h.$('rain-source').events.input({ target: { value: 'User scenario' } });
  h.$('retry-hydrology').events.click();
  assert.equal(h.requests.length, 3, 'retry requests only the failed source');
  h.requests[2].resolve(rainfall);
  await flush();
  assert.equal(h.$('rain-value').textContent, '0.99');
  assert.equal(h.$('rain-depth').value, '1.5', 'automatic data never overwrites a manual scenario');
  assert.equal(h.$('rain-source').value, 'User scenario');
  assert.equal(h.$('retry-hydrology').hidden, true);
  h.$('show-watershed').checked = false;
  h.$('show-watershed').events.change();
  assert.equal(h.$('watershed-legend').hidden, true);
  assert.equal(h.layers[1].data.length, 0);
  h.$('show-watershed').checked = true;
  h.workspace('street');
  assert.equal(h.$('water-tools').hidden, true);
  assert.equal(h.layers[1].data.length, 0);
  h.workspace('emissions', false);
  assert.equal(h.$('watershed-legend').hidden, true);
  h.workspace('water');
  assert.equal(h.$('watershed-legend').hidden, false);
  assert.equal(h.requests.length, 3, 'switching workspaces reuses the selected site data');
}

// Rapid site changes cannot leak an old watershed or depth into the new site.
{
  const h = harness('street');
  h.select(34.05, -118.25);await flush();
  assert.equal(h.requests.length, 0);
  h.workspace('water');
  h.select(34.06, -118.30);await flush();
  assert.equal(h.requests.length, 4);
  h.requests[2].resolve({ estimate: null });
  h.requests[3].resolve({ type: 'FeatureCollection', features: [] });
  await flush();
  h.requests[0].resolve(rainfall);
  h.requests[1].resolve(watershed('ballona'));
  await flush();
  assert.equal(h.$('watershed-name').textContent, 'Outside mapped subbasins');
  assert.equal(h.$('rain-value').textContent, '—');
  assert.equal(h.$('watershed-legend').hidden, true);
  assert.equal(h.$('view-watershed').disabled, true);
  assert.match(h.$('rain-result').textContent, /No reliable contour estimate/);
  h.select(34.05, -118.25);await flush();
  assert.equal(h.$('watershed-name').textContent, 'Ballona');
  assert.equal(h.$('rain-depth').value, .99);
  assert.equal(h.requests.length, 4);
}
// Analysis sends the edited rainfall separately from the county estimate and
// marks an in-flight result stale when the user changes its inputs.
{
  const h = harness();
  h.select(34.05, -118.25);await flush();
  h.requests[0].resolve(rainfall);
  h.requests[1].resolve(watershed('ballona'));
  await flush();
  h.$('rain-depth').events.input({ target: { value: '1.5' } });
  h.$('rain-source').events.input({ target: { value: 'Sensitivity scenario' } });
  const pending = h.$('site-analysis').events.submit({ preventDefault() {} });
  await flush();
  const body = JSON.parse(h.requests[2].options.body);
  assert.deepEqual(body.rainfallScenario, { inches: 1.5, source: 'Sensitivity scenario' });
  assert.deepEqual(body.markings, []);
  assert.equal(body.siteId, '34.050000,-118.250000');
  assert.equal(body.inputRevision, 2);
  assert.equal(body.proposalRevision, 1);
  h.$('rain-depth').events.input({ target: { value: '2' } });
  h.requests[2].resolve({ report: { findings: [], recommendations: [], questions: ['Confirm drainage?'] },
    evidence: { outlines: [], detections: [], frontages: [], search: [], unavailable: [] }, facts: [], sourceStatus: {},
    proposal:{revision:1}, comparison:{revision:1} });
  await pending;
  assert.equal(h.$('analysis-stale').hidden, false);
  assert.equal(h.$('run-site-analysis').disabled, false);
  assert.equal(h.map.events.filter(e=>e.name==='plannerresult').length, 0, 'changed inputs must not publish a stale proposal');
}
console.log('PASS: hydrology, source failures/retry, manual inputs, workspace visibility, site races, caching, scenario submission and stale analysis');
// Cancel/supersede a run: late activity and results cannot repaint another site.
{
  const h=harness('street');
  h.select(34.05,-118.25);await flush();
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  const first=h.requests[0];
  first.options.onEvent({specialist:'site-evidence',status:'started',summary:'Reading source.',fact_ids:[]});
  assert.equal(h.$('activity-count').textContent,'· 1');
  h.select(34.06,-118.26);await flush();
  assert.equal(first.options.signal.aborted,true);
  first.options.onEvent({specialist:'lead',status:'completed',summary:'OLD RESULT',fact_ids:[]});
  first.resolve({report:{findings:[],recommendations:[],questions:['OLD RESULT']},facts:[]});
  await pending;
  assert.notEqual(h.$('analysis-message').textContent,'OLD RESULT');
  assert.equal(h.$('activity-count').textContent,'');
  const second=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  h.$('cancel-site-analysis').events.click();
  assert.equal(h.requests[1].options.signal.aborted,true);
  h.requests[1].resolve({report:null,facts:[]});await second;
  assert.match(h.$('analysis-message').textContent,/canceled/);
  assert.equal(h.$('run-site-analysis').disabled,false);
}
console.log('PASS: canceled and superseded activity cannot repaint another site');

// Source selections seed the brief without an agent, then submit only a checked
// local reference; changing features at the same coordinate cancels stale work.
{
  const h=harness('street');
  const selection={workflow:'street',reference:{version:'v1',layer:'flow',feature:'flow-one'},
    source:{label:'LADOT',url:'https://example.org/source',retrieved_at:'2026-11-14'},
    layer:{unit:'vehicles reported',period:'Historical',method:'No scaling',limitations:'No current demand'},
    feature:{properties:{label:'Source intersection',center:[-118.25,34.05],value:18102,period:'2014-01-16'}}};
  h.map.fire('discoveryselect',selection);await flush();
  assert.equal(h.requests.length,0);
  assert.equal(h.$('discovery-context').hidden,false);
  assert.match(h.$('discovery-feature-value').textContent,/18,102/);
  assert.equal(h.$('discovery-feature-period').textContent,'2014-01-16');
  assert.match(h.$('planning-brief').value,/current surface-street slowdown/);
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  const body=JSON.parse(h.requests[0].options.body);
  assert.deepEqual(body.discoveryReference,selection.reference);
  assert.equal(body.source_record,undefined);
  h.map.fire('discoveryselect',{...selection,reference:{...selection.reference,feature:'count-two'}});
  assert.equal(h.requests[0].options.signal.aborted,true);
  h.requests[0].resolve({report:null,facts:[]});await pending;
}
console.log('PASS: discovery seeds a current-traffic site brief and submits a reference without an automatic agent call');

// Current-traffic selections seed an investigation; result identity follows the
// exact selected site and input revision, including repeated analyses.
{
  const h=harness('street');
  const selection={workflow:'street',reference:{version:'v1',layer:'approaches',feature:'approach-one'},
    source:{label:'LADOT',url:'https://example.org/source',retrieved_at:'2026-11-14'},
    layer:{unit:'vehicles reported',period:'Historical',method:'Verified count',limitations:'Not current demand'},
    feature:{properties:{label:'Counted intersection',center:[-118.25,34.05],value:4000,period:'2011-11-08'}}};
  h.map.fire('discoveryselect',selection);await flush();
  assert.match(h.$('planning-brief').value,/nearby source evidence/);
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  const body=JSON.parse(h.requests[0].options.body);
  assert.equal(body.siteId,'34.050000,-118.250000');
  assert.equal(body.inputRevision,1);assert.equal(body.proposalRevision,1);
  assert.deepEqual(JSON.parse(JSON.stringify(h.map.events.find(e=>e.name==='plannerinvestigation')?.event)),
    {siteId:body.siteId,workflow:'street',inputRevision:1,revision:1},'invalidate retained source links before a new run can emit facts');
  h.requests[0].resolve({report:null,facts:[],proposal:{revision:1},comparison:{revision:1}});await pending;
  const published=h.map.events.filter(e=>e.name==='plannerresult');
  assert.equal(published.length,1);assert.equal(published[0].event.siteId,body.siteId);
  assert.equal(published[0].event.workflow,'street');assert.equal(published[0].event.inputRevision,1);
  assert.equal(published[0].event.revision,1);
  const repeated=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  assert.equal(JSON.parse(h.requests[1].options.body).proposalRevision,2);
  assert.equal(h.map.events.filter(e=>e.name==='plannerinvestigation').at(-1).event.revision,2);
  assert.equal(h.map.events.filter(e=>e.name==='plannerinvestigation').at(-1).event.inputRevision,1,'same-input retries still invalidate older evidence links');
  h.select(34.06,-118.26);await flush();h.requests[1].resolve({report:null,facts:[],proposal:{revision:2},comparison:{revision:2}});await repeated;
  assert.equal(h.map.events.filter(e=>e.name==='plannerresult').length,1,'superseded site analysis must not emit a proposal');
}
console.log('PASS: traffic investigation brief, proposal identity, monotonic revisions and suppressed stale/superseded publication');

// Re-selecting the active workspace is a no-op: it must not erase a published
// proposal through a redundant plannersite event or cancel the active request.
{
  const h=harness('street');h.select(34.05,-118.25);await flush();
  const before=h.map.events.filter(e=>e.name==='plannersite').length;
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  h.workspace('street');
  assert.equal(h.map.events.filter(e=>e.name==='plannersite').length,before);
  assert.equal(h.requests[0].options.signal.aborted,false);
  h.requests[0].resolve({report:null,facts:[]});await pending;
  h.workspace('water');
  assert.equal(h.map.events.filter(e=>e.name==='plannersite').length,before+1,'a real mode change still clears unrelated geometry');
}

// Keyboard equivalents select a site, author and revise a keep-clear marking,
// and send the edited geometry only to the existing local analysis endpoint.
{
  const h=harness('street',{coverage:{},insideCoverage:p=>p.lng<=-118.249});
  h.$('use-map-center').events.click();await flush();
  assert.equal(h.map.events.filter(e=>e.name==='plannersite').at(-1).name,'plannersite');
  assert.equal(h.map.events.filter(e=>e.name==='plannersite').at(-1).event.siteId,'34.050000,-118.250000');
  h.$('mark-actions').children[1].events.click();
  assert.equal(h.$('keyboard-marking-editor').hidden,false);
  h.$('draw-add-center').events.click();
  const field=(index,axis)=>h.$('draw-coordinates').children[index].children[axis==='lat'?1:2].children[0];
  assert.equal(field(0,'lat').attributes['aria-label'],'Point 1 latitude');
  for(const invalid of ['', 'not-a-number','Infinity','32','34.30']) {
    const input=field(0,'lat');input.value=invalid;input.events.input();
    assert.equal(h.$('draw-save').disabled,true,'invalid coordinate blocks save');
    assert.equal(h.$('draw-add-center').disabled,true);
    assert.equal(h.$('draw-coordinate-error').hidden,false);
  }
  field(0,'lat').value='34.05';field(0,'lat').events.input();
  field(0,'lng').value='-118.248';field(0,'lng').events.input();
  assert.match(h.$('draw-coordinate-error').textContent,/coverage/);
  field(0,'lng').value='-118.25';field(0,'lng').events.input();
  assert.equal(h.$('draw-coordinate-error').hidden,true);
  h.map.center={lat:34.0501,lng:-118.25};h.$('draw-add-center').events.click();
  h.map.center={lat:34.0501,lng:-118.2499};h.$('draw-add-center').events.click();
  assert.equal(h.$('draw-save').disabled,false);
  h.$('draw-save').events.click();
  assert.equal(h.$('keyboard-marking-editor').hidden,true);
  assert.equal(h.map.events.filter(e=>e.name==='plannerinputs').at(-1).event.inputRevision,1);
  const first=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  const firstBody=JSON.parse(h.requests[0].options.body);
  assert.equal(firstBody.markings[0].kind,'access');
  assert.deepEqual(firstBody.markings[0].geometry.coordinates[0],[
    [-118.25,34.05],[-118.25,34.0501],[-118.2499,34.0501],[-118.25,34.05]]);
  h.requests[0].resolve({report:null,facts:[]});await first;
  h.$('shape-list').children[0].children[1].events.click();
  field(0,'lat').value='34.04995';field(0,'lat').events.input();h.$('draw-save').events.click();
  assert.equal(h.map.events.filter(e=>e.name==='plannerinputs').at(-1).event.inputRevision,2);
  const second=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  const secondBody=JSON.parse(h.requests[1].options.body);
  assert.equal(secondBody.inputRevision,2);assert.equal(secondBody.proposalRevision,2);
  assert.deepEqual(secondBody.markings[0].geometry.coordinates[0][0],[-118.25,34.04995]);
  h.requests[1].resolve({report:null,facts:[]});await second;
  const before=h.map.events.filter(e=>e.name==='plannersite').length;
  h.map.center={lat:Infinity,lng:-118.25};h.$('use-map-center').events.click();await flush();
  h.map.center={lat:34.05,lng:-118.248};h.$('use-map-center').events.click();await flush();
  assert.equal(h.map.events.filter(e=>e.name==='plannersite').length,before,'invalid/uncovered centers cannot select a site');
}
console.log('PASS: active-workspace persistence and keyboard site/constraint revisions with coordinate validation');

// A spherical distance just under 1 km may already be outside the server's
// projected buffer. The UI keeps a margin rather than saving a doomed request.
{
  const h=harness('street');h.select(34.05,-118.25);await flush();
  h.$('mark-actions').children[1].events.click();h.$('draw-add-center').events.click();
  const longitude=h.$('draw-coordinates').children[0].children[2].children[0];
  longitude.value='-118.23917';longitude.events.input();
  assert.match(h.$('draw-coordinate-error').textContent,/990 m/);
  assert.equal(h.$('draw-save').disabled,true);
  longitude.value='-118.2394';longitude.events.input();
  assert.equal(h.$('draw-coordinate-error').hidden,true);
}

// A site draft requires no drawings or manual comparison inputs.
{
  const h=harness();h.select(34.051,-118.2521);await flush();
  h.requests[0].resolve(rainfall);h.requests[1].resolve(watershed('Ballona'));await flush();h.requests.length=0;
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  const body=JSON.parse(h.requests[0].options.body);
  assert.equal(Object.hasOwn(body,'waterDesign'),false);
  assert.deepEqual(body.markings,[]);
  h.requests[0].resolve({report:null,facts:[]});await pending;
  const html=await readFile(new URL('../public/index.html',import.meta.url),'utf8');
  assert.doesNotMatch(html,/Compare your own placements|update-water-comparison/);
  assert.match(html,/manual-markings/,'optional constraints remain available');
}

// A late parcel match cannot assign a previous property to a new map point.
{
  const h=harness('street',{captureIdentity:true});
  h.select(34.05,-118.25);
  assert.equal(h.$('run-site-analysis').disabled,true);
  h.select(34.06,-118.30);
  const property={id:'one',lat:34.05,lon:-118.25,name:'First site',address:'First address',type:'Multifamily'};
  h.identityRequests[0].resolve({status:'matched',property,candidates:[],message:'Matched'});await flush();
  assert.equal(h.$('site-name').textContent,'Map location');
  h.identityRequests[1].resolve({status:'ambiguous',property:null,candidates:[property],message:'Choose a property'});await flush();
  assert.equal(h.$('run-site-analysis').disabled,false);
  assert.match(h.$('site-resolution-status').textContent,/Choose/);
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  assert.equal(JSON.parse(h.requests.at(-1).options.body).propertyId,undefined);
  h.requests.at(-1).resolve({report:null,facts:[]});await pending;
}

// A unique match preserves the clicked coordinates and reports identity separately.
{
  const h=harness('street',{captureIdentity:true});h.select(34.05,-118.25);
  const property={id:'matched',lat:34.0501,lon:-118.2501,name:'Matched site',address:'Source address',type:'Multifamily'};
  h.identityRequests[0].resolve({status:'matched',property,candidates:[],message:'Same mapped parcel'});await flush();
  assert.equal(h.$('site-location').textContent,'Source address','a matched property is identified by its address');
  assert.equal(h.$('site-resolution-status').textContent,'','the named card confirms a match without a routine success line');
  assert.equal(h.map.events.at(-1).name,'planneridentity');
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  await flush();
  const body=JSON.parse(h.requests.at(-1).options.body);
  assert.equal(body.propertyId,'matched');assert.equal(body.lat,34.05);assert.equal(body.lon,-118.25);
  h.requests.at(-1).resolve({report:null,facts:[]});await pending;
}
console.log('PASS: single stormwater analysis path, optional constraints, guarded property resolution and source/revision isolation');

// Explicit design settings are canonical inputs, survive restoration, and
// invalidate a pending calculation rather than mixing its metrics with edits.
{
  const h=harness();h.select(34.05,-118.25);await flush();
  h.requests[0].resolve(rainfall);h.requests[1].resolve(watershed('ballona'));await flush();
  h.$('water-target-area').events.input({target:{value:'42'}});
  h.$('water-storage-depth').events.input({target:{value:'.2'}});
  h.$('water-layout').events.change({target:{value:'linear'}});
  h.$('water-placement').events.change({target:{value:'away_from_previous'}});
  h.$('water-protect-access').events.change({target:{checked:true}});
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});await flush();
  const body=JSON.parse(h.requests[2].options.body);
  assert.deepEqual(body.stormwaterSettings,{targetAreaM2:42,storageDepthM:.2,layout:'linear',placement:'away_from_previous',runoffCoefficient:null,drainageAssumption:'unknown',protectAccess:true});
  assert.deepEqual(JSON.parse(JSON.stringify(h.saves.at(-1).stormwaterSettings)),body.stormwaterSettings);
  h.$('water-target-area').events.input({target:{value:'18'}});
  assert.equal(h.requests[2].options.signal.aborted,true);
  h.requests[2].resolve({proposal:{revision:1},report:null,facts:[]});await pending;
  assert.equal(h.map.events.filter(e=>e.name==='plannerresult').length,0);
  const saved={id:'a'.repeat(32),version:3,status:'ready',artifacts:[],events:[],result:null,
    snapshot:{workflow:'water',siteId:body.siteId,lon:-118.25,lat:34.05,propertyId:null,question:'Preserve access.',markings:[],rainfallScenario:{inches:1.5,source:'Named what-if'},stormwaterSettings:body.stormwaterSettings,inputRevision:5,proposalRevision:2}};
  const r=harness('water',{savedProject:saved});
  r.map.fire('scoutselect',{project:saved});await flush();await flush();
  assert.equal(r.$('water-target-area').value,42);
  assert.equal(r.$('water-storage-depth').value,.2);
  assert.equal(r.$('water-layout').value,'linear');
  assert.equal(r.$('water-protect-access').checked,true);
  assert.equal(r.$('rain-source').value,'Named what-if');
  assert.equal(r.requests.filter(q=>q.url==='/api/site-analysis').length,0,'restoration never starts a design run');
}
{
  const h=harness();h.select(34.05,-118.25);await flush();
  h.requests[0].resolve(rainfall);h.requests[1].resolve(watershed('ballona'));await flush();
  h.$('water-drainage-assumption').events.change({target:{value:'marked_connected'}});
  await h.$('site-analysis').events.submit({preventDefault(){}});
  assert.equal(h.requests.length,2);assert.match(h.$('analysis-message').textContent,/explicit runoff coefficient/);
  h.$('water-runoff-coefficient').events.input({target:{value:'.8'}});
  await h.$('site-analysis').events.submit({preventDefault(){}});
  assert.equal(h.requests.length,2);assert.match(h.$('analysis-message').textContent,/Outline a potential runoff source/);
  h.$('mark-actions').children[1].events.click();
  h.$('draw-add-center').events.click();h.map.center={lat:34.0501,lng:-118.25};h.$('draw-add-center').events.click();
  h.map.center={lat:34.0501,lng:-118.2499};h.$('draw-add-center').events.click();h.$('draw-save').events.click();
  h.$('rain-depth').events.input({target:{value:'1'}});h.$('rain-source').events.input({target:{value:'Explicit one-inch sensitivity event'}});
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});await flush();
  const body=JSON.parse(h.requests[2].options.body);
  assert.equal(body.stormwaterSettings.drainageAssumption,'marked_connected');assert.equal(body.stormwaterSettings.runoffCoefficient,.8);
  assert.equal(body.markings[0].kind,'drainage');assert.equal(body.rainfallScenario.source,'Explicit one-inch sensitivity event');
  h.requests[2].resolve({report:null,facts:[],waterPlan:{settings:body.stormwaterSettings},draftQuestion:'Choose a host parcel.',
    synthesisWarning:'Validated source research and design outputs remain available.',analysisError:null});await pending;
  assert.equal(h.map.events.filter(e=>e.name==='plannerresult').at(-1).event.waterPlan.settings.runoffCoefficient,.8);
  assert.equal(h.$('analysis-synthesis-warning').hidden,false);
  assert.match(h.$('analysis-synthesis-warning').textContent,/Validated source research/);
  assert.equal(h.$('analysis-stale').hidden,true,'incomplete narrative alone does not invalidate local design evidence');
}
console.log('PASS: stormwater settings persistence, explicit what-if guards, marked sources and stale-run cancellation');

// Exercise the actual NDJSON reader and planner together. Unavailable traffic
// is valid partial evidence, and must not interrupt unrelated source findings.
const trafficGap = {id:'area-flow-coverage',label:'Neighborhood flow coverage',value:'unavailable',display:'unavailable',
  basis:'availability',method:'Bounded neighborhood lookup',note:'Current traffic unavailable.',feature_ids:[],
  source:{provider:'TomTom Traffic',url:'https://example.org/traffic',retrieved_at:null,observed_at:null}};
const propertyFact = {id:'property-units',label:'Reported units',value:51,display:'51 units',basis:'reported',feature_ids:[],
  source:{provider:'CoStar',retrieved_at:'2026-11-15T08:10:00Z'}};
const partialFacts = [trafficGap, propertyFact];
const partialReport = {findings:[{text:'Property evidence remains available. Current traffic is unavailable.',fact_ids:['property-units','area-flow-coverage']}],recommendations:[],questions:[]};
const activity = (facts, run = 'partial-run') => ({type:'activity',run_id:run,sequence:1,specialist:'domain-analysis',stage:'discovery',
  status:'ready',summary:'Neighborhood evidence retrieved.',facts});
const terminal = (facts, run = 'partial-run') => ({type:'result',run_id:run,result:{runId:run,facts,report:partialReport,
  sourceStatus:{traffic:'unavailable',property:'ready'},sourceWarnings:['Current traffic unavailable.'],analysisError:null}});
const descendantsText = element => [element.textContent,...element.children.map(descendantsText)].join(' ');
{
  const h=harness('street',{streamResponses:[[activity(partialFacts),terminal(partialFacts)]]});
  h.select(34.04670,-118.25249);await flush();
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.equal(h.requests.filter(r=>r.url==='/api/site-analysis').length,1);
  assert.equal(h.$('analysis-message').textContent,'');
  assert.equal(h.$('analysis-stale').hidden,true,'missing live traffic alone does not make the review stale');
  assert.equal(h.$('run-site-analysis').disabled,false);
  assert.equal(h.$('cancel-site-analysis').hidden,true);
  assert.match(descendantsText(h.$('site-facts-list')),/Retrieval date unavailable/);
  assert.match(descendantsText(h.$('site-facts-list')),/Retrieved 2026-11-15/);
  assert.match(descendantsText(h.$('agent-assessment')),/Property evidence remains available/);
  assert.match(h.$('site-source-status').textContent,/traffic: unavailable/);
  assert.match(descendantsText(h.$('site-source-warnings')),/Current traffic unavailable/);
}
{
  const malformed = [
    null,
    {...trafficGap,id:'source-missing',source:null,feature_ids:null},
    {...trafficGap,id:'metadata-malformed',source:{provider:'TomTom',retrieved_at:42},feature_ids:{unexpected:true}},
    propertyFact,
  ];
  const h=harness('street',{streamResponses:[[activity(malformed),terminal(malformed)]]});
  h.select(34.04670,-118.25249);await flush();
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.equal(h.$('analysis-stale').hidden,true);
  assert.match(descendantsText(h.$('site-facts-list')),/Source unavailable/);
  assert.match(descendantsText(h.$('site-facts-list')),/51 units/,'valid evidence remains rendered after malformed metadata');
  assert.equal(h.$('run-site-analysis').disabled,false);
}
{
  const h=harness('street',{streamResponses:[
    [activity(partialFacts),{type:'error',run_id:'partial-run',error:'Analysis service temporarily offline.'}],
    [activity(partialFacts,'retry-run'),terminal(partialFacts,'retry-run')],
  ]});
  h.select(34.04670,-118.25249);await flush();
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.match(h.$('analysis-message').textContent,/Analysis service temporarily offline/);
  assert.equal(h.$('analysis-stale').hidden,false,'a real interrupted assessment remains incomplete');
  assert.equal(h.$('run-site-analysis').disabled,false,'failure releases the analysis button');
  assert.match(descendantsText(h.$('site-facts-list')),/Retrieval date unavailable/,'partial evidence survives failure');
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.equal(h.requests.filter(r=>r.url==='/api/site-analysis').length,2,'retry reaches the server despite the retained null-date fact');
  assert.equal(h.$('analysis-message').textContent,'');
  assert.equal(h.$('analysis-stale').hidden,true);
  assert.equal(h.$('run-site-analysis').disabled,false);
}
{
  const saved={id:'a'.repeat(32),version:1,resultVersion:1,status:'ready',artifacts:[],events:[],
    snapshot:{workflow:'street',siteId:'saved-null-date',lon:-118.25249,lat:34.04670,propertyId:null,
      question:'Inspect crossings while preserving access.',markings:[],rainfallScenario:null,inputRevision:0,proposalRevision:1},
    result:terminal(partialFacts).result};
  const h=harness('street',{savedProject:saved});
  h.map.fire('scoutselect',{project:saved});await flush();await flush();
  assert.match(descendantsText(h.$('site-facts-list')),/Retrieval date unavailable/);
  assert.match(descendantsText(h.$('agent-assessment')),/Property evidence remains available/);
  assert.equal(h.$('analysis-stale').hidden,true);
  assert.equal(h.$('run-site-analysis').disabled,false);
  assert.equal(h.requests.filter(r=>r.url==='/api/site-analysis').length,0,'restoration does not call the agent');
}
console.log('PASS: real streamed partial evidence, nullable metadata, interrupted-run retry and saved-result restoration');

{
  const facts = [
    {id:'parcel-area',label:'Selected parcel area',display:'70,744.08 m²',basis:'measured'},
    {id:'county-rainfall',label:'County design rainfall',value:1.03,display:'1.03 in',basis:'estimated'},
    {id:'county-watershed',label:'County watershed',display:'Ballona Creek',basis:'reported'},
    ...Array.from({length:35},(_,i)=>({id:`detail-${i}`,label:`Technical measurement ${i}`,display:'Recorded',basis:'reported'})),
  ];
  const report = {findings:[{text:'Full technical finding about the parcel.',fact_ids:['parcel-area']}],recommendations:[],questions:[]};
  const saved={id:'a'.repeat(32),version:1,resultVersion:1,status:'ready',artifacts:[],events:[],
    snapshot:{workflow:'water',siteId:'saved-water-summary',lon:-118.25249,lat:34.04670,propertyId:null,
      question:'Find a compact rain garden.',markings:[],rainfallScenario:null,inputRevision:0,proposalRevision:1},
    result:{report,facts,sourceStatus:{outlines:'ready',hydrology:'ready',property:'empty'},
      proposal:{workflow:'water',overlap:{status:'checked'},evidence:[{id:'county-rainfall'}],metrics:[]}}};
  const h = harness('water',{savedProject:saved});
  h.map.fire('scoutselect',{project:saved});await flush();await flush();
  const assessment = h.$('agent-assessment').children;
  const intro = assessment.filter(node=>node.tagName!=='details').map(descendantsText).join(' ');
  assert.match(intro,/A rain garden fits.*avoids mapped buildings.*Runoff capture is still unknown/);
  assert.match(intro,/Confirm next.*View design.*See supporting evidence/);
  assert.doesNotMatch(intro,/Full technical finding|70,744/);
  const full = assessment.find(node=>node.tagName==='details');
  assert.equal(full.open,false);
  assert.match(descendantsText(full),/Full technical finding.*Selected parcel area/);
  assert.equal(h.$('water-evidence-summary').children.filter(node=>node.tagName==='dt').length,4);
  assert.match(descendantsText(h.$('water-evidence-summary')),/1.03 inches over 24 hours.*LA County source/);
  assert.equal(h.$('all-site-facts-label').textContent,'All 38 measurements and sources');
  assert.equal(h.$('all-site-facts').open,false);
  assert.equal(h.$('site-facts-list').children.length,38);
  const rainSource = h.$('water-evidence-summary').children.flatMap(node=>node.children).find(node=>node.textContent==='LA County source');
  rainSource.click();
  assert.equal(h.$('all-site-facts').open,true,'source links open the exact record inside the ledger');
  assert.equal(h.$('fact-county-rainfall').open,true);
  assert.equal(h.requests.filter(r=>r.url==='/api/site-analysis').length,0);

  const blocked = {...saved,result:{...saved.result,proposal:null,draftQuestion:'Can you outline the driveway to keep clear?'}};
  const next = harness('water',{savedProject:blocked});
  next.map.fire('scoutselect',{project:blocked});await flush();await flush();
  const blockedIntro = next.$('agent-assessment').children.filter(node=>node.tagName!=='details').map(descendantsText).join(' ');
  assert.match(blockedIntro,/No rain garden placed.*Can you outline the driveway to keep clear/);
  assert.doesNotMatch(blockedIntro,/View design/);
}
console.log('PASS: saved stormwater assessments lead with the decision; all facts and blocked-site details remain accessible');

{
  const h=harness('street',{streamResponses:[new TypeError('Failed to fetch'),[activity(partialFacts),terminal(partialFacts)]]});
  h.select(34.04670,-118.25249);await flush();
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.match(h.$('analysis-message').textContent,/Failed to fetch/);
  assert.equal(h.$('run-site-analysis').disabled,false);
  assert.equal(h.$('cancel-site-analysis').hidden,true);
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.equal(h.$('analysis-message').textContent,'');
  assert.equal(h.$('analysis-stale').hidden,true);
}
console.log('PASS: network-offline analysis releases controls and permits a successful retry');

// A presentation exception must not discard the terminal result or strand a
// pending analysis. Inject failures only into the DOM mock, not the transport.
{
  const h=harness('street',{streamResponses:[
    [activity(partialFacts),terminal(partialFacts)],
    [activity(partialFacts,'display-retry'),terminal(partialFacts,'display-retry')],
  ]});
  h.select(34.04670,-118.25249);await flush();
  const factsList=h.$('site-facts-list'), originalAppend=factsList.append;
  let failAppend=true, fallbackShown=false;
  factsList.append=function(...rows) {
    if (failAppend) {failAppend=false;throw new Error('Injected evidence-row DOM failure');}
    fallbackShown ||= rows.some(row=>/Evidence item unavailable/.test(row.textContent));
    return originalAppend.apply(this,rows);
  };
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.equal(fallbackShown,true,'failed row has a visible fallback during activity');
  assert.match(descendantsText(h.$('agent-assessment')),/Property evidence remains available/,'terminal review is still consumed');
  assert.match(descendantsText(factsList),/51 units/,'other evidence survives the display failure');
  assert.equal(h.$('analysis-stale').hidden,true);
  assert.equal(h.$('run-site-analysis').disabled,false);
  assert.equal(h.$('cancel-site-analysis').hidden,true);

  const evidenceList=h.$('site-evidence-list'), originalReplace=evidenceList.replaceChildren;
  let failInitialRender=true;
  evidenceList.replaceChildren=function(...rows) {
    if (failInitialRender) {failInitialRender=false;throw new Error('Injected initial evidence render failure');}
    return originalReplace.apply(this,rows);
  };
  await assert.doesNotReject(h.$('site-analysis').events.submit({preventDefault(){}}));
  assert.equal(failInitialRender,false,'initial evidence render failure was exercised with retained facts');
  assert.equal(h.requests.filter(r=>r.url==='/api/site-analysis').length,2,'presentation failure does not prevent the next request');
  assert.match(descendantsText(h.$('agent-assessment')),/Property evidence remains available/);
  assert.equal(h.$('analysis-stale').hidden,true);
  assert.equal(h.$('run-site-analysis').disabled,false);
  assert.equal(h.$('cancel-site-analysis').hidden,true);
}
console.log('PASS: evidence-row and initial-render failures preserve stream completion and release controls');


// A failed continuation cannot erase the last completed traffic evaluation on
// reload. Restore its historical geometry as stale, keeping the failure visible.
{
  const prior={revision:2,inputRevision:1,proposal:null,alternatives:{failed_layout:{status:'rejected'}},
    savedAt:'2026-11-14T18:00:00+00:00',
    comparison:{status:'completed',site_id:'traffic-saved',workflow:'street',revision:2,input_revision:1,input_hash:'old-evaluation'},
    trafficPlan:{sourceDecisions:[{source:'Vexcel',decision:'Earlier crossing check.',fact_id:'traffic-old-check'}]}};
  const saved={id:'c'.repeat(32),version:4,resultVersion:4,status:'failed',artifacts:[],events:[],trafficDesignHistory:[prior],
    snapshot:{workflow:'street',siteId:'traffic-saved',lon:-118.25,lat:34.05,propertyId:null,question:'Shorten the lane reallocation.',markings:[],rainfallScenario:null,inputRevision:3,proposalRevision:3},
    result:{analysisError:'Provider rate limit interrupted this attempt.',report:null,facts:[],comparison:{status:'unavailable',revision:3}}};
  const h=harness('street',{savedProject:saved});h.map.fire('scoutselect',{project:saved});await flush();await flush();
  const restore=h.map.events.find(e=>e.name==='plannerrestore')?.event;
  assert.equal(restore?.revision,2);assert.equal(restore?.inputRevision,1);
  assert.equal(restore?.comparison.input_hash,'old-evaluation');
  assert.equal(restore?.savedAt,prior.savedAt);assert.equal(restore?.restored,true);
  assert.equal(restore?.trafficPlan.sourceDecisions[0].fact_id,undefined,'old source IDs cannot inspect the failed run’s current ledger');
  assert.equal(h.map.events.filter(e=>e.name==='plannerresult').length,0,'a failed revision must never publish as current');
  assert.match(h.$('analysis-message').textContent,/Provider rate limit/);
  assert.match(h.$('analysis-message').textContent,/saved reference/);
  assert.equal(h.requests.filter(q=>q.url==='/api/site-analysis').length,0);
  const empty={...saved,result:null,status:'interrupted'};
  const r=harness('street',{savedProject:empty});r.map.fire('scoutselect',{project:empty});await flush();await flush();
  assert.equal(r.map.events.find(e=>e.name==='plannerrestore')?.event.revision,2,'interrupted attempts without a result also restore permitted history');
  const foreign={...saved,trafficDesignHistory:[{...prior,comparison:{...prior.comparison,site_id:'another-site'}}]};
  const f=harness('street',{savedProject:foreign});f.map.fire('scoutselect',{project:foreign});await flush();await flush();
  assert.equal(f.map.events.filter(e=>e.name==='plannerrestore').length,0);
}
console.log('PASS: failed traffic continuation retains completed history as stale without publishing failed or foreign results');

// A failed water revision must retain the last evaluated concept and its own
// provenance without giving historical source IDs links into the current run.
{
  const prior={revision:2,inputRevision:1,savedAt:'2026-11-14T17:00:00+00:00',
    proposal:{site_id:'water-saved',workflow:'water',revision:2,input_revision:1,input_hash:'saved-water',
      geometry:[{id:'garden',geometry:{type:'Polygon',coordinates:[[[-118.25,34.05],[-118.2499,34.05],[-118.2499,34.0501],[-118.25,34.05]]]}}],
      metrics:[{id:'storage',proposed:3,unit:'m³',revision:2,input_hash:'saved-water'}]},
    alternatives:{smaller:{revision:2,input_revision:1}},
    waterPlan:{decisions:[{source:'Vexcel',decision:'Earlier footprint check.',fact_id:'old-water',evidence_ids:['old-outline']}]}};
  const older={...prior,revision:1,inputRevision:0,proposal:{...prior.proposal,revision:1,input_revision:0}};
  const invalid=[
    {...prior,proposal:{...prior.proposal,site_id:'another-site'}},
    {...prior,proposal:{...prior.proposal,workflow:'street'}},
    {...prior,revision:5,proposal:{...prior.proposal,revision:5}},
    {...prior,inputRevision:5,proposal:{...prior.proposal,input_revision:5}},
    {...prior,revision:3},
    {...prior,inputRevision:2},
    {...prior,proposal:{...prior.proposal,development_fixture:true}},
  ];
  const saved={id:'d'.repeat(32),version:4,resultVersion:4,status:'failed',artifacts:[],events:[],
    designHistory:[older,prior,...invalid],
    snapshot:{workflow:'water',siteId:'water-saved',lon:-118.25,lat:34.05,propertyId:null,
      question:'Make the garden smaller.',markings:[],rainfallScenario:null,inputRevision:3,proposalRevision:3},
    result:{analysisError:'The revised design exceeded the run deadline.',facts:[],proposal:{...prior.proposal,revision:3}}};
  const h=harness('water',{savedProject:saved});h.map.fire('scoutselect',{project:saved});await flush();await flush();
  const restore=h.map.events.find(e=>e.name==='plannerrestore')?.event;
  assert.equal(restore?.revision,2);assert.equal(restore?.inputRevision,1);
  assert.deepEqual(JSON.parse(JSON.stringify(restore?.proposal)),prior.proposal,'saved geometry and metrics remain bound to their original revision');
  assert.deepEqual(JSON.parse(JSON.stringify(restore?.alternatives)),prior.alternatives);
  assert.equal(restore?.designHistory.length,2,'only matching site and revision history reaches the inspector');
  assert.equal(restore?.savedAt,prior.savedAt);assert.equal(restore?.restored,true);
  assert.equal(restore?.historicalReference,true,'UI must not inspect old source IDs in the failed attempt ledger');
  assert.equal(restore?.waterPlan.decisions[0].evidence_ids[0],'old-outline','historical provenance stays readable');
  assert.equal(h.map.events.filter(e=>e.name==='plannerresult').length,0);
  assert.match(h.$('analysis-message').textContent,/run deadline/);
  assert.match(h.$('analysis-message').textContent,/saved reference/);
  assert.equal(h.$('analysis-stale').hidden,false);
  assert.equal(h.requests.filter(q=>q.url==='/api/site-analysis').length,0);
  for(const [status,result] of [['canceled',null],['interrupted',{facts:[],draftQuestion:'Incomplete question.'}]]) {
    const stopped={...saved,status,result};
    const r=harness('water',{savedProject:stopped});r.map.fire('scoutselect',{project:stopped});await flush();await flush();
    assert.equal(r.map.events.find(e=>e.name==='plannerrestore')?.event.revision,2);
    assert.equal(r.map.events.filter(e=>e.name==='plannerresult').length,0);
    assert.match(r.$('analysis-message').textContent,/previous run stopped/);
    assert.equal(r.$('analysis-stale').hidden,false);
  }
  const foreign={...saved,designHistory:invalid};
  const f=harness('water',{savedProject:foreign});f.map.fire('scoutselect',{project:foreign});await flush();await flush();
  assert.equal(f.map.events.filter(e=>e.name==='plannerrestore').length,0);
  const current={...saved,status:'ready',result:{...saved.result,analysisError:null,proposal:{...prior.proposal,revision:3,input_revision:3},savedAt:prior.savedAt,designHistory:[]}};
  const c=harness('water',{savedProject:current});c.map.fire('scoutselect',{project:current});await flush();await flush();
  const restoredCurrent=c.map.events.find(e=>e.name==='plannerresult')?.event;
  assert.equal(restoredCurrent?.restored,true);assert.equal(restoredCurrent?.savedAt,prior.savedAt);
  assert.equal(restoredCurrent?.designHistory[1].savedAt,prior.savedAt,'restoration prefers timestamped archive entries over legacy result copies');
}
console.log('PASS: stopped stormwater continuation retains same-site historical geometry, provenance and original saved time as stale');
