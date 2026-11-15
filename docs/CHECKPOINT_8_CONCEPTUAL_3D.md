# Checkpoint 8 — conceptual 3D

**November 15, 2026 — implemented and verified on desktop.** Checkpoint 7 is committed and pushed to `main` as `ee07eb01cc82f364d0d9a10c231d0ccdcbffcd2d`. This checkpoint adds a local conceptual viewer for the exact design selected on the 2D map. Observed browser checks and harness-only checks are separated below; the existing traffic release gaps remain explicit.

## Implemented behavior

Choose **Explore in 3D** on a published footprint. The viewer opens on request and shows **Existing** and **Proposed** from one shared camera. Orbit, zoom, pan, top view, reset and surroundings controls support desktop inspection. A saved or earlier design keeps its own revision, hash, metrics and original save time. A rejected alternative retains its rejection label. A comparison without a selected footprint does not silently choose a 3D layout.

The scene source comes from the validated publication actually displayed on the map, including internal alternatives and read-only history. The server resolves that design from its canonical saved project using project, revision, input hash and geometry identity. It rejects mismatches and development fixtures. Opening 3D does not rerun an agent, simulation or environmental calculation.

A different publication, site or workflow closes and invalidates the prior scene. Input edits or a new investigation invalidate it immediately; the retained design can be reopened as a labeled saved reference. Closing disposes the renderer, geometry, controls and pending work, and restores focus. Late responses cannot reopen an old view. WebGL failure is contained in the optional viewer, with retry and the 2D design still available.

## Geometry and source basis

The backend uses the existing Shapely/PyProj geometry stack to transform WGS84 display geometry into **EPSG:32611 meters**, then subtracts a stable project origin. Polygon holes and MultiPolygons are preserved. Scene footprint area is checked against the authoritative proposal measurement; the displayed performance metrics are copied from that same saved design. Existing/Proposed use the same origin, scene base and camera pose.

Matching parcel and building outlines come only from the source evidence attached to that saved evaluation. Historical records without matching context omit surrounding outlines; they do not borrow the latest result's geometry. Nearby context is bounded and clipped for the scene. The sources and coordinate origin remain inspectable.

The view makes its vertical assumptions explicit:

- Building footprints are sourced where available; their **6 m heights are illustrative**.
- Stormwater depth represents the proposal's **assumed effective ponding depth**, not surveyed ground or an excavation design.
- Traffic surfaces use an **illustrative 0.15 m display thickness**, not a proposed construction specification.
- The ground is a neutral reference plane. Surveyed terrain, full road geometry, materials and verified building heights are not reconstructed.

Three.js **0.187.0** and OrbitControls are pinned and vendored locally with the MIT license. The official npm package integrity was checked; runtime rendering requires no CDN or build-system migration. The renderer uses a single orthographic camera and renders on changes. The [Three.js extrusion](https://threejs.org/docs/pages/ExtrudeGeometry.html), [orbit controls](https://threejs.org/docs/pages/OrbitControls.html) and [orthographic camera](https://threejs.org/docs/pages/OrthographicCamera.html) documentation describe these primitives.

## Verification

| Check | Observed result | Scope |
| --- | --- | --- |
| Current stormwater concept | Project `2f06f0bcd94744b3a5147961eefb9e07`, revision 5 (`9f834e0f`), opened with its 20 m² footprint, 3 m³ storage and matching Vexcel building context. | Actual browser scene from the saved Checkpoint 7 design; no fresh model call. |
| Shared comparison camera | Existing/Proposed preserved exactly equal camera state recorded on the rendered canvas; top view was inspected. | Actual browser check. |
| Close and focus | Escape closed the dialog, left zero scene canvases and restored focus to the opener. | Actual browser check. |
| Earlier revision | Revision 2 opened as an earlier 40 m² design and omitted unmatched surrounding source context. | Actual browser history check. |
| Rejected traffic layout | Main/1st revision 4 (`c7cd6a64`), `wb-bike-80`, opened with 64 m², its original 09:23:23 UTC save time, coral geometry and a persistent Tested, rejected label. | Actual browser scene; no fresh traffic evaluation. |
| Camera after user rotation | A keyboard-activated rotation followed by Existing/Proposed retained exactly equal rendered camera state. | Actual browser check on the traffic scene. |
| Final visual review | The default oblique view clearly shows the 20 m² planting strip; translucent building masses retain the illustrative 6 m height. Grid spacing and north direction are visible. | Actual desktop screenshot; one active canvas and no console errors/warnings were observed. |
| Independent of tours | The stormwater project has no selected property association, and the scene opened with zero Matterport iframes. | Actual saved-project and browser check. |
| Narrow containment | At a 390 × 844 viewport, document/body width was 390 px and dialog content/canvas width was 376 px, without horizontal overflow. Desktop size was restored afterward. | Limited layout check, not a complete mobile journey. |
| Read-only scene API | The real scene endpoint returned HTTP 200 with `no-store`, 20 m² geometry and authoritative area, matched Vexcel collection/date, and the unchanged project version 5. | Local API check; source requests, model calls and simulations were not repeated. |
| Projected scene builder | Nine focused Python tests passed for metric identity, holes, MultiPolygons, stable origins, bounded context, historical isolation and rejection handling. | Deterministic tests; no provider calls. |
| Renderer geometry | The actual Three.js triangulation preserved holes, MultiPolygons, meter scale, north orientation and assumed depth. | Focused renderer test; it does not substitute for the browser's WebGL visual check. |
| Publication and lifecycle | Concept-scene, proposal and planner-hydrology controller checks passed. They cover identity, publication/history, late results, stale inputs, cleanup, focus and WebGL failure. | Focused harnesses, not a full live fault matrix. |

The focused scope is nine Python tests and four JavaScript files: `concept-scene-renderer.mjs`, `concept-scene-controller.mjs`, `proposal-controller.mjs` and `planner-hydrology.mjs`. The full suite was not rerun. Checkpoint 8 made no new model calls and no new traffic simulation runs.

## Acceptance boundary

Current and earlier stormwater views, rejected traffic geometry, mode switching, camera controls, cleanup/focus and final desktop visuals were observed in the browser. Selecting the earlier revision rebuilt the scene with its own 40 m² footprint and source availability; returning to the current project rebuilt the 20 m² scene. Input-edit invalidation, in-flight publication races and graphics failures were verified through focused controller harnesses rather than additional live agent runs. No full live fault matrix or full mobile journey is claimed.

## Scope and remaining gaps

This is a conceptual reconstruction of the agent's saved 2D design. It is not a Matterport scan, Gaussian splat or registered scan overlay. The independent Matterport property-tour viewer remains unchanged; its Proposed view stays unavailable without verified scan coverage and alignment. A site without a tour can still use conceptual 3D.

Checkpoint 8 does not establish an eligible traffic recommendation or a usable positive CoStar access record at Main/1st. Those remain the documented traffic acceptance gaps. Stormwater's existing sponsor contributions and the existing evaluation assumptions remain intact. No new 3D appearance should be presented as additional evidence of environmental benefit or construction feasibility.

## Review workspace

Branch: `codex/checkpoint-8-conceptual-3d`.

Checkout: `/Users/Derek/Documents/Codex/2026-11-14/https-github-com-noahsimon2006-hackprinceton2026-https-2/work/checkpoint-7-core-demo`.

The directory retains its earlier Checkpoint 7 name, but the active branch contains Checkpoint 8. The review server is <http://127.0.0.1:8010/#stormwater>, using the independent local project database with the prepared studies. Concurrent Desktop interface/guide work is preserved. See the [demo walkthrough](DEMO_WALKTHROUGH.md) for the presentation sequence.
