import {eventVolumes} from './demo-math.js';

const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat('en-US', {maximumFractionDigits:2}).format(value);
const details = {
  inlet: ['01 · Bring water into the garden', 'A proposed curb opening and stone forebay admit street runoff and slow it before the planted bed. The inlet location and connection are design assumptions to verify on site.'],
  planting: ['02 · Make room for rain and roots', 'Two 12 × 2.4 m planted cells provide 57.6 m² of landscape. Sedges, flowering plants and small trees illustrate a possible planting palette. The 150 mm ponding allowance gives 8.64 m³ of gross temporary storage.'],
  overflow: ['03 · Keep an overflow route', 'A raised overflow explains how water could leave once ponding storage fills. Its connection is proposed, not a located existing drain. The central 19 m gap remains unplanted for an access zone.'],
};
let renderer = null, sceneData = null, request = null, generation = 0;
let mode = 'proposed', view = 'overview', orbit = false, tourOpener = null;

function detail(name) {
  const [title, copy] = details[name] || details.planting;
  $('demo-detail-title').textContent = title;
  $('demo-detail-copy').textContent = copy;
  document.querySelectorAll('[data-feature]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.feature === name)));
}

function rain() {
  if (!sceneData) return;
  const value = eventVolumes($('demo-rain').value, sceneData.scenario);
  $('demo-rain-value').textContent = `${number(value.rainMm)} mm`;
  $('demo-capture').textContent = `${number(value.captured)} m³`;
  $('demo-overflow').textContent = `${number(value.overflow)} m³`;
  $('demo-storage').textContent = `${number(sceneData.scenario.storageM3)} m³`;
  renderer?.setRain(value.rainMm);
  $('demo-stage').dataset.rainMm = value.rainMm;
  $('demo-stage').dataset.capturedM3 = value.captured;
  $('demo-stage').dataset.overflowM3 = value.overflow;
}

function setMode(next) {
  if (next === 'existing' && view === 'section') setView('overview');
  mode = next;
  $('demo-existing').setAttribute('aria-pressed', String(mode === 'existing'));
  $('demo-proposed').setAttribute('aria-pressed', String(mode === 'proposed'));
  document.body.dataset.mode = mode;
  renderer?.setMode(mode);
  $('demo-status').textContent = mode === 'existing'
    ? 'Illustrative existing frontage · same camera and sourced building outlines.'
    : 'Proposed frontage · orbit to explore, or follow the details below.';
}

function setView(next) {
  view = next;
  orbit = false;
  $('demo-orbit').setAttribute('aria-pressed', 'false');
  document.querySelectorAll('button[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === view)));
  if (next === 'section') setMode('proposed');
  document.body.dataset.view = view;
  renderer?.setView(view);
  if (view === 'section') $('demo-status').textContent = 'Illustrative section · soil, gravel and drain layers explain the design; they are not surveyed.';
}

function failure(message) {
  $('demo-error').hidden = false;
  $('demo-status').textContent = message;
  $('demo-stage').setAttribute('aria-busy', 'false');
}

async function load() {
  const ticket = ++generation;
  request?.abort(); const controller = new AbortController(); request = controller;
  renderer?.dispose(); renderer = null;
  $('demo-error').hidden = true;
  $('demo-stage').setAttribute('aria-busy', 'true');
  $('demo-status').textContent = 'Preparing the sourced building model and planting study…';
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch('/api/demo-scene', {signal:controller.signal, cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The local demo could not be loaded.');
    if (data.kind !== 'curated-demo' || data.site?.propertyId !== '4497305' || data.units !== 'm') throw new Error('This source snapshot does not match Hancock Terrace.');
    const {createDemoScene} = await import('./demo-scene-renderer.js');
    if (ticket !== generation) return;
    sceneData = data;
    renderer = createDemoScene($('demo-stage'), data, {
      onError: () => failure('The graphics context was interrupted. Retry the scene; the exterior capture is also available.'),
      onSelect: detail,
      onFrame(points) {
        for (const point of points) {
          const button = document.querySelector(`#demo-hotspots [data-feature="${point.id}"]`);
          if (!button) continue;
          button.hidden = !point.visible || mode === 'existing' || view === 'section';
          button.style.transform = `translate(${point.x}px, ${point.y}px) translate(-50%, -50%)`;
        }
      },
    });
    setMode(mode); setView(view); rain(); detail('planting');
    $('demo-stage').setAttribute('aria-busy', 'false');
  } catch (error) {
    if (ticket === generation) failure(error.name === 'AbortError' ? 'The scene took too long to load. Retry when the local server is ready.' : error.message);
  } finally {clearTimeout(timer);}
}

$('demo-existing').addEventListener('click', () => setMode('existing'));
$('demo-proposed').addEventListener('click', () => setMode('proposed'));
$('demo-rain').addEventListener('input', rain);
$('demo-reset').addEventListener('click', () => {renderer?.reset(); setView('overview');});
$('demo-orbit').addEventListener('click', () => {
  orbit = !orbit; renderer?.setAutoRotate(orbit);
  $('demo-orbit').setAttribute('aria-pressed', String(orbit));
});
$('demo-retry').addEventListener('click', load);
$('demo-export').addEventListener('click', () => {
  if (!renderer) return;
  try {
    const link = $('demo-download');
    link.download = `hancock-terrace-${mode}-${view}.png`;
    link.href = renderer.exportPng();
    $('demo-export-image').src = link.href;
    $('demo-export-image').alt = `Hancock Terrace — authored ${mode} ${view} rendering`;
    $('demo-export-dialog').showModal(); renderer.setPaused(true);
  } catch {failure('The image could not be saved. Retry the scene and try again.');}
});
$('demo-export-close').addEventListener('click', () => $('demo-export-dialog').close());
$('demo-export-dialog').addEventListener('close', () => {renderer?.setPaused(false); $('demo-export').focus();});
document.querySelectorAll('button[data-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
document.querySelectorAll('[data-feature]').forEach(button => button.addEventListener('click', () => detail(button.dataset.feature)));

let tourGeneration = 0;
async function openTour() {
  tourOpener = document.activeElement;
  const ticket = ++tourGeneration;
  $('demo-tour-host').textContent = 'Checking the exterior capture for Hancock Terrace…';
  $('demo-tour-dialog').showModal(); renderer?.setPaused(true);
  try {
    const response = await fetch('/api/site-view?propertyId=4497305', {cache:'no-store'});
    const data = await response.json();
    if (ticket !== tourGeneration || !$('demo-tour-dialog').open) return;
    const scan = data.scans?.find(scan => scan.modelId === 'SU76BQEbevu');
    if (!response.ok || data.property?.id !== '4497305' || !scan || scan.url !== 'https://my.matterport.com/show/?m=SU76BQEbevu') throw new Error('The site-matched exterior capture is unavailable.');
    const frame = document.createElement('iframe');
    frame.title = 'Hancock Terrace — genuine exterior capture, separate from the proposed design';
    frame.src = scan.url; frame.allow = 'fullscreen; xr-spatial-tracking'; frame.allowFullscreen = true;
    $('demo-tour-host').replaceChildren(frame);
  } catch (error) {
    if (ticket === tourGeneration) $('demo-tour-host').textContent = error.message;
  }
}
$('demo-tour').addEventListener('click', openTour);
$('demo-show-capture').addEventListener('click', openTour);
$('demo-tour-close').addEventListener('click', () => $('demo-tour-dialog').close());
$('demo-tour-dialog').addEventListener('close', () => {
  ++tourGeneration; $('demo-tour-host').replaceChildren(); renderer?.setPaused(false); tourOpener?.focus();
});
window.addEventListener('pagehide', () => {++generation; request?.abort(); renderer?.dispose();});
window.addEventListener('pageshow', event => {if (event.persisted) load();});
load();
