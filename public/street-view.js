// The same Vexcel mesh stays in place when proposal geometry is toggled.
(() => {
  const get = id => document.getElementById(id);
  const frame = get('street-frame');
  const container = get('street-canvas');
  const status = get('street-status');
  const credits = document.createElement('div');
  credits.hidden = true;
  container.append(credits);
  let viewer, cesiumLoad, sceneLoad, tileset;
  let site, config, siteLoad, proposal = null, proposalKey, proposalLayer, payloadVersion = 0;
  let heightQueue = Promise.resolve();
  let position = 0, proposed = false, heading = 0, pitch = -0.075, drag, switching = false;
  const heights = new Map();

  function loadCesium() {
    cesiumLoad ??= new Promise((resolve, reject) => {
      window.CESIUM_BASE_URL = '/vendor/cesium/';
      const script = document.createElement('script');
      script.src = '/vendor/cesium/Cesium.js';
      script.onload = () => resolve(window.Cesium);
      script.onerror = () => { cesiumLoad = null; reject(new Error('Install the local Cesium package with npm ci.')); };
      document.head.append(script);
    });
    return cesiumLoad;
  }

  async function initialize(sceneUrl) {
    if (!sceneLoad) sceneLoad = (async () => {
      const C = await loadCesium();
      if (!viewer) {
        viewer = new C.Viewer(container, {
          baseLayer: false, globe: false, animation: false, timeline: false,
          fullscreenButton: false, homeButton: false, geocoder: false, navigationHelpButton: false,
          baseLayerPicker: false, sceneModePicker: false, infoBox: false, selectionIndicator: false,
          scene3DOnly: true, creditContainer: credits, requestRenderMode: true,
          maximumRenderTimeChange: Infinity, contextOptions: { webgl: { antialias: true } },
        });
        viewer.scene.screenSpaceCameraController.enableInputs = false;
        viewer.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
        viewer.scene.fog.enabled = false;
        viewer.scene.backgroundColor = C.Color.fromCssColorString('#c2d1df');
        viewer.scene.skyBox.show = false;
        viewer.scene.sun.show = false;
        viewer.scene.moon.show = false;
        viewer.camera.frustum.near = .1;
        viewer.camera.frustum.far = 2500;
        viewer.clock.currentTime = C.JulianDate.fromIso8601('2026-07-15T23:00:00Z');
        viewer.clock.shouldAnimate = false;
        new ResizeObserver(() => {
          if (!frame.hidden) { viewer.resize(); viewer.scene.requestRender(); }
        }).observe(container);
      }
      tileset = await C.Cesium3DTileset.fromUrl(new C.Resource({ url: sceneUrl }), {
        maximumScreenSpaceError: 2, dynamicScreenSpaceError: false,
        cullRequestsWhileMoving: false,
        cacheBytes: 160 * 1024 ** 2, maximumCacheOverflowBytes: 80 * 1024 ** 2,
      });
      viewer.scene.primitives.add(tileset);
      return C;
    })().catch(error => { sceneLoad = null; throw error; });
    return sceneLoad;
  }

  function coordinateKey(coords) { return coords.map(coord => coord.toFixed(8)).join(','); }

  function measureHeights(C, points, selectedSite) {
    const job = heightQueue.then(() => sampleLoadedSurface(C, points, selectedSite));
    heightQueue = job.catch(() => {});
    return job;
  }

  async function sampleLoadedSurface(C, points, selectedSite) {
    if (selectedSite !== site || frame.hidden) throw new Error('Street view closed.');
    const unique = new Map(points.map(coords => [coordinateKey(coords), coords]));
    const missing = [...unique].filter(([key]) => !heights.has(key));
    if (!missing.length) return;
    const scene = viewer.scene;
    const camera = viewer.camera;
    const saved = { destination: C.Cartesian3.clone(camera.positionWC),
      orientation: { direction: C.Cartesian3.clone(camera.directionWC), up: C.Cartesian3.clone(camera.upWC) } };
    camera.setView({ destination: C.Cartesian3.fromDegrees(selectedSite.lon, selectedSite.lat, 200),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 } });
    scene.requestRender();
    try {
      await new Promise((resolve, reject) => {
        let remove;
        const timer = setTimeout(() => { remove(); reject(new Error('The detailed Vexcel street surface did not load in time.')); }, 26000);
        remove = scene.postRender.addEventListener(() => {
          if (selectedSite !== site || frame.hidden) {
            clearTimeout(timer); remove(); reject(new Error('Street view closed.')); return;
          }
          if (tileset.tilesLoaded && tileset.statistics.numberOfTilesWithContentReady > 0) {
            clearTimeout(timer); remove(); resolve();
          } else { scene.requestRender(); }
        });
      });
      for (const [key, coordinates] of missing) {
        const height = scene.sampleHeight(C.Cartographic.fromDegrees(...coordinates), [], .1);
        if (Number.isFinite(height)) heights.set(key, height);
      }
    } finally {
      if (site === selectedSite) { camera.setView(saved); scene.requestRender(); }
    }
    if (missing.some(([key]) => !heights.has(key))) throw new Error('The 3D mesh has no usable street height at part of this intersection.');
  }

  const heightAt = coords => heights.get(coordinateKey(coords));
  const currentStop = () => config?.stops[position];

  function center(geometry) {
    if (geometry.type === 'Point') return geometry.coordinates;
    const points = geometry.coordinates[0].slice(0, -1);
    const total = points.reduce(([lon, lat], point) => [lon + point[0], lat + point[1]], [0, 0]);
    return total.map(value => value / points.length);
  }

  function pointCamera(C) {
    const stop = currentStop();
    if (!stop || !Number.isFinite(heightAt(stop.position))) return;
    viewer.camera.setView({
      destination: C.Cartesian3.fromDegrees(...stop.position, heightAt(stop.position) + 1.72),
      orientation: { heading, pitch, roll: 0 },
    });
    viewer.scene.requestRender();
  }

  function updateControls() {
    const ready = !!currentStop() && Number.isFinite(heightAt(currentStop().position));
    get('street-back').disabled = !ready || switching || position <= 0;
    get('street-forward').disabled = !ready || switching || position >= config.stops.length - 1;
    get('street-position').textContent = ready ? currentStop().label : 'Street view';
    get('street-step').textContent = ready ? `${position + 1} / ${config.stops.length}` : '';
    get('street-existing').setAttribute('aria-pressed', String(!proposed));
    get('street-proposed').setAttribute('aria-pressed', String(proposed));
    get('street-proposed').disabled = !ready || !proposal?.features.length || switching;
  }

  function removeProposal() {
    if (proposalLayer) viewer.dataSources.remove(proposalLayer, true);
    proposalLayer = null;
  }

  const palette = { planted:'#568541', concrete:'#c7c6b4', marking:'#fff9de', amber:'#e1ae30',
    bike:'#7bbb76', reallocated:'#7a918b', shade:'#253c38' };

  function tree(C, entities, coords) {
    const height = heightAt(coords);
    entities.add({ position: C.Cartesian3.fromDegrees(...coords, height + 1.45),
      cylinder: { length: 2.9, topRadius: .1, bottomRadius: .16, material: C.Color.fromCssColorString('#78543c') } });
    for (const [east, north, above, radius] of [[0, 0, 3.75, 1.35], [0.55, 0, 3.35, 1.15], [-0.45, .3, 3.2, 1.05], [0, -.5, 3.25, .98]]) {
      const lon = coords[0] + east / (111195 * Math.cos(coords[1] * Math.PI / 180));
      const lat = coords[1] + north / 111195;
      entities.add({ position: C.Cartesian3.fromDegrees(lon, lat, height + above),
        ellipsoid: { radii: new C.Cartesian3(radius, radius, radius * 1.14),
          material: C.Color.fromCssColorString(above > 3.5 ? '#4e8051' : '#66964f') } });
    }
  }

  function streetLamp(C, entities, coords) {
    const height = heightAt(coords);
    entities.add({ position: C.Cartesian3.fromDegrees(...coords, height + 2.6),
      cylinder: { length: 5.2, topRadius: .07, bottomRadius: .12, material: C.Color.fromCssColorString('#53615f') } });
    entities.add({ position: C.Cartesian3.fromDegrees(...coords, height + 5.25),
      ellipsoid: { radii: new C.Cartesian3(.28, .18, .12), material: C.Color.fromCssColorString('#d4c68e') } });
  }

  async function renderProposal(C, version) {
    removeProposal();
    if (!proposal?.features.length) return;
    const features = proposal.features;
    // Sample one reference height for each surface and one for each point object.
    // Each concept surface is short. Its projected height is an approximation.
    const anchors = features.map(({ geometry }) => center(geometry));
    await measureHeights(C, anchors, site);
    if (version !== payloadVersion || !proposed || frame.hidden) return;
    const layer = new C.CustomDataSource('Proposed street design');
    for (const [i, { geometry, properties }] of features.entries()) {
      const kind = properties.kind;
      if (kind === 'tree') { tree(C, layer.entities, anchors[i]); continue; }
      if (kind === 'lamp') { streetLamp(C, layer.entities, anchors[i]); continue; }
      const ground = heightAt(anchors[i]);
      const height = properties.height_m;
      const color = C.Color.fromCssColorString(palette[kind]);
      const vertices = ring => C.Cartesian3.fromDegreesArray(ring.slice(0, -1).flat());
      const [exterior, ...holes] = geometry.coordinates;
      const hierarchy = new C.PolygonHierarchy(vertices(exterior), holes.map(ring => new C.PolygonHierarchy(vertices(ring))));
      const polygon = { hierarchy,
        height: ground + height + .09, material: kind === 'shade' ? color.withAlpha(.37) : color,
        ...(height > 0 ? { extrudedHeight: ground - .10, closeBottom: false } : {}) };
      layer.entities.add({ polygon });
    }
    await viewer.dataSources.add(layer);
    if (version !== payloadVersion || !proposed || frame.hidden) { viewer.dataSources.remove(layer, true); return; }
    proposalLayer = layer;
    viewer.scene.requestRender();
  }

  async function switchDesign(show) {
    const version = ++payloadVersion;
    removeProposal();
    if (!show) {
      proposed = false;
      switching = false;
      status.textContent = '';
      viewer?.scene.requestRender();
      updateControls();
      return;
    }
    if (!proposal?.features.length || !viewer) { updateControls(); return; }
    proposed = true;
    switching = true;
    status.textContent = 'Placing the proposal on the street…';
    updateControls();
    try {
      await renderProposal(window.Cesium, version);
      if (version === payloadVersion) status.textContent = 'Proposed design · concept';
    } catch (error) {
      if (version === payloadVersion) {
        proposed = false;
        status.textContent = error.message || 'The proposal could not be placed on this 3D mesh.';
      }
    } finally {
      if (version === payloadVersion) { switching = false; updateControls(); }
    }
  }

  async function show(preferProposal = false) {
    if (!site) return;
    const selectedSite = site;
    frame.hidden = false;
    get('aerial-frame').hidden = true;
    get('view-street').setAttribute('aria-pressed', 'true');
    get('view-aerial').setAttribute('aria-pressed', 'false');
    get('map-help').textContent = 'Drag to look around · use the arrows to move · compare from the same viewpoint';
    document.dispatchEvent(new Event('streetviewchange'));
    try {
      if (!siteLoad) siteLoad = (async () => {
        status.textContent = 'Loading Vexcel’s 3D street mesh…';
        const result = await requestContext('street-view', selectedSite);
        const C = await initialize(result.tileset);
        if (site !== selectedSite) return;
        config = result;
        position = 1;
        heading = C.Math.toRadians(config.stops[position].heading);
        pitch = -.075;
        viewer.resize();
        await measureHeights(C, config.stops.map(stop => stop.position), selectedSite);
        if (site === selectedSite) pointCamera(C);
      })().catch(error => { if (site === selectedSite) siteLoad = null; throw error; });
      await siteLoad;
      if (site !== selectedSite || frame.hidden) return;
      viewer.resize();
      viewer.scene.requestRender();
      updateControls();
      if (preferProposal && proposal?.features.length) {
        lookAtProposal(window.Cesium);
        await switchDesign(true);
      }
      else status.textContent = proposed ? 'Proposed design · concept' : '';
    } catch (error) {
      if (site === selectedSite && !frame.hidden) status.textContent = error.message || 'The Vexcel street mesh could not load.';
    }
  }

  function lookAtProposal(C) {
    const target = proposal.features.find(f => f.properties.kind === 'planted') || proposal.features[0];
    const [lng, lat] = center(target.geometry);
    const lonScale = 111195 * Math.cos(lat * Math.PI / 180);
    const distances = config.stops.map(({ position: [stopLon, stopLat] }) => ({
      east: (lng - stopLon) * lonScale, north: (lat - stopLat) * 111195,
    }));
    position = distances.reduce((best, point, index) =>
      Math.abs(Math.hypot(point.east, point.north) - 16) < Math.abs(Math.hypot(distances[best].east, distances[best].north) - 16)
        ? index : best, 0);
    heading = Math.atan2(distances[position].east, distances[position].north);
    pitch = -.095;
    pointCamera(C);
  }

  function showAerial() {
    if (switching) void switchDesign(false);
    frame.hidden = true;
    get('aerial-frame').hidden = false;
    get('view-street').setAttribute('aria-pressed', 'false');
    get('view-aerial').setAttribute('aria-pressed', 'true');
    get('map-help').textContent = 'Drag to pan · scroll or pinch to zoom · click a dot to inspect';
    if (typeof map !== 'undefined') map?.invalidateSize({ pan: false });
    document.dispatchEvent(new Event('streetviewchange'));
  }

  function move(step) {
    if (switching || !currentStop() || !Number.isFinite(heightAt(currentStop().position))) return;
    const target = position + step;
    if (target < 0 || target >= config.stops.length) return;
    position = target;
    pointCamera(window.Cesium);
    updateControls();
  }

  function look(dx, dy) {
    if (switching) return;
    heading += dx;
    pitch = Math.max(-1.48, Math.min(1.48, pitch + dy));
    pointCamera(window.Cesium);
  }

  get('view-aerial').addEventListener('click', showAerial);
  get('view-street').addEventListener('click', () => show());
  get('street-existing').addEventListener('click', () => switchDesign(false));
  get('street-proposed').addEventListener('click', () => switchDesign(true));
  get('street-back').addEventListener('click', () => move(-1));
  get('street-forward').addEventListener('click', () => move(1));
  container.addEventListener('pointerdown', event => {
    if (switching || !currentStop() || event.button !== 0) return;
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY };
    container.focus({ preventScroll: true });
    container.setPointerCapture(event.pointerId);
  });
  container.addEventListener('pointermove', event => {
    if (drag?.id !== event.pointerId) return;
    look((drag.x - event.clientX) * .004, (event.clientY - drag.y) * .004);
    drag.x = event.clientX;
    drag.y = event.clientY;
  });
  container.addEventListener('pointerup', () => { drag = null; });
  container.addEventListener('pointercancel', () => { drag = null; });
  container.addEventListener('keydown', event => {
    if (!currentStop()) return;
    const actions = { w: () => move(1), s: () => move(-1), arrowleft: () => look(-.12, 0),
      arrowright: () => look(.12, 0), arrowup: () => look(0, .10), arrowdown: () => look(0, -.10) };
    const action = actions[event.key.toLowerCase()];
    if (typeof action === 'function') { event.preventDefault(); action(); }
  });

  window.streetView = {
    select(next) {
      get('view-street').disabled = !next;
      if (next?.name === site?.name) return;
      site = next;
      config = null;
      siteLoad = null;
      proposal = null;
      proposalKey = null;
      position = 0;
      void switchDesign(false);
      showAerial();
    },
    design(next, key = null) {
      if (proposalKey === key) return;
      proposalKey = key;
      proposal = next;
      if (proposed && !frame.hidden) void switchDesign(!!proposal?.features.length);
      updateControls();
    },
    show,
    isOpen: () => !frame.hidden,
  };
})();
