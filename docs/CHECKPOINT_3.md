# Checkpoint 3 review · November 14, 2026

This report records Checkpoint 3 acceptance before pull-request publication. The work builds on Checkpoints 0–2 on `codex/checkpoints-0-1`. **Stop here for review; Checkpoint 4 has not started.**

The user explicitly changed the traffic acceptance target: **“Show historical counts with dates; leave unsupported metrics unavailable.”** The archived assumed-demand emissions scenario remains disabled. No forecast, hourly extrapolation, emissions benefit, delay benefit or flood depth was invented to complete this checkpoint.

## What is available

- **Traffic:** 76 dated automated LADOT count records, located approximately through exact normalized street-name pairs in the local OSM network.
- **Stormwater:** 32 inferred downhill paths and 16 unresolved collection candidates from a real 1 m USGS DEM; 64 county design-rainfall display cells; one clipped county storm-drain study catchment.
- A map layer selector, legend, pilot navigation, optional overlay hiding, collapsible controls and keyboard-accessible feature selection.
- Clicking/selecting a feature shows its source, period/event, value, units, method and limitations, and seeds a site brief without an agent call. The existing Analyze site flow receives a validated scalar fact from that selection.
- Source failures stay explicit. One unavailable source does not remove other usable layers. A missing local snapshot offers retry and build instructions; it never becomes a fixture. Browser retry reloads the local snapshot; refreshing upstream data requires the build command.

Try <http://127.0.0.1:8001/#urban-planners> and <http://127.0.0.1:8001/#stormwater>. Use **Browse mapped features**, then **Source, method & limits** in the sidebar. Select **Analyze site** only when ready to investigate. Narrow-screen selection collapses the layer controls; **Show layers** reopens them.

## Traffic sources and interpretation

[LADOT Traffic Counts Summary](https://data.lacity.org/Transportation/LADOT-Traffic-Counts-Summary/94wu-3ps3), [records API](https://data.lacity.org/resource/94wu-3ps3.json), [metadata](https://data.lacity.org/api/views/94wu-3ps3.json): 5,953 downloaded rows, source dates 2011–2016; latest source date December 7, 2016. Metadata reports its last row update as January 6, 2017 and license `CC0_10`. Downloaded November 14, 2026.

Metadata describes manual counts expanded using conversion factors. These are excluded, along with unverified count types. Only `AUTO`/`AUT`, `AT`-intersection records with finite nonnegative integer totals are eligible. The source metadata does not document each automated count's observation duration. Values therefore mean **vehicles reported**, not vehicles/hour or vehicles/day. Direction columns are exposed as reported, never divided, inferred or scaled.

The builder matches normalized primary/cross street names against passenger-road junctions within the downtown bounding box. Ordinal naming and standard street suffixes are normalized. Junction clusters wider than 60 m are rejected as ambiguous; equivalent nodes within that tolerance are consolidated to a deterministic representative. This is a documented geolocation heuristic, not a surveyed count-station position. Latest eligible record per ordered street pair is retained. A reversed primary/cross pair may describe a different measured street at the same intersection; the feature picker makes overlapping records accessible.

[OpenStreetMap](https://www.openstreetmap.org/copyright) supplies geometry only. Local OSM/network vintage is unverified, so no contemporary count-station accuracy is claimed. Its input hash is recorded. No SUMO demand, EMFAC rate or model response enters these discovery values.

Filtering audit: 2,624 records have no in-pilot network match; 1,844 use manual/unverified types; 1,404 specify offset locations. Remaining eligible records are deduplicated by latest date into 76 map features. None is a turning-movement or signal-plan observation.

**Spot check:** `count-920f956738fc`, 1st Street at Alameda Street, January 16, 2014, automated record. The displayed total **18,102** exactly matches the downloaded record; reported westbound 6,433 and eastbound 11,669 sum to that total, with north/south both reported zero. The automated test checks the original source object and date without time conversion. Approximate network location: `cluster_12385839648_12385839656_1437216564_6389146888_#2more`.

### SUMO export preparation

The archived builder now exports `waitingTime` and `timeLoss` as summed vehicle-seconds, their shares of `sampledSeconds`, interval begin/end, entered/left/departed/arrived counts and simulated flow. Stopped time uses a 0.1 m/s halting threshold. Shares use **vehicle presence seconds**, not a guessed vehicle denominator; missing/zero samples produce null. Multiple intervals are rejected until explicitly aggregated. Definitions follow [SUMO's edge-output documentation](https://sumo.dlr.de/docs/Simulation/Output/Lane-_or_Edge-based_Traffic_Measures.html).

This code applies to both period exports, but no random-demand simulation was run and the archived artifact was not regenerated. These outputs are still labeled assumed-demand and are not live discovery metrics. Verified demand, turning volumes, signals and queue/throughput observations remain prerequisites for a credible comparison.

## Stormwater sources and method

**Elevation:** [USGS 3DEP 1 m product](https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/CA_LosAngeles_B23/TIFF/USGS_1M_11_x37y378_CA_LosAngeles_B23.tif), `USGS 1 Meter 11 x37y378 CA_LosAngeles_B23`. National Map metadata identifies publication August 11, 2025; acquisition date is unverified. [USGS dataset documentation](https://data.usgs.gov/datacatalog/data/USGS%3A77ae0551-c61e-4979-aedd-d797abdcde0e) describes bare-earth elevations in meters referenced to NAVD88. Native grid: NAD83 / UTM 11N (EPSG:26911), 1 m cells.

Downloaded a 400 × 400 m window around the Kipling pilot by ranged GeoTIFF access. All 160,000 cells are valid; heights range from 67.592 to 78.910 m. Routing uses the native cells, without smoothing, resampling or sink filling. Each valid cell routes to its steepest strictly downhill D8 neighbor, accounting for diagonal distance. Flats and pits stop routing. Accumulation adds one square meter per cell in descending elevation order; it is **window-limited contributing raster area**, not verified drainage area or runoff volume.

Display covers the inner 240 × 240 m with an 80 m context buffer. Candidate paths/terminals require at least 100 m² accumulated raster area. Path display additionally requires at least six contiguous cells and a 0.2 m drop. Up to 32 paths are selected with overlap suppression; up to 16 unresolved terminal candidates are spaced at least 12 m apart. These are display filters, not engineering thresholds or assumed flow quantities. Routes leaving and reentering the display area are clipped to a single contiguous section, never bridged. Contributions touching the data boundary are flagged.

Bare-earth terrain can route under mapped buildings and ignores roof drains, curbs and pipe networks. Small elevation differences may fall within DEM uncertainty. Gold points are **unresolved sink/flat candidates**, not observed ponding, a flood probability, flood depth or a treatment recommendation. The DEM is suitable for screening topography, not curb-scale design or hydraulics.

**County comparison:** [LA County storm-drain study catchments, layer 47](https://dpw.gis.lacounty.gov/dpw/rest/services/PW_Open_Data/MapServer/47). The returned pilot polygon is **Ballona Creek**, outfall reference **BC-100**. Terrain features are spatially checked against it and expose county context. This study compilation is regional context, with vintage unavailable; membership does not establish an inlet-level or parcel drainage connection. No inlet survey or verified pipe connection was available in this pass.

**Rainfall:** [LA County 85th-percentile, 24-hour contours](https://dpw.gis.lacounty.gov/dpw/rest/services/hydrologygis/MapServer/3), source date unavailable. The existing contour adapter interpolates at 30 m display-cell centers. The pilot's displayed estimate is 1.01 inches, bracketed by 1.0 and 1.1 inch contours. The 30 m cells are display geometry, not rainfall source resolution. This is a design-event depth, not real-time rainfall, intensity or flood depth.

**Spot check:** first exported path `flow-1`, from native raster cell `[157,94]` to `[181,175]`. Every segment follows the D8 downstream neighbor and descends in the downloaded DEM. Accumulated area at its downstream end is **2,777 m²**; path length **91.77 m**; elevation drop **2.443 m**, calculated before display rounding. No window-edge contribution was detected for this path; the window and unresolved-pit limitations still apply. Its downstream point falls inside the returned Ballona Creek polygon. The test recomputes accumulation and verifies every path coordinate against raster cells.

## Provenance, reproducibility and privacy

Install `requirements-discovery.txt`, then run `.venv/bin/python scripts/build_discovery.py`. Inputs and outputs live in ignored `private/discovery/`; `--refresh` refetches upstream data. The current OSM network is `sim/dtla.net.xml`; see README for source-only network preparation on a fresh checkout. No sponsor data or model request is needed to build these public-source layers. County data is kept local; no new redistribution rights are asserted. OSM attribution remains visible on the map.

Each snapshot includes schema, workflow, build time, source retrieval dates/hashes, data limitations, filtering audit and a version identifier. Cached source timestamps remain their original file retrieval times, rather than being relabeled at every rebuild. Raw source records, raster grid references and local geometry support inspection/reproduction; they do not enter automatic model context.

At analysis time the server resolves `{version, layer, feature}` against the current local snapshot and verifies that the selected site is within 5 m of the feature's declared center. Stale, invented, unavailable or mismatched-site references are rejected before any model call. Only a curated sourced scalar fact is added to the model-visible brief. Names, addresses, coordinates, raw source records and geometry stay local. Changing the selected feature invalidates/cancels the old analysis, even at the same center. Mode changes reject late discovery responses and restore their own map views.

## Acceptance and remaining limits

- 27 Python tests pass, including D8 conservation/strict descent, pits/flats/NoData, clipping continuity, count filtering/dates/directions, source-reference validation/privacy, partial-source failure, delay denominators and the two real-source spot checks. Existing agent, proposal, API and measurement checks still pass. Scripted graph tests verify that the new sourced selection reaches model context without restricted fields.
- Four JavaScript suites cover discovery, planner/hydrology, streamed activity and proposal revisions. Discovery checks include selection without agent calls, partial failure, retry, mode races, layer hiding and compact controls. The planner test verifies reference submission and cancellation at the same coordinate.
- Desktop browser walkthrough: all four discovery layers loaded; selections exposed source/value/date or event, and seeded the prompt. Traffic matched 18,102 on January 16, 2014; terrain matched the 2,777 m² spot check. Existing Vexcel imagery rendered beneath the overlays.
- Narrow viewport inspection uses Chrome responsive mode at 400 × 844. The prompt and Analyze site action remain reachable with a visible map. A crowded layout found during this check was corrected with collapsible controls and removal of the duplicate small-screen watershed legend.
- The final compact layout was rechecked: selecting terrain evidence changed **Hide layers** to **Show layers**, exposed the popup and left the lower map clear. Desktop mode was restored afterward. Review captures: `/private/tmp/checkpoint-3-discovery.png` and `/private/tmp/checkpoint-3-mobile.png`. JavaScript syntax, Python compilation and `git diff --check` pass.

No current traffic calibration, physical redesign comparison, verified inlet connectivity, hydraulic flood model or treatment impact is claimed. Sponsor-driven deep-agent investigation remains the Checkpoint 2 workflow; Checkpoint 3 browsing does not need to invoke it. Public-source screening does not replace sponsor evidence or field verification for later designs.

**Next review decision:** whether to proceed to Checkpoint 4, with its verified traffic input gaps resolved first. Do not begin it automatically.
