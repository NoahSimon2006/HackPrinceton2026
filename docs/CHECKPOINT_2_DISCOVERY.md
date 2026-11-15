# Checkpoint 2 — useful traffic and expanded stormwater discovery

Completed November 15, 2026. The user authorized both parts of Checkpoint 2. Checkpoints 0/1 were committed first as **`07c57af`** (`Restore source readiness and unify selected-site planning`). This work is on **`codex/checkpoint-2-discovery`**, based on that commit. Checkpoint 2 changes are uncommitted for review; nothing was pushed or merged. The local app runs at **http://127.0.0.1:8003/**.

## Traffic: current conditions with inspectable records

The app now decodes **TomTom Orbis v2 flow tiles** over the agreed downtown pilot. It displays current estimated speed, percentage of free-flow speed, road closure where supplied, displayed length and a screened travel-time penalty. Provider confidence and per-segment observation time remain unavailable; retrieval time is not relabeled as observation time. HERE remains configured as an alternative, without a duplicate production adapter.

The adapter uses the documented tile coordinate system and units, removes overlapping geometry within matching OpenLR references, and checks direction against ordered reference anchors or their local bearing. Unknown direction stays explicit. Conflicting values for one reference are excluded, with the layer marked partial. OSM proximity supplies a road name only when the association is unambiguous; it does not bind live traffic to simulation demand. Connected slow portions with the same name and checked direction can be inspected together through **Connected slow approaches**. Opposing traffic, overlapping lengths, branches and disconnected portions are not silently combined into one route.

Free-flow speed is calculated from current speed divided by the supplied relative speed. Time comparisons use the displayed length and those speeds; grouped comparisons sum the included source portions. Zero speed, closure and unsupported denominators do not produce an invented finite travel-time estimate. These are screening comparisons, not routing results, recurring congestion, traffic volume or measured CO₂.

Current data is kept in memory only, obeying the provider cache lifetime with a maximum of **60 seconds**. The map removes expired flow and offers explicit refresh; there is no background polling or feed archive. A full pilot fetch uses **30 tiles**, four requests at a time, with a **256-tile local process budget**. That counter is a local guard, not the account's remaining quota. Failures preserve historical layers without substituting expired traffic. Separate live versions preserve historical count references.

The existing **76 dated automated-count records** and **four verified turning intersections** remain available. Automated totals now say that their count duration is unknown; manual turning records retain their counted peak-hour meaning. Current flow does not replace the turning sheets required by SUMO.

Sources: [Orbis v2 tile fields, units, grid and cache headers](https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v2/traffic-flow/vector-flow-tiles), [TomTom OpenLR conversion library](https://github.com/tomtom-international/openlr-python), [TomTom product attribution and live-service conditions](https://download.tomtom.com/open/banners/third-party-product-terms-eula-2022-06.pdf). The implementation uses short-lived display/inspection; no account-wide usage or additional entitlement is inferred from a successful request.

## Stormwater: a larger source-backed pilot

The western pilot is **`-118.307, 34.055, -118.294, 34.073`**, approximately **2.4 km²**, with **300 m of surrounding terrain**. Four USGS CA_LosAngeles_B23 products supply a native 1 m mosaic. Their publication date is August 11, 2025; acquisition date remains unverified. No older acquisition is substituted.

The build retains source URLs, input and mosaic hashes, grid/datum metadata and bounded extraction windows. Source-grid alignment differed by less than **0.00007 m**, and overlapping elevations by less than **0.0001 m**. Native cells are placed on a common grid without interpolation or gap filling. An initial library merge produced an invalid flat mosaic; validation caught it, and the corrected build retains the real **53.009–95.533 m** elevation range. All **2,395,078 pilot cells** have valid source elevation.

| Layer | Current inventory | Meaning |
| --- | ---: | --- |
| Terrain paths and collection areas | **159 features across 53 display blocks** | Strictly downhill D8 screening. Unresolved flats/pits stay unresolved. Context-edge/NoData contributions are excluded. |
| Design rainfall | **244 display cells** | Interpolated county 85th-percentile, 24-hour depth; cells are not independent observations or source resolution. |
| County drainage study areas | **1 intersecting catchment** | Regional study context, without a verified parcel-to-inlet connection. |
| CoStar property context | **106 reported locations/uses** | Reported property context; selection still requires the local parcel association check. |
| Vexcel surface context | **6 parcel/building outlines at 3 independent properties** | Bounded samples at both Normandie properties and Kipling, with returned capture dates. This is not pilot-wide surface coverage. |

Selecting a terrain feature outlines the exact raster cells contributing to its terminal cell. The map explains what to investigate next instead of presenting a bare raster-area number as a treatment footprint. Source geometry and areas are locally measured; no runoff capture, verified flooding, impervious classification or inlet connection is inferred. The local terrain-screening helper now accepts the expanded, hash-validated mosaic.

The county inventory consulted did not supply a verified inlet/pipe layer for this build. Such infrastructure and documented flooding are therefore not displayed as established evidence. Rainfall, terrain and drainage context remain separate.

Sources: [USGS 1 m DEM collection and datum](https://data.usgs.gov/datacatalog/data/USGS%3A77ae0551-c61e-4979-aedd-d797abdcde0e), [The National Map product inventory](https://apps.nationalmap.gov/downloader/), [LA County layer inventory](https://dpw.gis.lacounty.gov/dpw/rest/services/PW_Open_Data/MapServer?f=pjson). The four exact download URLs and file hashes are retained in the ignored local metadata.

## Agent and API integration

A bounded area-query API returns the same spatial records used by the map, with source versions, availability and truncation. The domain specialist has **`query_neighborhood_discovery`**, limited to a 350 m neighborhood and curated scalar facts. Raw polygons, contribution outlines, property names/addresses and exact coordinates remain outside model context. Both sponsor providers can contribute neighborhood facts alongside terrain, rainfall and current flow. This extends the existing per-run specialist workflow; persistent native subagents and project files remain Checkpoint 3.

## Verification

- **148 Python tests pass, zero skips**, including tile decoding, opposite directions, overlap conservation, conflicting values, stale live references, cache isolation, request budget, terrain-area conservation and a real location outside the old window.
- **All six JavaScript test files pass**, including explicit refresh, removal of expired flow, retained historical references, mode changes during a pending fetch and existing proposal/cancellation protections.
- A live browser fetch displayed **1,200 current street portions**. A separate inspected snapshot offered **62 connected slow approaches**. Counts vary with the current source response; coverage remains explicitly partial.
- A real Main Street group showed its road direction, two source portions and a sourced free-flow comparison. The source/method panel kept retrieval time and unavailable observation/confidence separate.
- Outside the original Kipling window, feature **`flow-1902-1255`** displayed **12,137 m²** of raster contribution. Its projected outline area independently matched that value.
- A real downtown query against the western stormwater inventory returned **`outside_pilot`** and zero matching records in every layer. No substitute terrain was returned.
- A real Grok/Deep Agents analysis at 229 S Normandie completed without an analysis error, consumed **18 neighborhood facts**, and produced a mapped rain-garden draft. The cited review used CoStar, Vexcel, county and terrain evidence; contributing runoff and capture stayed unassessed.
- Desktop traffic and stormwater rendering were inspected. At **390 × 844**, page width remained 390 px, discovery controls collapsed correctly and did not overlap zoom controls. Browser console errors: none. The temporary viewport override was reset.
- Dependency compatibility check passed. No new SUMO run was needed: network, turning demand and simulation code are unchanged, with the prior nine-run baseline retained.

Private receipts and source files remain ignored: `private/checkpoint2-*.log`, `private/checkpoint2-live-draft.json`, and the expanded assets under `private/discovery/`. The live traffic adapter does not save feed payloads to disk.

## Review walkthrough and next boundary

1. Open Traffic & Emissions. Inspect **Current street flow**, then **Connected slow approaches**. Select a road and open **Source, method & limits** for its comparison. After expiry, use **Refresh current traffic**.
2. Switch to **Dated automated counts** and **Turning-movement counts** to see the separate historical demand evidence.
3. Switch to Stormwater and browse **Terrain paths & collection areas**. Inspect the outlined contribution and its practical explanation. Toggle rainfall, county study areas, property uses and sampled outlines separately.
4. Search **229 S Normandie**, select the property and analyze without drawings to exercise the agent with neighborhood context.

The next checkpoint is **3: persistent agent workspace, native delegation, trusted skills and project files**. It has not started. Researched location shortlisting, complete conversational design loops and conceptual 3D remain later checkpoints.
