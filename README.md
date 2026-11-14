# Sustainability Map

A Los Angeles aerial map with a site workspace for urban planners. CoStar property points and Esri place labels are optional layers.

## Run locally

Set `VEXCEL_API_KEY`, `GROK_API_KEY`, and `COSTAR_KIT_DIR` in a local `.env` file. Set `COSTAR_KIT_DIR` to the absolute path of the extracted kit, which contains `data/commercial-property.jsonl` and `schemas/enums.json`. Git ignores `.env`. Keep the kit outside the checkout.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

Open <http://127.0.0.1:8000>. If that port is occupied, run `PORT=8001 .venv/bin/python server.py` and open <http://127.0.0.1:8001>. The server binds to localhost only. Vexcel imagery, LA County hydrology, and the xAI model require network access. The API keys and CoStar source records stay server-side. The map and site card receive selected property fields.

The opening view is downtown Los Angeles at zoom 13. Panning uses Vexcel's ortho collection coverage and samples across the viewport. Property points appear when their toggle is on and zoom is at least 15. Selecting a property search result enables the layer and zooms to it. Leaflet is bundled locally. Optional labels load from Esri.

## Plan a site

1. Open **Urban Planners**. Search for a CoStar property or select **Pick a site on the map**.
2. Choose **Intersection Redesign** or **Stormwater**, then select **Analyze site** or edit the suggested question. One Deep Agent chooses which local tools to call. **Site evidence** draws the actual tool results, such as parcel and building outlines, detection candidates, and nearby CoStar frontage. Toggle **Show imagery search areas** to see the ranked scenes when the agent ran a search.
3. In **Stormwater**, review the county subbasin and rainfall estimate. The 85th-percentile, 24-hour depth is estimated between adjacent LA County contours that bracket the site. Enter a scenario depth and source manually when the service or estimate is unavailable.
4. Use **Adjust or add map markings** if a crossing, driveway, runoff source, or treatment area needs clarification. The next analysis sees which types of features you marked. Map markings, rainfall inputs, and assessments stay available during the current page session.

The configured xAI model receives the typed question, the workflow, and short summaries such as detection counts and source availability. The app keeps coordinates, geometry, rainfall depths, and CoStar fields on the local server and displays them in the browser.
