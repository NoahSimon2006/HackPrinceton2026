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
  const map = { handlers: {}, createPane() {}, getPane: () => ({ style: {} }),
    on(name, handler) { this.handlers[name] = handler; },
    fire(name, event) { this.handlers[name]?.(event); }, setView() {}, closePopup() {}, getZoom: () => 17 };
  const requests = [];
  const json = (url) => new Promise((resolve, reject) => requests.push({ url, resolve, reject }));
  vm.runInNewContext(source, { $, map, json, planningMode: mode, coverage: null,
    URLSearchParams, AbortController, document: { createElement: element },
    L: { layerGroup: layer, geoJSON: layer, circleMarker: layer } });
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
console.log('PASS: automatic hydrology, partial failures/retry, manual inputs, workspace visibility, site races and caching');
