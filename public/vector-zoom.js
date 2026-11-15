// Keeps vector overlays at a steady on-screen size while the map zooms, and
// draws lines a little thinner when zoomed out.
//
// Every overlay in this app is drawn by a Leaflet canvas renderer (the map sets
// preferCanvas). Leaflet 1.9 zooms those renderers by CSS-scaling the canvas
// element until the zoom settles, so strokes and circle markers swell (or
// shrink) during the gesture and snap back when the canvas is redrawn on
// moveend. Here the canvas element is never scaled. Each zoom frame redraws it
// with the same view transform the tiles use, and divides stroke widths, dash
// lengths and circle-marker radii by that frame's scale.
//
// - Wheel, trackpad and touch pinch, and flyTo move the map one frame at a time
//   (`zoom` events with `pinch`/`flyTo`).
// - Buttons, double-click, keyboard and animated setView/fitBounds use
//   Leaflet's CSS zoom animation for the tiles. A hidden probe element runs the
//   same CSS transition, and its sampled progress gives each frame's view.
// Each frame re-projects the layers at its view when that is cheap, so the
// last frame matches the settled redraw exactly. Costly layers redraw their
// existing projection through the canvas transform and re-project only after
// enough zoom drift that rounded, simplified geometry would visibly shift.
(function () {
  "use strict";
  const L = window.L;
  if (!L?.Canvas) return;

  const proto = L.Canvas.prototype;
  const base = {
    onAdd: proto.onAdd,
    onRemove: proto.onRemove,
    _update: proto._update,
    _redraw: proto._redraw,
    _updateCircle: proto._updateCircle,
  };
  // Zoom levels drawn from one projection before re-projecting.
  const REBASE_LEVELS = .35;
  // Re-project on every frame while a full projection costs less than this.
  const CHEAP_REBASE_MS = 4;
  // Viewport fraction clipped in on each side during live zoom, for zooming out.
  const CLIP_MARGIN = .5;
  const PROBE_TRAVEL = 10000;
  // Lines draw at their full weight from this zoom in, and thin by this share
  // per zoom level further out, down to the thinnest share (never below 1px).
  const FULL_WEIGHT_ZOOM = 16;
  const THINNING_PER_LEVEL = .12;
  const THINNEST = .45;
  const weightShare = (zoom) =>
    Math.min(1, Math.max(THINNEST, 1 - (FULL_WEIGHT_ZOOM - zoom) * THINNING_PER_LEVEL));
  const pixelRatio = () => L.Browser.retina ? 2 : 1;
  const frame = (callback) => window.requestAnimationFrame(callback);
  const cancelFrame = (id) => id && window.cancelAnimationFrame(id);

  // Samples the eased progress of Leaflet's CSS zoom transition. The probe sits
  // in the map pane with the class Leaflet animates, so it shares the tiles'
  // duration, easing and start frame.
  function zoomClock(map) {
    if (map._vectorZoomClock) return map._vectorZoomClock;
    const probe = L.DomUtil.create("div", "leaflet-zoom-animated", map.getPane("mapPane"));
    probe.setAttribute("aria-hidden", "true");
    Object.assign(probe.style, { position: "absolute", left: "0", top: "0", width: "0", height: "0",
      visibility: "hidden", pointerEvents: "none" });
    let animation = null;
    let sampledAt = null;
    let progress = 0;
    map._vectorZoomClock = {
      start(event) {
        if (event === animation) return;
        animation = event;
        sampledAt = null;
        progress = 0;
        probe.style.transition = "none";
        probe.style.transform = "translateX(0px)";
        // Commit the start value so the next change runs the eased transition.
        void getComputedStyle(probe).transform;
        probe.style.transition = "";
        probe.style.transform = `translateX(${PROBE_TRAVEL}px)`;
      },
      progress(time) {
        if (time !== sampledAt) {
          sampledAt = time;
          const match = /matrix(3d)?\(([^)]+)\)/.exec(getComputedStyle(probe).transform);
          const x = match ? Number(match[2].split(",")[match[1] ? 12 : 4]) : 0;
          progress = Math.min(1, Math.max(0, x / PROBE_TRAVEL || 0));
        }
        return progress;
      },
    };
    return map._vectorZoomClock;
  }

  L.Canvas.include({
    onAdd() {
      base.onAdd.call(this);
      // Zoom frames are drawn into the canvas; it must never be CSS-scaled.
      L.DomUtil.removeClass(this._container, "leaflet-zoom-animated");
    },

    onRemove() {
      this._stopLiveZoom();
      base.onRemove.call(this);
    },

    _update() {
      if (this._map._animatingZoom && this._bounds) return;
      this._stopLiveZoom();
      base._update.call(this);
      this._anchorLiveZoom();
    },

    // Records the projection the layers were drawn from.
    _anchorLiveZoom() {
      this._liveOrigin = this._map.getPixelOrigin();
      this._canvasMin = this._bounds.min.clone();
    },

    _stopLiveZoom() {
      cancelFrame(this._zoomAnimFrame);
      cancelFrame(this._liveRequest);
      this._zoomAnimFrame = this._liveRequest = this._zoomAnim = this._live = this._liveView = null;
      this._liveScale = 1;
    },

    // A view is a zoom and the pixel origin placing it in the map pane:
    // pane point = map.project(latlng, zoom) - origin.
    _mapView() {
      return { zoom: this._map.getZoom(), origin: this._map.getPixelOrigin() };
    },

    _shownView() {
      return this._liveView || { zoom: this._zoom, origin: this._liveOrigin };
    },

    // Affine map from the drawn layer points P to the pane at a view:
    // pane = k * P + (x, y).
    _stateForView(view) {
      const k = this._map.getZoomScale(view.zoom, this._zoom);
      return { k, x: this._liveOrigin.x * k - view.origin.x, y: this._liveOrigin.y * k - view.origin.y };
    },

    // Renderer._reset passes the renderer's own view; any other caller gets a live frame.
    _updateTransform(center, zoom) {
      if (!this._map || (!this._live && center === this._center && zoom === this._zoom)) return;
      this._drawLive({ zoom, origin: this._map._getNewPixelOrigin(center, zoom) });
    },

    _onZoom(event) {
      if (!this._map) return;
      if (event && (event.pinch || event.flyTo)) {
        this._showView(this._mapView());
        return;
      }
      // Other zoom events are followed by moveend in the same task, which
      // redraws and cancels this request.
      if (!this._liveRequest) {
        this._liveRequest = frame(() => {
          this._liveRequest = null;
          if (this._map) this._drawLive(this._mapView());
        });
      }
    },

    // Re-projects when that is cheap, after enough zoom drift that rounded and
    // simplified geometry would visibly shift, or when clipping would show;
    // otherwise redraws the current projection through the canvas transform.
    _showView(view) {
      const state = this._stateForView(view);
      if ((this._rebaseCost ?? 0) < CHEAP_REBASE_MS || Math.abs(Math.log2(state.k)) > REBASE_LEVELS ||
          !this._coversView(state)) {
        this._reprojectView(view);
      } else {
        this._drawLive(view, state);
      }
    },

    _onAnimZoom(event) {
      const map = this._map;
      const clock = zoomClock(map);
      clock.start(event);
      const to = { zoom: event.zoom, origin: map._getNewPixelOrigin(event.center, event.zoom) };
      // Intermediate views lie between the two end views, so covering both
      // keeps a zoom-out drawn through the canvas transform free of clipped edges.
      const target = this._stateForView(to);
      if (!this._coversView(target)) this._clipToView(target);
      this._zoomAnim = { from: this._shownView(), to, clock };
      if (!this._zoomAnimFrame) this._zoomAnimFrame = frame((time) => this._zoomAnimStep(time));
    },

    _zoomAnimStep(time) {
      this._zoomAnimFrame = null;
      const animation = this._zoomAnim;
      if (!animation || !this._map?._animatingZoom) {
        this._zoomAnim = null;
        return;
      }
      const { from, to, clock } = animation;
      const p = clock.progress(time);
      if (p >= 1) {
        this._showView(to);
      } else {
        // CSS interpolates the tiles' scale and translation linearly.
        const scale = this._map.getZoomScale(to.zoom, from.zoom);
        const k = 1 + (scale - 1) * p;
        this._showView({ zoom: from.zoom + Math.log2(k), origin: L.point(
          from.origin.x * k - (from.origin.x * scale - to.origin.x) * p,
          from.origin.y * k - (from.origin.y * scale - to.origin.y) * p) });
      }
      this._zoomAnimFrame = frame((next) => this._zoomAnimStep(next));
    },

    // Pane-space viewport in drawn layer coordinates at a live state.
    _viewInLayer(state) {
      const map = this._map;
      const min = map.containerPointToLayerPoint([0, 0]);
      const max = min.add(map.getSize());
      return L.bounds(
        L.point((min.x - state.x) / state.k, (min.y - state.y) / state.k),
        L.point((max.x - state.x) / state.k, (max.y - state.y) / state.k));
    },

    _coversView(state) {
      return this._bounds.contains(this._viewInLayer(state));
    },

    // Leaflet's segment clipping rounds intersections and never terminates
    // against fractional bounds, so clip bounds are always whole pixels.
    _setClipBounds(min, max) {
      this._bounds = L.bounds(min.floor(), max.ceil());
    },

    _clipToView(state) {
      const view = this._viewInLayer(state);
      const pad = this._map.getSize().multiplyBy(this.options.padding / state.k);
      const bounds = L.bounds([this._bounds.min, this._bounds.max, view.min.subtract(pad), view.max.add(pad)]);
      this._setClipBounds(bounds.min, bounds.max);
      for (const id in this._layers) this._layers[id]._update();
    },

    // Re-projects every layer at a view, exactly as moveend will draw it once
    // the map settles there. Leaflet projects with the map's own zoom and
    // origin, so a CSS-animated frame's view is lent to the map meanwhile.
    _reprojectView(view) {
      const started = performance.now();
      const map = this._map;
      const actual = { zoom: map._zoom, origin: map._pixelOrigin };
      this._live = this._liveView = null;
      this._liveScale = 1;
      map._zoom = view.zoom;
      map._pixelOrigin = view.origin;
      try {
        L.Renderer.prototype._update.call(this);
        for (const id in this._layers) this._layers[id]._project();
      } finally {
        map._zoom = actual.zoom;
        map._pixelOrigin = actual.origin;
      }
      this._liveOrigin = view.origin;
      const bounds = this._bounds;
      const pad = map.getSize().multiplyBy(CLIP_MARGIN);
      this._setClipBounds(bounds.min.subtract(pad), bounds.max.add(pad));
      for (const id in this._layers) this._layers[id]._update();
      // The canvas element stays where moveend placed it until the next moveend.
      const m = pixelRatio();
      cancelFrame(this._redrawRequest);
      this._ctx.setTransform(m, 0, 0, m, -m * this._canvasMin.x, -m * this._canvasMin.y);
      this._redrawBounds = null;
      this._redraw();
      const cost = performance.now() - started;
      this._rebaseCost = this._rebaseCost === undefined ? cost : this._rebaseCost * .7 + cost * .3;
    },

    _drawLive(view, state = this._stateForView(view)) {
      if (!this._ctx) return;
      const m = pixelRatio();
      const min = this._canvasMin;
      this._live = state;
      this._liveView = view;
      this._liveScale = state.k;
      cancelFrame(this._redrawRequest);
      this._ctx.setTransform(m * state.k, 0, 0, m * state.k, m * (state.x - min.x), m * (state.y - min.y));
      this._redrawBounds = null;
      this._redraw();
    },

    _redraw() {
      // Scaled strokes can extend past a layer's projected redraw bounds.
      if (this._live) this._redrawBounds = null;
      // Line weights follow the zoom being displayed, including mid-zoom frames.
      this._weightShare = weightShare(this._zoom + Math.log2(this._liveScale || 1));
      base._redraw.call(this);
    },

    // Leaflet's canvas fill/stroke, with pixel sizes held constant on screen
    // and line weights thinned when zoomed out.
    _fillStroke(ctx, layer) {
      const options = layer.options;
      const k = this._liveScale || 1;
      const share = this._weightShare ?? 1;
      if (options.fill) {
        ctx.globalAlpha = options.fillOpacity;
        ctx.fillStyle = options.fillColor || options.color;
        ctx.fill(options.fillRule || "evenodd");
      }
      if (options.stroke && options.weight !== 0) {
        if (ctx.setLineDash) {
          const dash = options._dashArray || [];
          ctx.setLineDash(k === 1 ? dash : dash.map((length) => length / k));
        }
        ctx.globalAlpha = options.opacity;
        ctx.lineWidth = Math.max(Math.min(options.weight, 1), options.weight * share) / k;
        ctx.strokeStyle = options.color;
        ctx.lineCap = options.lineCap;
        ctx.lineJoin = options.lineJoin;
        ctx.stroke();
      }
    },

    // Circle markers have pixel radii; L.Circle radii are geographic and scale.
    _updateCircle(layer) {
      const k = this._liveScale || 1;
      if (k === 1 || layer instanceof L.Circle) {
        base._updateCircle.call(this, layer);
        return;
      }
      if (!this._drawing || layer._empty()) return;
      const point = layer._point;
      this._ctx.beginPath();
      this._ctx.arc(point.x, point.y, Math.max(Math.round(layer._radius), 1) / k, 0, Math.PI * 2, false);
      this._fillStroke(this._ctx, layer);
    },
  });
})();
