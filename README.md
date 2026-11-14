# Sustainability Map

A local Vexcel aerial map for Los Angeles with a precomputed downtown road-emissions pilot in **Urban Planners**. The pilot compares weekday midday and PM peak modeled tailpipe CO₂ and NOₓ. CoStar property points and Esri labels remain optional layers. Urban Planners also includes a site workspace with Intersection Redesign and Stormwater evidence workflows powered by one Deep Agent.

## Run locally

Put `VEXCEL_API_KEY`, `GROK_API_KEY`, and the absolute `COSTAR_KIT_DIR` in the ignored local `.env`. The existing `.env` can be reused. The CoStar kit needs `data/commercial-property.jsonl` and `schemas/enums.json`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Open <http://127.0.0.1:8000>. Set `PORT=8023` if that port is taken. The server binds to localhost. Vexcel and Esri need network access; the emissions artifact and Leaflet are bundled locally. The Vexcel key stays on the server. The map and site card receive selected CoStar property fields. The agent defaults to `GROK_MODEL=grok-4.7`; its dependencies are separate from the optional simulation rebuild dependencies.

Append `/#urban-planners` to open directly on the emissions overlay. After pulling changes to `server.py`, stop and restart the Python server on the same port, then reload the page. An older process can serve the updated HTML while still lacking `/api/emissions`, which produces a 404 and an empty overlay. The map now shows a restart message and Retry button in that case, and displays the legend only after data loads.

## Plan a site

1. Open **Urban Planners**. Search for a CoStar property or select **Pick a site on the map**.
2. Choose **Intersection Redesign** or **Stormwater**, then select **Analyze site** or edit the suggested question. One Deep Agent chooses which local tools to call. **Site evidence** draws the actual tool results, such as parcel and building outlines, detection candidates, and nearby CoStar frontage. Toggle **Show imagery search areas** to see the ranked scenes when the agent ran a search.
3. In **Stormwater**, review the county subbasin and rainfall estimate. The 85th-percentile, 24-hour depth is estimated between adjacent LA County contours that bracket the site. Enter a scenario depth and source manually when the service or estimate is unavailable.
4. Use **Adjust or add map markings** if a crossing, driveway, runoff source, or treatment area needs clarification. The next analysis sees which types of features you marked. Map markings, rainfall inputs, and assessments stay available during the current page session.

The configured xAI model receives the typed question, the workflow, and short summaries such as detection counts and source availability. The app keeps coordinates, geometry, rainfall depths, and CoStar fields on the local server and displays them in the browser.

## What the pilot means

The displayed road values are an **illustrative scenario**, not a current measured inventory or calibrated traffic forecast. The 4 × 4 km pilot uses OpenStreetMap road geometry, SUMO 1.28 traffic and edge-emissions runs, the California Air Resources Board's EMFAC2025 v2.1.1 **2026 Los Angeles (SC)** regional on-road fleet rates, and historical LADOT traffic counts. The [EMFAC rates](https://emfac.arb.ca.gov/emissions-inventory/3b6469b056eb7e5a47b65c0c96415b33d5e20812) are VMT-weighted across vehicle/fuel rows and include electric vehicle miles as zero tailpipe running exhaust. SUMO supplies relative speed and route-pressure variation; its European default emissions factors are normalized to the CARB fleet rates. The layer covers running exhaust only, excluding upstream and non-tailpipe emissions.

The [LADOT traffic count data](https://data.lacity.org/Transportation/LADOT-Traffic-Counts-Summary/94wu-3ps3) are from **2011–2016**. Where a street and cross-street match the road network, the latest weekday directional count anchors that segment's daily volume. Other segments use stated road-class daily-volume assumptions, adjusted by illustrative SUMO route pressure. Hourly shares of daily volume are assumed: 6% at midday and 8.5% at PM peak. Signal locations come from OSM; SUMO generated timing is assumed. The UI gives judgmental sensitivity ranges of approximately ±35% on count-anchored edges and ±60% elsewhere; these are **not statistical confidence intervals**. Neither the historical counts nor the random origin–destination routes should be read as 2026 observed traffic.

The bundled `public/data/emissions.json` contains the two ready-to-use periods, source links, method description, and road-level basis labels. The layer starts automatically when Urban Planners opens, and the map centers on the pilot. Road click details show the historical anchor or volume assumption.

## Rebuild the artifact

The source downloads and SUMO outputs live in ignored `sim/`. The derived map artifact is tracked so the demo works without installing SUMO.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-sim.txt
.venv/bin/python scripts/fetch_osm.py
mkdir -p sim/sources
curl -L 'https://data.lacity.org/resource/94wu-3ps3.json?$limit=6000' -o sim/sources/ladot-traffic-counts.json
```

In the [EMFAC emissions inventory](https://emfac.arb.ca.gov/emissions-inventory/), select **Onroad Emission Rates**, **EMFAC2025 v2.1.1**, **Sub-Area → Los Angeles (SC)**, **2026**, **Annual**, all EMFAC202Y classes and fuels, aggregate model year and speed. Download the output CSV as `sim/sources/emfac2025-la-2026.csv`. Then run:

```sh
.venv/bin/python scripts/run_pilot.py
```

The pipeline creates a SUMO network, generates deterministic random routes (seed 26 for midday, 27 for PM peak), runs both periods, and rebuilds `public/data/emissions.json`. The scripts and method metadata make the assumptions reviewable. OSM data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
