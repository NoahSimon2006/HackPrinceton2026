# Sustainability Map

A local Vexcel aerial map for Los Angeles with a precomputed downtown road-emissions pilot in **Urban Planners**. The pilot compares weekday midday and PM peak modeled tailpipe CO₂ and NOₓ. CoStar property points and Esri labels remain optional layers.

## Run locally

Put `VEXCEL_API_KEY` and `COSTAR_KIT_DIR` in the ignored local `.env`. The existing `.env` can be reused. The CoStar kit needs `data/commercial-property.jsonl` and `schemas/enums.json`.

```sh
python3 server.py
```

Open <http://127.0.0.1:8000>. Set `PORT=8023` if that port is taken. The server binds to localhost. Vexcel and Esri need network access; the emissions artifact and Leaflet are bundled locally. The Vexcel key stays on the server. CoStar endpoints return only property name, address, type, ID, and location.

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
