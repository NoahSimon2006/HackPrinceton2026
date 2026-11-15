// Run with: node tests/planner-hydrology.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../public/planner.js', import.meta.url), 'utf8');
function harness(mode = 'water', options = {}) {
  const elements = new Map();
  const element = () => ({ hidden: false, checked: false, disabled: false, value: '', textContent: '',
    events: {}, children: [], attributes: {}, style: { setProperty() {} }, classList: { toggle() {} },
    setAttribute(name, value) {this.attributes[name]=value;}, replaceChildren(...children) {this.children=children;}, append(...children) {this.children.push(...children);}, scrollIntoView() {},
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
  const requests = [];
  const json = (url, options = {}) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
  vm.runInNewContext(source, { $, map, json, planningMode: mode, coverage: options.coverage ?? null,
    insideCoverage: options.insideCoverage ?? (()=>true),
    cancelSiteAnalysis: () => {},
    streamSiteAnalysis: (payload, options) => json("/api/site-analysis", {body:JSON.stringify(payload), ...options}),
    URLSearchParams, AbortController, document: { createElement: element },
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
  return { $, map, layers, requests, select, workspace };
}
const watershed = (name) => ({ type: 'FeatureCollection', features: [{ type: 'Feature',
  properties: { WATERSHED: name, NAME: ' ' }, geometry: { type: 'Polygon', coordinates: [] } }] });
const rainfall = { estimate: { inches: .99, method: 'interpolated', depth_range: [.9, 1] } };
const flush = () => new Promise(setImmediate);

// Real UI events drive the controller: direct links, partial failure, retry,
// user input preservation, layer visibility and per-site caching.
{
  const h = harness();
  h.select(34.051, -118.2521);
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
  h.select(34.05, -118.25);
  assert.equal(h.requests.length, 0);
  h.workspace('water');
  h.select(34.06, -118.30);
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
  h.select(34.05, -118.25);
  assert.equal(h.$('watershed-name').textContent, 'Ballona');
  assert.equal(h.$('rain-depth').value, .99);
  assert.equal(h.requests.length, 4);
}
// Analysis sends the edited rainfall separately from the county estimate and
// marks an in-flight result stale when the user changes its inputs.
{
  const h = harness();
  h.select(34.05, -118.25);
  h.requests[0].resolve(rainfall);
  h.requests[1].resolve(watershed('ballona'));
  await flush();
  h.$('rain-depth').events.input({ target: { value: '1.5' } });
  h.$('rain-source').events.input({ target: { value: 'Sensitivity scenario' } });
  const pending = h.$('site-analysis').events.submit({ preventDefault() {} });
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
  h.select(34.05,-118.25);
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  const first=h.requests[0];
  first.options.onEvent({specialist:'site-evidence',status:'started',summary:'Reading source.',fact_ids:[]});
  assert.equal(h.$('activity-count').textContent,'· 1');
  h.select(34.06,-118.26);
  assert.equal(first.options.signal.aborted,true);
  first.options.onEvent({specialist:'lead',status:'completed',summary:'OLD RESULT',fact_ids:[]});
  first.resolve({report:{findings:[],recommendations:[],questions:['OLD RESULT']},facts:[]});
  await pending;
  assert.notEqual(h.$('analysis-message').textContent,'OLD RESULT');
  assert.equal(h.$('activity-count').textContent,'');
  const second=h.$('site-analysis').events.submit({preventDefault(){}});
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
  const selection={workflow:'street',reference:{version:'v1',layer:'counts',feature:'count-one'},
    source:{label:'LADOT',url:'https://example.org/source',retrieved_at:'2026-11-14'},
    layer:{unit:'vehicles reported',period:'Historical',method:'No scaling',limitations:'No current demand'},
    feature:{properties:{label:'Source intersection',center:[-118.25,34.05],value:18102,period:'2014-01-16'}}};
  h.map.fire('discoveryselect',selection);
  assert.equal(h.requests.length,0);
  assert.equal(h.$('discovery-context').hidden,false);
  assert.match(h.$('discovery-feature-value').textContent,/18,102/);
  assert.equal(h.$('discovery-feature-period').textContent,'2014-01-16');
  assert.match(h.$('planning-brief').value,/historical count/);
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  const body=JSON.parse(h.requests[0].options.body);
  assert.deepEqual(body.discoveryReference,selection.reference);
  assert.equal(body.source_record,undefined);
  h.map.fire('discoveryselect',{...selection,reference:{...selection.reference,feature:'count-two'}});
  assert.equal(h.requests[0].options.signal.aborted,true);
  h.requests[0].resolve({report:null,facts:[]});await pending;
}
console.log('PASS: discovery seeds a dated site brief and submits a reference without an automatic agent call');

// Real turning counts request physical alternatives; result identity follows the
// exact selected site and input revision, including repeated analyses.
{
  const h=harness('street');
  const selection={workflow:'street',reference:{version:'v1',layer:'turning',feature:'turning-one'},
    source:{label:'LADOT',url:'https://example.org/source',retrieved_at:'2026-11-14'},
    layer:{unit:'vehicles reported',period:'Historical',method:'Verified count',limitations:'Not current demand'},
    feature:{properties:{label:'Counted intersection',center:[-118.25,34.05],value:4000,period:'2011-11-08'}}};
  h.map.fire('discoveryselect',selection);
  assert.match(h.$('planning-brief').value,/at least two physical/);
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  const body=JSON.parse(h.requests[0].options.body);
  assert.equal(body.siteId,'34.050000,-118.250000');
  assert.equal(body.inputRevision,1);assert.equal(body.proposalRevision,1);
  h.requests[0].resolve({report:null,facts:[],proposal:{revision:1},comparison:{revision:1}});await pending;
  const published=h.map.events.filter(e=>e.name==='plannerresult');
  assert.equal(published.length,1);assert.equal(published[0].event.siteId,body.siteId);
  assert.equal(published[0].event.workflow,'street');assert.equal(published[0].event.inputRevision,1);
  assert.equal(published[0].event.revision,1);
  const repeated=h.$('site-analysis').events.submit({preventDefault(){}});
  assert.equal(JSON.parse(h.requests[1].options.body).proposalRevision,2);
  h.select(34.06,-118.26);h.requests[1].resolve({report:null,facts:[],proposal:{revision:2},comparison:{revision:2}});await repeated;
  assert.equal(h.map.events.filter(e=>e.name==='plannerresult').length,1,'superseded site analysis must not emit a proposal');
}
console.log('PASS: turning-count brief, proposal identity, monotonic revisions and suppressed stale/superseded publication');

// Re-selecting the active workspace is a no-op: it must not erase a published
// proposal through a redundant plannersite event or cancel the active request.
{
  const h=harness('street');h.select(34.05,-118.25);
  const before=h.map.events.filter(e=>e.name==='plannersite').length;
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
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
  h.$('use-map-center').events.click();
  assert.equal(h.map.events.at(-1).name,'plannersite');
  assert.equal(h.map.events.at(-1).event.siteId,'34.050000,-118.250000');
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
  const firstBody=JSON.parse(h.requests[0].options.body);
  assert.equal(firstBody.markings[0].kind,'access');
  assert.deepEqual(firstBody.markings[0].geometry.coordinates[0],[
    [-118.25,34.05],[-118.25,34.0501],[-118.2499,34.0501],[-118.25,34.05]]);
  h.requests[0].resolve({report:null,facts:[]});await first;
  h.$('shape-list').children[0].children[1].events.click();
  field(0,'lat').value='34.04995';field(0,'lat').events.input();h.$('draw-save').events.click();
  assert.equal(h.map.events.filter(e=>e.name==='plannerinputs').at(-1).event.inputRevision,2);
  const second=h.$('site-analysis').events.submit({preventDefault(){}});
  const secondBody=JSON.parse(h.requests[1].options.body);
  assert.equal(secondBody.inputRevision,2);assert.equal(secondBody.proposalRevision,2);
  assert.deepEqual(secondBody.markings[0].geometry.coordinates[0][0],[-118.25,34.04995]);
  h.requests[1].resolve({report:null,facts:[]});await second;
  const before=h.map.events.filter(e=>e.name==='plannersite').length;
  h.map.center={lat:Infinity,lng:-118.25};h.$('use-map-center').events.click();
  h.map.center={lat:34.05,lng:-118.248};h.$('use-map-center').events.click();
  assert.equal(h.map.events.filter(e=>e.name==='plannersite').length,before,'invalid/uncovered centers cannot select a site');
}
console.log('PASS: active-workspace persistence and keyboard site/constraint revisions with coordinate validation');

// A spherical distance just under 1 km may already be outside the server's
// projected buffer. The UI keeps a margin rather than saving a doomed request.
{
  const h=harness('street');h.select(34.05,-118.25);
  h.$('mark-actions').children[1].events.click();h.$('draw-add-center').events.click();
  const longitude=h.$('draw-coordinates').children[0].children[2].children[0];
  longitude.value='-118.23917';longitude.events.input();
  assert.match(h.$('draw-coordinate-error').textContent,/990 m/);
  assert.equal(h.$('draw-save').disabled,true);
  longitude.value='-118.2394';longitude.events.input();
  assert.equal(h.$('draw-coordinate-error').hidden,true);
}

// Water inputs are explicit, per-site and revision-bound; no proposed defaults.
{
  const h=harness();h.select(34.051,-118.2521);
  h.requests[0].resolve(rainfall);h.requests[1].resolve(watershed('Ballona'));await flush();h.requests.length=0;
  assert.equal(h.$('water-design').hidden,false);assert.equal(h.$('water-storage-depth').value,'');assert.equal(h.$('water-confirm-connections').checked,false);
  let pending=h.$('site-analysis').events.submit({preventDefault(){}});
  assert.equal(JSON.parse(h.requests[0].options.body).waterDesign,null);
  h.requests[0].resolve({report:null,facts:[]});await pending;h.requests.length=0;
  const enter=(id,value)=>{h.$(id).value=value;h.$(id).events.input({target:h.$(id)});};
  enter('water-storage-depth','0.2');
  await h.$('update-water-comparison').events.click({preventDefault(){}});
  assert.equal(h.requests.length,0,'partial inputs cannot silently use defaults');
  pending=h.$('site-analysis').events.submit({preventDefault(){}});
  assert.equal(JSON.parse(h.requests[0].options.body).waterDesign,null,'optional comparison fields cannot block an agent draft');
  h.requests[0].resolve({report:null,facts:[]});await pending;h.requests.length=0;
  enter('water-runoff-coefficient','0.85');enter('water-confirmation-note','Proposed storage and field-checked connection.');
  for(const id of ['water-confirm-surface','water-confirm-connections','water-confirm-access','water-confirm-overflow']) {h.$(id).checked=true;h.$(id).events.change({target:h.$(id)});}
  pending=h.$('update-water-comparison').events.click({preventDefault(){}});
  const body=JSON.parse(h.requests[0].options.body);
  assert.deepEqual(body.waterDesign,{storage_depth_m:.2,runoff_coefficient:.85,confirmation_note:'Proposed storage and field-checked connection.',surface_confirmed:true,connections_confirmed:true,access_confirmed:true,overflow_confirmed:true});
  assert.equal(body.inputRevision,7);
  enter('water-storage-depth','0.25');assert.equal(h.requests[0].options.signal.aborted,true,'editing design cancels its active run');
  assert.equal(h.$('water-confirm-overflow').checked,false,'new depth needs overflow confirmation again');
  assert.equal(h.$('water-confirm-surface').checked,true,'changing depth does not invalidate the same source surface');
  h.requests[0].resolve({report:null,facts:[],proposal:{revision:2},comparison:{revision:2}});await pending;
  assert.equal(h.map.events.filter(event=>event.name==='plannerresult').length,0);
  h.select(34.052,-118.253);assert.equal(h.$('water-storage-depth').value,'');assert.equal(h.$('water-confirm-access').checked,false);
  h.select(34.051,-118.2521);assert.equal(h.$('water-storage-depth').value,'0.25','design settings remain scoped to their site');
  h.workspace('street');assert.equal(h.$('water-design').hidden,true);
  h.requests.length=0;pending=h.$('site-analysis').events.submit({preventDefault(){}});
  assert.equal(JSON.parse(h.requests[0].options.body).waterDesign,null,'water inputs never enter traffic request');
  h.requests[0].resolve({report:null,facts:[]});await pending;
}
console.log('PASS: explicit stormwater inputs, no defaults, per-site persistence, update action, cancellation and workflow isolation');

// Confirmations describe a particular physical layout, not every future edit.
{
  const h=harness();h.select(34.05,-118.25);
  const confirm=()=>{for(const id of ['water-confirm-surface','water-confirm-connections','water-confirm-access','water-confirm-overflow']) {h.$(id).checked=true;h.$(id).events.change({target:h.$(id)});}};
  confirm();h.$('water-mark-treatment').events.click();
  for(const point of [[34.05,-118.25],[34.0501,-118.25],[34.0501,-118.2499]]) {h.map.center={lat:point[0],lng:point[1]};h.$('draw-add-center').events.click();}
  h.$('draw-save').events.click();
  for(const id of ['water-confirm-surface','water-confirm-connections','water-confirm-access','water-confirm-overflow']) assert.equal(h.$(id).checked,false);
  confirm();h.$('shape-list').children[0].children[2].events.click();
  assert.equal(h.$('water-confirm-connections').checked,false,'removal cannot retain an old connection confirmation');
  confirm();h.$('water-runoff-coefficient').value='.7';h.$('water-runoff-coefficient').events.input({target:h.$('water-runoff-coefficient')});
  assert.equal(h.$('water-confirm-surface').checked,false);assert.equal(h.$('water-confirm-access').checked,true);
}
console.log('PASS: geometry, coefficient and depth changes invalidate their physical confirmations');

// A late automatic county request must not replace the newer analysis source.
{
  const h=harness();h.select(34.05,-118.25);
  const pending=h.$('site-analysis').events.submit({preventDefault(){}});
  h.requests[2].resolve({report:null,facts:[],hydrology:{estimate:{inches:1.1,method:'on_contour',depth_range:[1.1,1.1]},watershed:watershed('Ballona')}});await pending;
  h.requests[0].resolve(rainfall);h.requests[1].reject(new Error('Old lookup failed'));await flush();
  assert.equal(h.$('rain-value').textContent,'1.10');assert.equal(h.$('watershed-name').textContent,'Ballona');
  assert.equal(h.$('retry-hydrology').hidden,true);
  const next=h.$('site-analysis').events.submit({preventDefault(){}});
  h.requests[3].resolve({report:null,facts:[],hydrology:{unavailable:['rainfall','watershed']}});await next;
  assert.match(h.$('rain-result').textContent,/latest analysis.*cached/);
  assert.match(h.$('watershed-result').textContent,/latest analysis.*cached/);
  assert.equal(h.$('retry-hydrology').hidden,false,'latest source failure exposes a retry instead of stale success');
}
console.log('PASS: latest hydrology source wins and cached values disclose later source failures');

{
 const h=harness('street',{coverage:{},insideCoverage:point=>point.lng < -118.249});
 h.map.fire('plannerproperty',{property:{id:'outside',name:'Outside',lat:34.05,lon:-118.248}});
 assert.equal(h.map.events.filter(e=>e.name==='plannersite').length,1,'marker click outside imagery cannot select a site');
 assert.match(h.$('planner-status').textContent,/coverage/);
 h.map.fire('plannerproperty',{property:{id:'inside',name:'Inside',lat:34.05,lon:-118.25}});
 assert.equal(h.map.events.filter(e=>e.name==='plannersite').at(-1).event.siteId,'property:inside');
}
