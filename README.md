# Sustainability Map

A local planning workspace for Los Angeles, using a Python server, bundled Leaflet, Vexcel aerial imagery and CoStar site evidence. **Traffic & Emissions** opens with dated historical traffic counts. **Stormwater** opens with terrain screening around Kipling Apartments, with optional county rainfall and drainage-context layers.

**Stormwater starts with a map draft.** Select a supported site and ask the agent for a rain garden. The draft uses mapped outlines and avoids known access constraints. It labels ponding depth as a design assumption and leaves external runoff capture unassessed until a contributing area and coefficient support a what-if estimate. **Compare your own placements** opens the optional [Checkpoint 5 storage comparison](docs/CHECKPOINT_5.md).

**[Checkpoint 6 core release acceptance remains blocked](docs/CHECKPOINT_6.md).** That report records the earlier build, before Checkpoint 5 implementation. The new stormwater implementation needs a confirmed real-site design review before release acceptance. Traffic comparisons use official historical turning counts, approved generated signal timing and strict total-CO₂/throughput/regression gates; a supported successful design demonstration and final narrow-screen checks remain pending. The archived assumed-demand emissions layer remains disabled. See [Checkpoint 4](docs/CHECKPOINT_4.md) for the traffic method and source limits. The [Checkpoint 7 existing-site walkthrough](docs/CHECKPOINT_7.md) remains available; Proposed 3D is still disabled until design alignment is verified.

Earlier review records: [Checkpoints 0–1](docs/CHECKPOINTS_0_1.md), [Checkpoint 2](docs/CHECKPOINT_2.md).

The [codebase audit](docs/CODEBASE_AUDIT.md) records correctness fixes and remaining data/acceptance limits. The [road-network verification](docs/ROAD_NETWORK_VERIFICATION.md) records the refreshed OSM extract, corrected static turn permissions and nine real-count simulation runs. Unsupported restrictions in a study block comparison; complete real-world turn coverage is not claimed. Known counts from only some CoStar parking/loading categories are no longer presented as complete totals.

## Run locally

Keep `VEXCEL_API_KEY`, `GROK_API_KEY` and the absolute `COSTAR_KIT_DIR` in the ignored `.env`. The CoStar kit needs `data/commercial-property.jsonl` and `schemas/enums.json`; the exterior walkthrough also requires `commercial-properties.csv` to validate its property-to-model association. Credentials and raw sponsor data stay local.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PORT=8001 .venv/bin/python server.py
```

Open <http://127.0.0.1:8001>. After backend changes, restart the Python server and reload the page. Local JavaScript/CSS revalidate on reload. Vexcel imagery and optional Esri labels require network access. Discovery reads local prebuilt source snapshots; missing snapshots produce an explicit unavailable state, never substitute data. A Grok key is needed only when **Analyze site** is selected. Traffic comparisons also require `requirements-sim.txt`, the local OSM network, verified turning-sheet discovery data, and the official CARB export described in the Checkpoint 4 report.

## Build discovery data

The optional comparison needs `requirements-discovery.txt` and the source-validated cached Kipling terrain raster to publish a conditional preference. The base map and draft workflow can run without the terrain dependencies.

The existing workspace has the source snapshots under ignored `private/discovery/` and the OSM network under ignored `sim/`. To rebuild from cached sources:

```sh
.venv/bin/python -m pip install -r requirements-discovery.txt
.venv/bin/python scripts/build_discovery.py
```

Use `--refresh` to download public sources again. The build is deterministic given its inputs, apart from build timestamp/version. It makes no agent calls and runs no traffic simulation. It records source hashes, source dates where supplied, retrieval timestamps and method limitations. Details, exclusions and spot checks are in [Checkpoint 3](docs/CHECKPOINT_3.md).

For a fresh checkout without `sim/dtla.net.xml`, prepare the OSM topology first. This only converts sourced road geometry and names; it does not generate traffic demand or run SUMO:

```sh
.venv/bin/python -m pip install -r requirements-sim.txt
.venv/bin/python scripts/fetch_osm.py
.venv/bin/python scripts/build_road_network.py
.venv/bin/python scripts/build_discovery.py
```

A different OSM extract may produce different matches; network hashes identify the exact inputs. Generated network signal settings are not treated as observed signal plans. Public raw downloads and generated discovery artifacts stay local rather than being redistributed in Git. Runtime rendering does not import Rasterio or execute the build.

The network builder keeps original OSM identifiers, checks the converted connections, corrects verified static restrictions for modeled vehicle classes, and checks again before publishing. `sim/network-build.json` binds the source and network hashes; manual network replacement requires rebuilding this provenance and discovery. Conditional, via-way and malformed restrictions are reported separately. A study containing unresolved represented restrictions remains unavailable, including after lane changes. Current available counted sites are Main/1st and Beaudry/1st; Hill/1st and Beaudry/Temple need conditional-rule support. To rerun the Main/1st nine-run verification:

```sh
.venv/bin/python scripts/verify_traffic_network.py --output-dir private/traffic-network-verification
```

## Explore and investigate

1. Use **Traffic & Emissions** or **Stormwater** at the top of the sidebar. Existing `/#urban-planners`, `/#intersections` and `/#stormwater` links remain useful.
2. Choose a discovery layer on the map. Click a feature or use **Browse mapped features** to inspect its value, units and date/event. **Source, method & limits** in the sidebar includes provenance. **View pilot** returns to that mode's pilot. **Hide layers** collapses the controls; **Hide discovery layer** removes the overlay. On narrow screens, selecting a feature collapses controls to leave the map usable.
3. Selection seeds a site brief without calling the agent. Property search and direct map selection remain available. Stormwater site selection also loads the existing county subbasin/rainfall lookups independently, with retry for source failure.
4. Choose **Analyze site** to run one lead Deep Agent with concurrent site-evidence and domain specialists. Expand **Agent activity** to follow actual tool results and inspect cited facts. Changing sites/modes cancels the followed run; a changed discovery selection also cancels the old analysis, including when two features share coordinates.
5. Under **Site evidence & adjustments**, inspect returned outlines, detections, frontages and locally measured facts. Drawings and manually edited rainfall remain distinct from source values. They do not constitute verified drainage, current traffic, a physical proposal or a benefit calculation. Editing inputs marks prior results stale.
6. For keyboard site selection, focus the map, pan with arrow keys, then choose **Use map center as site**. Under **Adjust or add map markings**, add points at the map center or edit each point's labeled coordinates, then save the marking using the map controls. Invalid or uncovered points cannot be saved.
7. For the approved exterior demo, choose **Open existing view** under **Exterior walkthrough · 510 E Olympic Blvd**, then press the tour's Play control. Opening selects that property on the map. The existing Matterport tour loads on demand and needs network access, but no Grok call or SDK key. Close returns to the map; **Retry viewer** and **Open Matterport in a new tab** are available if the embedded provider fails. **Proposed** is disabled because there is no supported design registered to this scan.

8. In Stormwater, select the **Normandie** property and choose **Analyze site** to screen a draft. Revise it by describing an access constraint or marking a keep-clear area. For an optional detailed comparison at **Kipling Apartments**, open **Compare your own placements**, mark the contributing surface and two or three treatments, and supply the depth, coefficient, input basis and confirmations. **Update comparison** runs fresh source analysis and an event storage balance. Changing the rainfall or markings makes previous results stale. Green shows the conditional treatment footprint and cyan shows the contributing surface. Both workflows reserve capacity for direct rainfall before applying runoff from outside the treatment.

All site work is held for the current page session. The labeled **Development preview** uses test geometry. At verified turning-count sites, expand a traffic alternative and choose **Show footprint on map** to inspect the tested layout and its verdict. The optional stormwater terrain screening currently uses the cached Kipling 1 m USGS raster.

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
```

Install `requirements-discovery.txt` for terrain/builder tests. Most tests use explicit test fixtures and make no provider calls. Two local spot checks use downloaded public source artifacts when available; they report skipped if those files are absent. See the checkpoint reports for live verification and remaining limits.

## Archived simulation

Archived commands require explicit opt-in: `scripts/run_pilot.py --allow-illustrative` writes random-demand runs only under ignored `sim/archived-pilot/`; `scripts/build_emissions.py --allow-volume-assumptions` builds the separate archived extrapolation artifact. Neither refreshes current source-only discovery or the real turning-count comparison.

`public/data/emissions.json`, `scripts/run_pilot.py` and `scripts/build_emissions.py` preserve the earlier illustrative SUMO/EMFAC work for reference. It used random origin–destination demand, generated signals, road-class volume assumptions and assumed hourly shares. Its historical-count interpretation is not the source-only discovery method, and its predictions are excluded from the current UI and agent evidence.

The exporter can now retain stopped/time-loss vehicle-seconds, normalized by sampled vehicle-seconds, plus interval and simulated volume context for both periods. This is export preparation only. Checkpoint 3 did not rerun the simulation or rebuild the archived artifact. The Checkpoint 4 comparison uses separately verified manual turning sheets and labels generated signal timing explicitly. Historical automated totals alone still cannot support a comparison.
