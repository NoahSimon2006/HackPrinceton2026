# Hancock Terrace — detailed frontage demonstration

> Historical record. The planner now shows planted stormwater designs in **Results → Design** and **Explore in 3D**. The former demo address redirects to Stormwater. See the [desktop walkthrough](DEMO_WALKTHROUGH.md).

November 15, 2026. Built after Checkpoint 8 and the guided interface were merged and pushed as `4c29229`. This dedicated demo is local work on `codex/detailed-demo-scene`; it is separate from saved agent evaluations.

## The use case

**538 S Manhattan Place, Los Angeles — Hancock Terrace Apartments.** Turn a street frontage into two planted rain gardens while reserving a central access zone. CoStar identifies 28 apartments and three stories. Vexcel supplies actual building outlines and the mapped parcel. A verified property-linked Matterport exterior capture shows the building and surrounding block.

The two proposed cells are each **12 × 2.4 m**, totaling **57.6 m²**. An assumed **150 mm** effective ponding depth gives **8.64 m³** of gross temporary storage. Their coordinates are authored in the same local UTM frame as the source outlines. Both avoid the returned building geometry, with more than 5 m clearance, and leave a 19 m unplanted central gap. Their location is **outside the mapped parcel**: this is a public-frontage proposal requiring street-edge, access, utilities and right-of-way verification. The gap does not establish the exact position of an existing entrance.

## What to present

Open **http://127.0.0.1:8010/demo**. The main planner's Focus step also links to the detailed demo.

1. **Captured site:** open the real exterior capture and orbit the surrounding block. Say: “This is the real captured site context.” Close it to return to the authored design.
2. **Existing → Proposed:** use the same model camera to reveal the planted cells. Say: “Here is one frontage retrofit we can inspect in detail.” The Existing model is illustrative; the separate capture is the actual imagery.
3. **At eye level:** inspect planting, trees, curb openings and forebays. Select the numbered details to explain collection, storage and overflow. Facades, materials, tree placement and drainage components are conceptual.
4. **Make it rain:** start at **20 mm**. The what-if assumes **450 m²** of connected street area and runoff coefficient **0.9**. It produces **8.10 m³** of street runoff plus **1.152 m³** of rain directly onto the gardens. Reserving storage for direct rain leaves **7.488 m³** for street runoff, with **0.612 m³** beyond storage. The UI rounds these to 7.49 and 0.61. At **50 mm**, street runoff held is **5.76 m³**, with **14.49 m³** beyond storage. Greater rain directly on the treatment consumes more of the fixed storage.
5. **Below the surface:** inspect the explanatory ponding, soil, transition, aggregate and drain section. It describes possible components; no soil infiltration or water-quality benefit has been calculated.
6. Return to **The whole street** and use **Save image** to export the current view as a PNG. Keep the conceptual status in presentation captions.

This sequence takes roughly two minutes after the capture has loaded. The locally prepared model, metrics and rendering do not require a model API call. The optional exterior capture and reference photo require an internet connection.

## Why this is more informative

The demonstration combines actual source footprints with detailed architectural massing, facade elements, sidewalk joints, curbs, fences, palms, planted beds, shade trees, forebays and an overflow concept. Four camera presets support overview, eye-level, section and plan inspection. Rain animation and ponding level follow the same event-volume balance as the displayed values; the animation is illustrative, not a hydraulic simulation. Existing/Proposed retain the camera. The exported image contains the rendered model without the interface.

## Source and reconstruction boundaries

| Element | Basis |
| --- | --- |
| Property identity, 28 homes, three stories | Supplied CoStar property 4497305; reported parking types have no counts. |
| Main and surrounding building footprints | Vexcel collection `us-ca-losangeles_rf07-2026`, capture July 3, 2026; neighboring geometry clipped to the scene board. |
| Building heights | Main assumes 3.2 m per reported story; neighboring heights are illustrative. |
| Facades, palms, paving and street alignment | Authored visual reconstruction informed by the exterior reference, not surveyed geometry. |
| Garden placement and component dimensions | Authored public-frontage design assumptions, not an approved plan. |
| Connected area, coefficient and rain event | Explicit hypothetical scenario; actual contributing drainage remains unverified. |
| Matterport exterior | Verified model `SU76BQEbevu`, opened independently on request; actual exterior playback observed. |

No raw Gaussian splat, mesh or point-cloud export exists in the supplied local assets. A public Matterport tour is not an export or a registered scene. The [Matterport Bundle SDK](https://developers.matterport.com/bundle-sdk/) supports custom scene content with an SDK key and allowed domains; [downloadable model add-ons](https://developers.matterport.com/api/model/ordering-addons/) require the appropriate account access. No such credentials or exports were supplied, and this implementation does not scrape private model assets. The real capture is therefore a separate view, with its own camera. The authored model is not labeled a Gaussian reconstruction.

## Local preparation

From the repository root, using the existing environment and requirements:

```sh
.venv/bin/python scripts/prepare_hancock_demo.py
PORT=8010 .venv/bin/python server.py
```

The preparation command reuses validated local snapshots. `--refresh` explicitly retrieves one bounded 90 m Vexcel property extract and rereads the supplied CoStar kit. It validates the source/property association before replacing the private files. It makes no model call. The running web endpoint only reads local evidence; it does not silently fetch or fabricate missing source data.

Sponsor geometry and property evidence remain under ignored `private/demo-hancock/`, outside Git. The public endpoint exposes only the bounded, derived scene needed by the local viewer. A fresh checkout requires the same authorized source preparation. No saved planning project or existing evaluation is changed by opening this demo.

## Verification

Focused checks cover the real local source identity, 57.6 m² measured geometry, no overlap with displayed source buildings, missing-source handling, and dry/20 mm/50 mm event-volume balance. JavaScript syntax and unique DOM controls are checked. Browser review covers the rendered overview, eye-level and section views, camera-preserving Existing/Proposed switching, rainfall controls and real capture opening. No new agent call, traffic simulation or broad test-suite run is needed for this curated scene.

Final browser checks confirmed dry and 50 mm outputs, identical before/after camera state, embedded exterior playback, tour cleanup/focus, return navigation and a valid 1860 × 1268 PNG render. Image export opens a reviewable preview with a Download PNG link. The authored renderer pauses while the capture or image dialog is open. The full test suite was not rerun.
