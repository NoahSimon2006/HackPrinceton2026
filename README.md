# Sustainability Map

A local planning workspace for Los Angeles, using a Python server, bundled Leaflet, Vexcel aerial imagery and CoStar site evidence. **Traffic & Emissions** opens with current surface-street speeds and connected slow approaches. **Stormwater** opens with terrain screening across the western pilot, with rainfall, drainage, property-use and sampled parcel/building layers.

**Current work: [Checkpoint 8 conceptual 3D](docs/CHECKPOINT_8_CONCEPTUAL_3D.md), implemented and desktop-verified.** Checkpoint 7 is pushed to `main` as `ee07eb0`. The new **Explore in 3D** viewer reconstructs the selected 2D footprint in meters, with matching source context when available and one camera for Existing/Proposed. Current and historical stormwater scenes and a rejected traffic layout have been checked in the browser; focused harnesses verify stale-input and late-publication invalidation. Opening a scene makes no new agent or simulation call. Main/1st still has no eligible traffic recommendation or usable CoStar access record. Read the [handoff](docs/CONVERSATION_HANDOFF.md), [demo walkthrough](docs/DEMO_WALKTHROUGH.md) and [approved plan](docs/NEXT_IMPLEMENTATION_PLAN.md).

**Detailed demonstration:** Open `/demo` for the [Hancock Terrace frontage study](docs/DEMO_HANCOCK_FRONTAGE.md): two planted rain gardens, an interactive event-volume scenario, a layered section and a genuine site-matched exterior capture. This curated scene is separate from saved agent evaluations. Prepare the local source snapshot with `scripts/prepare_hancock_demo.py`; sponsor geometry remains ignored.

**Traffic keeps each evaluated design.** The agent can revise named alternatives while preserving unspecified parameters and constraints. New evaluations apply hard gates, then modeled CO₂ priority, with feasibility/disruption used only within a disclosed variability tie screen. Readiness remains separate. Inspect rejected footprints and earlier evaluations, including after a failed continuation. Live speeds are discovery evidence; quantitative comparisons require a uniquely associated verified historical turning sheet and valid network inputs.

**Stormwater produces a revisable map concept.** Vexcel outlines and CoStar operating context shape a conditional footprint with up to three internal alternatives. Ask for a different size, depth, shape or placement; the project preserves constraints and earlier design revisions. Storage can be calculated while drainage remains unknown. Explicit runoff what-if controls combine marked source areas, a coefficient and a named rainfall event, reserving storage for direct rain first. Environmental screening, practical constraints and readiness stay separate.

**3D property tours are optional.** On the assistant's **Site** step, open tours linked to the selected property. Interior, exterior, amenity and unspecified tours are included when their property/model association is validated. Conflicting or unmatched links remain excluded with a reason. No tour changes the active property, and no scan is required for a 2D draft. Conceptual 3D is available independently from the published footprint; Matterport scans are not registered to the design. Historical [release acceptance](docs/CHECKPOINT_6.md), [traffic method](docs/CHECKPOINT_4.md) and [viewer implementation](docs/CHECKPOINT_7.md) reports describe earlier builds, not the current checkpoint numbering. A supported eligible traffic winner and final release acceptance remain open.

Earlier review records: [Checkpoints 0–1](docs/CHECKPOINTS_0_1.md), [Checkpoint 2](docs/CHECKPOINT_2.md).

The [codebase audit](docs/CODEBASE_AUDIT.md) records correctness fixes and remaining data/acceptance limits. The [road-network verification](docs/ROAD_NETWORK_VERIFICATION.md) records the refreshed OSM extract, corrected static turn permissions and nine real-count simulation runs. Unsupported restrictions in a study block comparison; complete real-world turn coverage is not claimed. Known counts from only some CoStar parking/loading categories are no longer presented as complete totals.

## Run locally

Keep `VEXCEL_API_KEY`, `GROK_API_KEY`, `TOMTOM_API_KEY` and the absolute `COSTAR_KIT_DIR` in the ignored `.env`. The CoStar kit needs `data/commercial-property.jsonl` and `schemas/enums.json`; the property-tour viewer also requires `commercial-properties.csv` to validate its property-to-model association. Credentials and raw sponsor data stay local.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-discovery.txt -r requirements-sim.txt
PORT=8003 .venv/bin/python server.py
```

Open <http://127.0.0.1:8003>. Use a free port or stop the server you started before restarting. After backend changes, restart Python and reload the page. Local JavaScript/CSS revalidate on reload. Vexcel imagery and optional Esri labels require network access. Discovery reads local prebuilt source snapshots; missing snapshots produce an explicit unavailable state, never substitute data. A Grok key is needed for agent scouting and site analysis. Traffic comparisons also require the local OSM network, verified turning-sheet discovery data, and the original official CARB export at `sim/sources/emfac2025-la-2026.csv`. The new readiness report records the restored inputs, hashes and remaining source gaps.

## Build discovery data

Terrain discovery needs `requirements-discovery.txt` and its source-validated cached raster. The base map and draft workflow can run independently of the broader terrain build.

The existing workspace has the source snapshots under ignored `private/discovery/` and the OSM network under ignored `sim/`. To rebuild from cached sources:

```sh
.venv/bin/python -m pip install -r requirements-discovery.txt
.venv/bin/python scripts/build_discovery.py --sponsors
```

Use `--refresh` to download public sources again. Use `--workflow street` or `--workflow water` to rebuild one inventory. `--sponsors` permits the three bounded Vexcel site samples; cached samples are reused unless `--refresh` is also set. Current TomTom flow is fetched separately at runtime and is not archived. The build is deterministic given its inputs, apart from build timestamp/version. It makes no agent calls and runs no traffic simulation. It records source hashes, source dates where supplied, retrieval timestamps and method limitations. Details, exclusions and spot checks are in [Checkpoint 3](docs/CHECKPOINT_3.md).

For a fresh checkout without `sim/dtla.net.xml`, prepare the OSM topology first. This only converts sourced road geometry and names; it does not generate traffic demand or run SUMO:

```sh
.venv/bin/python -m pip install -r requirements-sim.txt
.venv/bin/python scripts/fetch_osm.py
.venv/bin/python scripts/build_road_network.py
.venv/bin/python scripts/build_discovery.py --sponsors
```

A different OSM extract may produce different matches; network hashes identify the exact inputs. Generated network signal settings are not treated as observed signal plans. Public raw downloads and generated discovery artifacts stay local rather than being redistributed in Git. Runtime rendering does not import Rasterio or execute the build.

The network builder keeps original OSM identifiers, checks the converted connections, corrects verified static restrictions for modeled vehicle classes, and checks again before publishing. `sim/network-build.json` binds the source and network hashes; manual network replacement requires rebuilding this provenance and discovery. Conditional, via-way and malformed restrictions are reported separately. A study containing unresolved represented restrictions remains unavailable, including after lane changes. Current available counted sites are Main/1st and Beaudry/1st; Hill/1st and Beaudry/Temple need conditional-rule support. To rerun the Main/1st nine-run verification:

```sh
.venv/bin/python scripts/verify_traffic_network.py --output-dir private/traffic-network-verification
```

## Explore and investigate

1. The assistant window beside the map walks through five steps, one at a time: **Focus**, **Place**, **Site**, **Brief** and **Results**. Its footer always names the next action; **Back**, the numbered steps and **Map layers** (title bar) move between views without losing work. Start on **Focus** by choosing **Traffic & Emissions** or **Stormwater**. Existing `/#urban-planners`, `/#intersections` and `/#stormwater` links remain useful.
2. Choose a discovery layer on the map. Click a feature or use **Browse mapped features** to inspect its value, units and date/event. **Source, method & limits** on the **Site** step includes provenance. **View data area** returns to that mode's data area (Stormwater also has **View Los Angeles**). **Collapse** folds the panel; **No overlay** removes the overlay. **Layer details** holds feature counts, full timestamps and method limits. On narrow screens, selecting a feature collapses controls to leave the map usable.
3. On **Place**, scout an area with the agent, pick a spot (property search, map click or map center) or open a saved project. Selecting a site or a discovery feature opens the **Site** step and seeds a site brief without calling the agent. Stormwater site selection also loads the existing county subbasin/rainfall lookups independently, with retry for source failure.
4. On **Brief**, choose **Analyze site** to run one lead Deep Agent with concurrent site-evidence and domain specialists. The assistant moves to **Results**, where **Agent activity** follows specialist assignments, skill reads, files and source results. Use **Results → Project** to inspect the plan and reports; **Place → Saved project** and **Continue project** restore earlier work. Changing sites/modes cancels the followed run; a changed discovery selection also cancels the old analysis, including when two features share coordinates.
5. Under **Results → Evidence**, inspect returned outlines, detections, frontages and locally measured facts. Drawings and manually edited rainfall remain distinct from source values. They do not constitute verified drainage, current traffic, a physical proposal or a benefit calculation. Editing inputs marks prior results stale.
6. For keyboard site selection, focus the map, pan with arrow keys, then choose **Use map center as site**. Under **Brief → Map markings**, add points at the map center or edit each point's labeled coordinates, then save the marking using the map controls. Invalid or uncovered points cannot be saved.
7. On the **Site** step under **3D property tours**, choose **View tours**. All validated tours for the selected property are available in a selector with a tour count. Repeated attachments for one model are grouped; missing captions/dates do not hide a valid tour. A missing or conflicting association is explained. Matterport loads only on request, with retry, slow-loading guidance and an external link. A loaded iframe alone does not establish that a tour is playable. The tour viewer is separate from conceptual 3D.
8. In Stormwater, choose a researched location or a supported direct site and request a concept with no drawings. Inspect its source-informed siting decisions and internal alternatives. Revise size/form/depth/placement through the brief, or set explicit controls under **Brief → Design settings**; a named rainfall event goes under **Brief → Rainfall scenario**. Keep-clear and runoff-source markings are under **Brief → Map markings**. A runoff calculation requires an explicit assumed connection, coefficient, source marking and event; direct rain reserves storage first. **Earlier design revisions** (under **Results → Design**) restores each saved footprint with its own metrics. A tour is not required.

9. Under **Results → Design**, on a published footprint, choose **Explore in 3D**. Switch **Existing / Proposed** without changing the camera, use Top view or Reset view, and inspect Scene basis for sourced outlines and illustrative heights. History and rejected-layout inspections keep their own identity. Changed inputs or a new publication invalidate the open scene. A property tour is not required.

Project inputs, constraints and permitted artifacts persist locally in ignored SQLite storage under `private/agent-workspace/`. Reloads and server restarts retain them. Live traffic inspection is transient and refreshed on continuation, not archived. The labeled **Development preview** uses test geometry and appears under **Results → Project** only when the page is opened with `?dev`. At verified turning-count sites, expand a traffic alternative and choose **Show footprint on map** to inspect the tested layout and its verdict. Stormwater terrain screening uses the expanded four-tile, native 1 m USGS mosaic. Current traffic expires after at most one minute and refreshes only on request.

## Measurement and sharing boundaries

Geometry is validated with Shapely and measured locally in UTM zone 11N. Invalid/out-of-scope shapes are excluded, polygon holes are preserved, and overlapping footprints are unioned before measurement. Detection boxes are candidates, not measured crossings or impervious surfaces. CoStar gross floor area is distinct from mapped building footprint area. Missing data is not zero.

xAI receives the planner's text, approved scalar measurements, sourced rainfall/watershed facts and allowlisted CoStar fields: use, units, reported parking/loading counts and gross floor area. Discovery selections are resolved from a versioned local reference and become a sourced scalar fact. Exact site coordinates, raw geometry, names/addresses, vacancy, raw source records and credentials are not automatically included in model messages. Source text is treated as data. LangSmith tracing remains disabled.

Reviews must cite returned facts; local validation rejects unknown references and unsupported numeric claims. This does not establish physical feasibility. A terrain path is an inference from a bare-earth raster, rainfall is a design depth, and county catchments are regional context. None is a flood-depth map or a verified inlet connection.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -q
node tests/app-controller.mjs
node tests/discovery-controller.mjs
node tests/planner-hydrology.mjs
node tests/analysis-stream.mjs
node tests/proposal-controller.mjs
node tests/site-view-controller.mjs
# Optional local catalog audit (no provider requests or raw records in output):
.venv/bin/python scripts/audit_site_views.py
node tests/projects.mjs
node tests/scouting.mjs
node tests/guide-controller.mjs
```

Install `requirements-discovery.txt` for terrain/builder tests. Most tests use explicit test fixtures and make no provider calls. Two local spot checks use downloaded public source artifacts when available; they report skipped if those files are absent. See the checkpoint reports for live verification and remaining limits.

## Archived simulation

Archived commands require explicit opt-in: `scripts/run_pilot.py --allow-illustrative` writes random-demand runs only under ignored `sim/archived-pilot/`; `scripts/build_emissions.py --allow-volume-assumptions` builds the separate archived extrapolation artifact. Neither refreshes current source-only discovery or the real turning-count comparison.

`public/data/emissions.json`, `scripts/run_pilot.py` and `scripts/build_emissions.py` preserve the earlier illustrative SUMO/EMFAC work for reference. It used random origin–destination demand, generated signals, road-class volume assumptions and assumed hourly shares. Its historical-count interpretation is not the source-only discovery method, and its predictions are excluded from the current UI and agent evidence.

The exporter can now retain stopped/time-loss vehicle-seconds, normalized by sampled vehicle-seconds, plus interval and simulated volume context for both periods. This is export preparation only. Checkpoint 3 did not rerun the simulation or rebuild the archived artifact. The Checkpoint 4 comparison uses separately verified manual turning sheets and labels generated signal timing explicitly. Historical automated totals alone still cannot support a comparison.
