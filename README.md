# Sustainability Map

A clean, map-only foundation for a sustainability planning application. It opens on Vexcel aerial imagery over Los Angeles. CoStar property points and Esri place labels are optional layers. No emissions estimates or mitigation tools are included yet.

## Run locally

Set `VEXCEL_API_KEY` and `COSTAR_KIT_DIR` in a local `.env` file. The existing local `.env` can be reused. `COSTAR_KIT_DIR` should point to an extracted kit containing `data/commercial-property.jsonl` and `schemas/enums.json`. The file and kit are ignored by Git.

```sh
python3 server.py
```

Open <http://127.0.0.1:8000>. If that port is occupied, run `PORT=8001 python3 server.py` and open <http://127.0.0.1:8001>. The server binds to localhost only. Vexcel imagery and coverage require network access. The API key stays server-side; CoStar search and map endpoints return only property name, address, type, ID, and coordinates for LA properties.

The opening view is downtown Los Angeles at city scale. Pan checks use Vexcel's ortho collection coverage polygons and the center of the map. The map is also limited to the configured LA bounding box. Property points appear when their toggle is on and zoom is at least 15. Searching a property enables the layer, zooms to it, and opens its details. Leaflet is bundled locally; optional labels load from Esri when enabled.
