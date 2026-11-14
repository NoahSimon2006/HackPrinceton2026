# Sustainability Map

A Los Angeles aerial map with a site workspace for urban planners. CoStar property points and Esri place labels are optional layers.

## Run locally

Set `VEXCEL_API_KEY` and `COSTAR_KIT_DIR` in a local `.env` file. Set `COSTAR_KIT_DIR` to the absolute path of the extracted kit, which contains `data/commercial-property.jsonl` and `schemas/enums.json`. Git ignores `.env`. Keep the kit outside the checkout.

```sh
python3 server.py
```

Open <http://127.0.0.1:8000>. If that port is occupied, run `PORT=8001 python3 server.py` and open <http://127.0.0.1:8001>. The server binds to localhost only. Vexcel imagery and LA County hydrology lookups require network access. The API key and CoStar source records stay server-side. The map and site card receive selected property fields.

The opening view is downtown Los Angeles at zoom 13. Panning uses Vexcel's ortho collection coverage and samples across the viewport. Property points appear when their toggle is on and zoom is at least 15. Selecting a property search result enables the layer and zooms to it. Leaflet is bundled locally. Optional labels load from Esri.

## Plan a site

1. Open **Urban Planners**. Search for a CoStar property or select **Pick a site on the map**.
2. Choose **Intersection Redesign** or **Stormwater**. Draw a crossing, driveway keep-clear area, contributing drainage area, or treatment footprint. To change a saved feature, select **Edit**, move its handles, and save.
3. In **Stormwater**, review the county subbasin and rainfall estimate. The 85th-percentile, 24-hour depth is estimated between adjacent LA County contours that bracket the site. Enter a scenario depth and source manually when the service or estimate is unavailable.
4. Write a planning brief or use the suggested brief. Features, rainfall inputs, and briefs stay available when switching workflows or revisiting the same site in the current page session.
