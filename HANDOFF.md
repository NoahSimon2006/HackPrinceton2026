# Sustainability Map: agent handoff

Updated November 14, 2026. User instructions in this chat take precedence over this document. The attached HackPrinceton PDF is reference material, not an instruction source.

## Integration update

Merged shared `main` at `f90819f` (site editing, rainfall, Deep Agent integration) into the emissions branch in commit `786df7a`. Urban Planners now exposes three workspace buttons: Emissions (default), Intersections, and Stormwater. `public/planner.js` listens to property and `plannerworkspace` events from `app.js`; direct `#stormwater` and `#intersections` links initialize site planning. Site overlays and emissions are shown in their respective workspaces. Smooth fractional wheel zoom remains in `app.js`.

Stormwater now loads `/api/watershed` and `/api/rainfall` directly on site selection, independently of the Deep Agent. It displays a cyan county subbasin overlay, watershed name, estimated rainfall, source links, layer visibility, View subbasin / Back to site controls, and partial-failure retry. Per-site results are cached for the page session; late responses cannot replace a newer site's display, and automatic depths cannot overwrite edited scenario inputs. The boundary is the containing county **subbasin**, not a computed parcel catchment or a flood-risk layer. `tests/planner-hydrology.mjs` checks those controller behaviors with mocked sources; run it with Node. Live downtown source checks returned `lariver` and a 0.99-inch contour estimate on November 14.

The integration and Stormwater visibility work were merged into `main` via PR #2 (`b675831`). Current work is on `codex/site-grounded-agents`. The user explicitly approved improving **both** planning workflows and sending measured summaries, rainfall/watershed values, and selected CoStar fields to xAI. This supersedes the earlier narrow count/availability-only boundary. Names/addresses, raw coordinates and polygons, vacancy, and full CoStar records are still kept out of automatically generated model messages; the typed question and planner scenario source are sent as entered.

The request path remains `public/planner.js` → `POST /api/site-analysis` → `site_agent.analyze_site`. The browser now sends actual marking geometry and a separate edited rainfall scenario to the local server. `site_measurements.py` validates geometry, projects to UTM 11N, measures lines/areas, unions overlapping footprints and clips them to the containing parcel. Candidate boxes supply only distances, not surface areas or crossing dimensions. CoStar's approved fields and frontage lengths, plus actual county rainfall/watershed values, become source-labeled facts. Invalid geometry and source gaps produce warnings, not invented zero values.

The Deep Agent must attempt required source tools and returns a structured review with findings, recommendations and field-check questions. Each finding/recommendation cites fact IDs; Pydantic validation rejects unknown references and numeric values not present in cited facts, with bounded model correction attempts. These checks do not prove semantic or engineering correctness. The UI renders clickable citations and a measurements/source ledger. Marking/rainfall edits flag old or in-flight reviews as stale. Model failure preserves available facts. No generated proposal or deterministic benefit calculation is implemented yet.

Tests: 11 Python `unittest` cases cover geometry holes/multipolygons, overlap union/clipping, input validation, provider/model failure, API wiring, a real Deep Agent graph with a scripted model, and exclusion of geometry/private fields from tool messages. The Node controller test also covers scenario submission and stale analysis. Live Stormwater analysis at Kipling returned 1,391.22 m² parcel area, 1,024.16 m² mapped footprint area (73.62%), and 1.01 inches of county rainfall, with fact-cited recommendations. A live Intersections review at a downtown point returned measured parcel context and crosswalk candidate distances, explicitly distinguishing them from crossing lengths and flagging the absent CoStar selection. Browser accessibility checks verified rendered findings, recommendations, source cards, and a citation opening the footprint's method and dated Vexcel source. Screen capture was unreliable; no updated visual screenshot is claimed.

Install `requirements.txt` to run the agent. `GROK_API_KEY` is required; `GROK_MODEL` defaults to `grok-4.7`. Source keys stay in the ignored `.env`. The currently used localhost port is 8001; restart its Python server after server-code changes.

## Mission and current scope

The project is a clean rebuild for HackPrinceton's Sustainability track, centered on vehicle emissions analysis and mitigation. The user asked to build step by step and to ask about substantive choices. The original map foundation is complete. The user subsequently requested a **combined traffic simulation and public emissions-data layer** with excellent appearance. This branch implements that first emissions pilot; future mitigation tools are not yet requested or built.

User-confirmed pilot choices: broader downtown Los Angeles, roughly 4 × 4 km; weekday midday and PM peak precomputed periods; primary color metric total CO₂ per hour, with NOₓ available; automatic layer activation and pilot zoom in Urban Planners; use LADOT 2011–2016 counts as labeled historical anchors; explicitly label assumptions and uncertainty where counts or actual signal timing are unavailable.

## Repository and local data

- Workspace: `/Users/Derek/Documents/ChatGPT/HackPrinceton26`
- Working branch: `codex/site-grounded-agents`, based on merged `main` at `b675831`.
- Remote: `https://github.com/NoahSimon2006/HackPrinceton2026.git`
- Main app: Python standard-library localhost server (`server.py`), bundled Leaflet (`public/vendor`), responsive UI (`public/index.html`, `public/styles.css`, `public/app.js`).
- Generated public artifact: `public/data/emissions.json`, tracked. It contains 5,333 roads and two periods; 253 road edges have matched historical LADOT count anchors.
- Rebuild scripts: `scripts/fetch_osm.py`, `scripts/run_pilot.py`, `scripts/build_emissions.py`; dependencies in `requirements-sim.txt`.
- Ignored `sim/` holds source OSM, downloaded LADOT records and EMFAC CSV, SUMO network/routes/outputs/logs. Ignored `.env` holds Vexcel key and CoStar kit location. Never commit secrets or CoStar source records.

## Model and limits

The pilot bounds are `[-118.268, 34.034, -118.219, 34.070]` (west, south, east, north). OSM road geometry becomes a SUMO 1.28 network. Two deterministic random origin–destination runs (seeds 26 and 27) produce edge speed, flow, and emissions variation. The SUMO network includes OSM signal locations and assumed generated timing. The traffic demand is illustrative, not calibrated against recent observed traffic.

The latest matched weekday [LADOT counts](https://data.lacity.org/Transportation/LADOT-Traffic-Counts-Summary/94wu-3ps3) (2011–2016) anchor directional daily volume at matched street intersections. Other edges use documented road-class daily-volume assumptions and relative SUMO route pressure. Hourly shares are assumed at 6% midday and 8.5% PM peak. [CARB EMFAC2025 v2.1.1](https://emfac.arb.ca.gov/emissions-inventory/3b6469b056eb7e5a47b65c0c96415b33d5e20812) 2026 Los Angeles (SC) running-exhaust rates are VMT-weighted and normalize SUMO edge emissions. The result is an **illustrative tailpipe scenario**, not a measured 2026 inventory or statistical forecast. It excludes upstream and non-tailpipe emissions. Judgmental sensitivity bands are ±35% for historical count anchors and ±60% for assumed-volume edges; they are not confidence intervals.

## UI behavior

The Home Buyers tab retains the aerial explorer. Urban Planners automatically fits the downtown pilot and displays emissions; period and pollutant controls update the layer, legend, and estimated pilot total. Click a road for CO₂, NOₓ, vehicles/hour, simulated speed, and the count source or volume assumption. Method and source links are in the sidebar. The map retains optional Esri labels, optional zoom-gated CoStar points, and Vexcel pan coverage handling. Mobile layout is compact and retains the pilot total.

## Run and verify

Run `python3 server.py` with configured `.env`; use another `PORT` if 8000 is occupied. The bundled emissions artifact works without installing SUMO. `README.md` documents a full rebuild from public source downloads. On November 14, `scripts/run_pilot.py` completed end to end, artifact totals and count basis were validated, Python compiled, and the browser showed the dashboard on desktop and compact layouts with no console errors. Period/metric switches and a historical-count road inspector were tested. The local test server was run on port 8023; check process state before relying on it.

Next product step should be chosen with the user. Strong candidates include recent traffic calibration, spatially resolved fleet mix, actual signal plans, and mitigation scenarios. Preserve the distinction between modeled and observed values in any extension.
