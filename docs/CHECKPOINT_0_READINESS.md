# Checkpoint 0 — baseline and source readiness

Verified November 14, 2026, America/New_York (some artifact timestamps are November 15 UTC).

The Desktop checkout is restored and runnable. Python and JavaScript baselines pass, the current OSM network passes the supported restriction checks, and sponsor access works at selected properties. The follow-up source check verified TomTom access at two LA surface-street locations and to an Orbis flow tile. The original HERE access token was rejected; a later replacement API key succeeded. This establishes bounded live-source access, not an implemented traffic adapter or completion of later product checkpoints.

**Historical checkpoint snapshot:** This report records Checkpoint 0 on `codex/checkpoint-0-readiness`, based on verified `origin/main` at `99333b30c8fabd46b78a9b9fb4db38f497e520f7`. No commit, push or merge was performed. Checkpoint 1 subsequently completed on `codex/checkpoint-1-site-identity`, preserving these changes. Read the [Checkpoint 1 report](CHECKPOINT_1_WORKFLOW.md) for current behavior and checks; references below to later work describe the boundary at the end of Checkpoint 0.

## Restored local baseline

- Correct repository: `/Users/Derek/Desktop/HackPrinceton26`, matching the requested GitHub remote. This is the repository root on this machine; the old nested-checkout instructions describe another environment.
- Installed all three pinned requirement sets into the existing `.venv`. `pip check` reports no broken requirements. Versions include Deep Agents 0.7.38, langchain-xai 1.3.0, Shapely 2.2.0, Rasterio 1.5.2, pypdf 6.3.0 and SUMO/sumolib 1.28.0.
- Set the absolute `COSTAR_KIT_DIR=/Users/Derek/Desktop/costar-hackathon-kit` in the ignored `.env`, preserving existing credentials. The environment file has mode `0600`.
- Restored 67 cached discovery files, including source JSON, the USGS raster, official count PDFs and prior missing-sheet markers, from `/Users/Derek/Documents/ChatGPT/HackPrinceton26/private/discovery`. Preserved file modification times; retained hashes in a private restoration receipt. The other checkout was not modified.
- Recovered the user's official CARB EMFAC2025 Los Angeles 2026 annual export from Downloads and copied it to `sim/sources/emfac2025-la-2026.csv`. Its contents pass the existing fleet parser; there is no invented replacement fleet.
- Downloaded a fresh bounded OSM extract, rebuilt the road network and its verification manifest, then rebuilt discovery against that network. Restored public caches retain their original source ages; rebuilding does not make historical counts current.
- Started the updated server at **http://127.0.0.1:8003/**. Its listener's working directory was verified as the Desktop checkout. Other pre-existing servers were left alone.

Credentials, sponsor responses, source assets, raw audits and simulation outputs remain ignored under `.env`, `private/` and `sim/`. No new model calls or paid subscriptions were introduced during this checkpoint.

## Startup defect fixed

The live Vexcel coverage response contained 61 collection polygons. One polygon, from `us-ca-hollywood-2019`, had a self-intersecting ring. The previous all-or-nothing validation returned HTTP 503 and prevented normal map startup despite 60 valid source polygons.

The server now excludes malformed individual coverage records, preserves valid geometry exactly, and reports `status: partial` with `excludedFeatures`. It still fails when no usable coverage remains. It does not repair polygons, enlarge coverage, or substitute an invented boundary. The map status discloses the exclusion, including after a property-layer refresh.

The live endpoint now returns HTTP 200 with 60 valid polygons and one excluded record. Browser inspection confirmed aerial tiles, the historical-count overlay and the partial-coverage status. Added regression coverage checks mixed valid/invalid inputs, an all-invalid result, cached results, warning persistence and navigation outside retained source coverage.

Application changes are limited to this baseline startup fix. Site resolution, the manual placement workflow, the agent architecture and Matterport selection behavior remain work for later checkpoints.

## Verification results

| Check | Result | What it establishes |
| --- | --- | --- |
| Python suite | **133 tests passed, zero skips** | Includes real cached DEM/count spot checks and the new coverage regression. Before restoring source assets, four source-dependent checks skipped; all now run. |
| JavaScript | **6 test files passed, zero failures** | Existing state, cancellation, revisions, discovery and viewer checks, plus partial-coverage behavior. |
| Dependency consistency | Pass | `pip check` found no broken requirements. |
| Network/SUMO smoke | **9 real-count runs passed** | Baseline and two layouts, paired seeds 11/23/37; exact counted movements, cohort accounting, positive emissions and zero teleports. |
| Local HTTP | Pass | Page, CoStar search, linked site-view descriptor, both discovery inventories, rainfall, watershed and repaired imagery coverage. |
| Browser startup | Pass | Aerial map and 76 historical count features render. This is a startup check, not final desktop/mobile release acceptance. |
| Normandie deterministic draft | Pass | Fresh sponsor/county evidence produces a 12.546 m² footprint and 1.882 m³ gross storage at 0.15 m assumed depth. |
| TomTom live requests | **3 HTTP 200 responses** | Two Flow Segment Data v4 probes near Main/1st and Beaudry/1st, plus one Orbis v2 vector flow tile. Tile decoding and application integration remain unimplemented. |
| Original HERE access-token requests | **HTTP 401** | Rejected using Bearer authentication and when treated as an API key. Historical result; the replacement key below succeeded. |
| Later HERE API-key follow-up | **HTTP 200** | A bounded Traffic v7 flow request returned 60 records. The key is configured locally; application integration remains Checkpoint 2A. |

The Normandie check directly exercised the existing local source adapters and design tool. It was not a new end-to-end LLM run. It retained CoStar property type, unit count and reported building floor area, used a containing Vexcel parcel/building and landscape candidates, and used approximately 1.00 in county event rainfall. Direct rainfall on the draft was 0.319 m³. External runoff, capture and overflow remain unassessed without a contributing area and runoff coefficient. Floor area was not substituted for a roof or drainage area.

The SUMO smoke produced **no eligible winning design**. Both tested Main/1st layouts failed operational gates; the script also intentionally leaves sponsor/access checks unassessed. Passing the smoke check verifies the machinery and accounting, not environmental improvement or construction feasibility.

## CoStar inventory and useful applications

The current map extent contains **1,581 property records**, including 1,417 multifamily records. Counts below describe this local snapshot, not completeness of the real-world property market.

| Available information | Populated records | Planning use and limit |
| --- | ---: | --- |
| Property type | 1,581 | Identify surrounding uses and operational context; not observed trip generation. |
| Apartment unit count | 1,417 | Describe reported residential scale; not population or occupancy. |
| Gross building floor area | 1,578 | Building scale and land-use context; not roof area or impervious area. |
| Building stories | 1,572 | Help describe scale and future simple massing; do not invent measured height. |
| Reported building height | 128 | Potential massing input after units/site association checks. |
| Lot size | 1,574 | Size plausibility check and property context. 1,370 use acres and 204 square feet; conversion must honor the source unit. |
| Zoning label / parcel references | 1,566 each | Join candidates for authoritative parcel/zoning investigation. Snapshot labels are not current permission or proof of ownership. |
| Complete reported parking totals | 342 | Operational/disruption context. Although 1,245 records contain parking entries, incomplete category counts must remain unknown. |
| Complete loading-dock totals in the current adapter | 1 | Sparse; cannot support general claims that loading is absent. |
| Usable frontage geometry | 17 lines across 12 properties | Potential access constraints, after spatial association. There are 36 raw records across 22 properties; 19 have missing/invalid line geometry. |
| Nonempty LEED certification lists | 23 | Reported building certification context; no basis for stormwater infiltration, soils or flood risk. |

The apparently widespread `environmental` object is mostly an empty container. Its populated information here is LEED certification, not a hidden drainage or flood dataset. Lot size, parcel IDs, stories and related fields are not yet exposed through the current five-field site-fact adapter. Expanding the curated adapter belongs with the planned site-context work.

## Vexcel capability and site checks

Authenticated MCP initialization and tool listing succeeded against the official endpoint, advertising 33 tools. The account profile lists property/structure, imagery, detection, embeddings and DSM/DTM services. A successful list/profile is distinct from successful site extraction. The existing scoped REST adapters remain the integration path; no duplicate MCP adapter was added. [Official Vexcel MCP setup](https://vexceldata.com/platform/vexcel-mcp/mcp-get-started/)

Live checks established:

- **Kipling Apartments, property 4483806:** one containing parcel and one building footprint.
- **Normandie, 229 S Normandie Ave, property 4355436:** one containing parcel and one building footprint; two landscaped-strip detection candidates; three imagery-search results. This is the supported Normandie example for subsequent review.
- **739 S Normandie Ave, property 734761:** also returns a containing parcel/building. It is a different property, outside the initial western stormwater study window. Name matching alone must not conflate these records.
- At 229 S Normandie, a DTM point query returned `vexcel-dtm` from the 2026 Los Angeles collection; a DSM point query returned `vexcel-dsm` from a 2025 Los Angeles collection. These establish endpoint/site access. Different products and capture periods must not be subtracted blindly into a measured building height.
- County live queries at that site returned a watershed feature and an interpolated event rainfall estimate of approximately 1.00 in.

This gives the next checkpoints viable physical geometry, landscape hints and elevation sources. Detections remain candidate boxes. Imagery search returns similarity, not confirmed material or drainage function. A point elevation does not validate a terrain raster, its datum, drainage connectivity or a full-area model.

The existing property query requests footprints but omits useful metadata fields, so its returned feature dates were blank. The advertised schema supports `capture-date`, `gsd`, metadata, hardscapes and roof fields. Request and validate only useful fields during the adapter work; those additional fields were not comprehensively tested here.

The profile reports unit-based billing and lists enabled services. The usage query was denied by role permissions, so remaining credits and account-wide usage could not be verified. Audit calls were bounded; no bulk expansion, account upgrade or entitlement change was made. Check remaining track allowance before large-area extraction or repeated detectors.

## Matterport association audit

The kit contains substantially more associations than the hardcoded viewer supports. Within the local property catalog, there are **4,225 CSV-to-attachment join rows across 1,297 properties**, representing 4,189 distinct model IDs. These are metadata candidates, not verified playable tours. Twenty-four model IDs appear against more than one local property, so the future resolver must handle ambiguous associations explicitly.

Caption screening finds 172 potentially relevant exterior/courtyard/loading/roof/outdoor rows across 146 properties. This is a text screen only. Kipling and the two Normandie properties have linked tour metadata, but their tested captions did not identify exterior coverage. Do not use an interior tour as evidence of curb or drainage conditions.

The existing 510 E Olympic Blvd association still passes the current CSV/address/property/attachment validation and `/api/site-view` returns its descriptor. The global entry still selects that property. Correcting it to follow the selected site is **Checkpoint 1**, not part of this restoration. Actual playback and design-to-scan registration were not tested here.

## Pilot geography and stormwater inventory

Use two explicit study windows for initial work; keep the broader LA map for navigation.

| Window | Bounds, west/south/east/north | Evidence and scope |
| --- | --- | --- |
| Downtown traffic | `-118.268, 34.034, -118.219, 34.070` | Fresh OSM network, 159 CoStar properties, 76 historical automated-count features and four accepted manual turning sheets. TomTom returned live flow near Main/1st and Beaudry/1st plus one area tile; pilot-wide completeness remains unverified. |
| Western stormwater | `-118.307, 34.055, -118.294, 34.073` | 106 CoStar properties, including Kipling and 229 S Normandie; successful site-specific sponsor and county checks. This is the proposed expansion boundary, not a claim of already-built terrain throughout it. |

The current water inventory still contains **48 terrain features, 64 rainfall-context cells and one county catchment feature**. Terrain uses the existing 1 m USGS bare-earth raster: a 400 m context window around Kipling with a smaller displayed pilot. The 64 rainfall cells are sampled context, not 64 independent observed flood events. Catchment context does not establish a parcel's connection to a drain.

The next terrain build must expand beyond that original window, retain surrounding context and verify source datum/resolution and boundary behavior. Vexcel DTM access is now a tested alternative to evaluate alongside USGS. Inlets, curb/downspout connectivity, soils/infiltration and overflow routing are not verified by this checkpoint.

Current traffic-study classifications remain:

- Main/1st and Beaudry/1st: supported network and count inputs for the current simulator.
- Hill/1st and Beaudry/Temple: comparison unavailable because represented conditional/complex/invalid turn restrictions remain unresolved.

Keep **data readiness separate from environmental priority**. Normandie can support a physical screening draft now but cannot yet support verified capture. Main/1st can support a modeled comparison but has no demonstrated eligible winning layout. Neither statement is an environmental-impact score.

## Traffic-provider decision and verified access

**Later follow-up:** The replacement HERE API key also passed a bounded `/v7/flow` check: HTTP 200, 60 records, source update time `2026-11-15T04:25:30Z`. It is saved locally. The earlier access-token failures below remain historical. See [Checkpoint 1](CHECKPOINT_1_WORKFLOW.md) for the current state; neither provider is integrated into the app yet.

**Selected provider for the next traffic integration: TomTom Traffic API / Traffic Flow.** On November 14, 2026, the user authorized navigating the TomTom setup. The signed-in MyTomTom account already contained a default key with Traffic API and Orbis Traffic Flow access. The dashboard showed Freemium; the key was labeled Evaluation. Completed optional developer/use-case onboarding and used that existing key. No new key, paid plan or expanded entitlement was created. Stored `TOMTOM_API_KEY` only in the ignored, mode-`0600` `.env`; no credential is included in this report.

Three bounded requests succeeded at approximately **23:18 EST on November 14 / 04:18 UTC on November 15**:

| Request | Observed result | Interpretation |
| --- | --- | --- |
| Flow Segment Data v4 near Main/1st | HTTP 200; current speed **20 km/h**, free-flow speed **29 km/h**; current travel time **220 s**, free-flow time **152 s**; confidence **1**; FRC4; no closure; geometry approximately **1.2 m** from the selected point; OpenLR present | A returned road segment showed a 68-second travel-time difference and about 31% lower speed than its free-flow reference at retrieval. This is not intersection-wide delay, a recurring pattern, a count or a measured emissions reduction. |
| Flow Segment Data v4 near Beaudry/1st | HTTP 200; current and free-flow speed **32 km/h**; both travel times **143 s**; confidence **1**; FRC4; no closure; geometry approximately **0.5 m** from the selected point; OpenLR present | The returned segment showed no slowdown relative to its free-flow reference at retrieval. This does not prove every nearby approach was uncongested. |
| Orbis v2 Vector Flow Tiles | HTTP 200; zoom 15; **14,783 bytes**, `application/vnd.mapbox-vector-tile` | Access to the current area/map representation is verified. The protobuf payload was not decoded, so actual feature coverage, requested tag presence and directions are not yet verified. |

The point response fields and proximity support these two local probes. They do not finish road/direction association, establish full pilot coverage, or provide a per-segment observation timestamp. The receipt records retrieval time and HTTP Date; neither should be relabeled a sensor observation time. [Flow Segment Data v4](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/flow-segment-data)

For Checkpoint 2A, start with **Orbis v2 flow tiles** for map coverage and a structured area-query tool. Decode and validate the geometry, directions, overlapping segments and fields before fixing the adapter contract. The documented on-demand `absolute_speed` is km/h; `relative_speed` is a fraction. OpenLR must be requested explicitly. This schema does not document the same confidence or per-segment observation timestamp as other providers. Use v4 point detail only with explicit version/source attribution and validated association; do not assume v4 and Orbis share identical geometry, identifiers or fields. [Orbis introduction](https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v2/product-information/introduction), [Orbis vector flow tiles](https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v2/traffic-flow/vector-flow-tiles), [migration guide](https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v2/product-information/migration-guide)

The public pricing page lists 20,000 monthly free Flow Segment Data requests and 200,000 monthly free flow/incident tile requests. These are published allowances, not a verified remaining account balance or a guarantee about every Orbis entitlement. No background polling is enabled. Verify the chosen endpoint's permitted display/storage, attribution, refresh policy and account budget before production use. Historical analytics and junction products are separate offerings. The request-only Intermediate Traffic evaluation currently lists six example cities, excluding LA; it is unnecessary for this initial live-flow integration. [Pricing](https://docs.tomtom.com/pricing), [Intermediate evaluation coverage](https://docs.tomtom.com/intermediate-traffic-service/documentation/tomtom-orbis-maps/evaluation-api/overview)

**Original HERE access-token check:** A bounded `/v7/flow` request with documented Bearer-token authentication returned HTTP 401 (`Token Validation Failure - unrecognized kid null`). An earlier attempt treating the value as an API key also returned HTTP 401 (`apiKey invalid. apiKey not found.`). The user subsequently confirmed the value was an access token. No cause such as expiry or account entitlement is inferred, and that rejected credential was not installed as a working configuration. The replacement API key subsequently passed the bounded check recorded above. [HERE authentication](https://docs.here.com/traffic-api/docs/send-request-readme)

HERE Traffic v7 supports structured area flow with source update time, speed/reference speed and confidence with real-time/historical/speed-limit semantics. Routing is complementary for specific route comparisons. Account pricing and entitlements remain unverified. TomTom now supplies the verified starting source, so HERE setup is not a dependency for Checkpoint 1 or the initial TomTom adapter. [HERE flow documentation](https://docs.here.com/traffic-api/docs/flow)

No traffic application code was changed in this follow-up. Historical turning counts remain the simulation-demand source; live speed alone does not replace them or directly measure CO₂.

## Reproduction and audit artifacts

From the repository root, with the local keys and official CoStar kit configured:

```sh
.venv/bin/python -m pip install -r requirements.txt -r requirements-discovery.txt -r requirements-sim.txt
.venv/bin/python -m pip check
.venv/bin/python scripts/fetch_osm.py
.venv/bin/python scripts/build_road_network.py
.venv/bin/python scripts/build_discovery.py
.venv/bin/python -m unittest discover -s tests
node --test tests/*.mjs
.venv/bin/python scripts/verify_traffic_network.py --output-dir private/checkpoint0/traffic-verification
PORT=8003 .venv/bin/python server.py
```

On this machine Node is available at `/Users/Derek/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node` if `node` is absent from the shell PATH. Create `.venv` first on a new machine. Place the original official CARB export at `sim/sources/emfac2025-la-2026.csv`; it is not redistributed in Git. Missing public discovery inputs can be downloaded by the builder; `--refresh` refreshes its public JSON/raster inputs. Previously missing PDF markers may need a targeted recheck. Use a free port or stop the server you started before restarting; old processes can otherwise serve stale Python code.

Private receipts and logs are under `private/checkpoint0/`: restored-input hashes, CoStar inventory, Matterport association candidates, Vexcel capability/schema and source checks, the deterministic Normandie draft, test logs and traffic verification. The follow-up adds secret-free `tomtom-access-check.json` and `here-access-check.json` access receipts. `sim/network-build.json` and its report folder bind the current OSM/network audit. Representative SHA-256 values:

| Input | SHA-256 |
| --- | --- |
| OSM extract | `a6d067836132d5ec46ce73124f0556091e10e0698f029450f13cb28bb480b80d` |
| Built road network | `f32130dcb97817ab695fb87607adf27779e5744f01ca5fd997b434cd2cd9b46d` |
| CARB fleet export | `014018df4b627705b08421d81a84dbb0544552a4a5c3caa9e21b132e5343a554` |
| Cached USGS raster | `a9352c6c4da8c7a7e55e8e55a6758f7d80b5904f18e79c3b456126c0b1addbf2` |

Discovery versions are `8e4a16a63abd7389` for street and `10dee9f329efed7b` for water. The existing aggregated turning-sheet `retrieved_at` records inventory build time; do not treat it as the original PDF download time. Sheet count dates and hashes remain explicit, and restored PDF file times were preserved. Correct per-sheet retrieval provenance during the traffic discovery work.

## Review boundary

Baseline restoration, source inventory and the bounded authenticated TomTom feasibility probe are complete and ready for review. Orbis payload decoding, road/direction association, use terms and production request policy remain Checkpoint 2A work. Remaining Vexcel credits need checking before bulk expansion. Checkpoint 1 can proceed independently once authorized: simplify stormwater entry, resolve actual site identity, improve bounded source queries and make Matterport follow the selected site. Persistent native subagents, skills and internal project files remain Checkpoint 3 work; none are claimed complete here.
