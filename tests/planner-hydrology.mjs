// Run with: node tests/planner-hydrology.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../public/planner.js', import.meta.url), 'utf8');
function harness(mode = 'water') {
  const elements = new Map();
  const element = () => ({ hidden: false, checked: false, disabled: false, value: '', textContent: '',
    events: {}, style: { setProperty() {} }, classList: { toggle() {} },
    setAttribute() {}, replaceChildren() {}, append() {}, scrollIntoView() {},
    addEventListener(name, handler) { this.events[name] = handler; } });
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  $('show-watershed').checked = true;
  const layers = [];
  const layer = () => {
    const result = { data: [], attached: false, addTo() { this.attached = true; return this; },
      remove() { this.attached = false; }, clearLayers() { this.data = []; },
      addData(data) { this.data.push(data); }, bindTooltip() { return this; } };
    layers.push(result);
    return result;
  };
  const map = { handlers: {}, events: [], createPane() {}, getPane: () => ({ style: {} }),
    on(name, handler) { this.handlers[name] = handler; },
    fire(name, event) { this.events.push({name,event}); this.handlers[name]?.(event); }, setView() {}, closePopup() {}, getZoom: () => 17 };
  const requests = [];
  const json = (url, options = {}) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
  vm.runInNewContext(source, { $, map, json, planningMode: mode, coverage: null,
    cancelSiteAnalysis: () => {},
    streamSiteAnalysis: (payload, options) => json("/api/site-analysis", {body:JSON.stringify(payload), ...options}),
    URLSearchParams, AbortController, document: { createElement: element },
    L: { latLng: (lat,lng) => ({lat,lng}), layerGroup: layer, geoJSON: layer, circleMarker: layer } });
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
