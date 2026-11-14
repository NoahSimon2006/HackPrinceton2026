# Crossing Lab

Traffic engineering copilot for early intersection redesign. Explore real streets, ask for a change, and compare the same concept on a Vexcel map and a navigable 3D street. The prototype opens at Olympic Boulevard and Wall Street in Los Angeles. The inherited Houston tab links to H-GAC's regional explorer.

## Run locally

Use Python 3.12 and Node.js 22. From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
.venv/bin/python scripts/import_la.py
.venv/bin/python scripts/import_ccrs.py
.venv/bin/python server.py
```

Set the local credentials below before starting the server. Open [Crossing Lab](http://localhost:8000) in a WebGL-enabled browser. Vexcel, Matterport, and Grok requests require internet access. If a Python installation uses a separate certificate store, configure its trusted CA bundle before running the server and imports.

## Walk a revised design

1. At the featured intersection, choose **Plant a corner** or send your own design request.
2. Switch to **Street view**, then **Proposed**. Drag to look around. Use the on-screen arrows or W and S to move, and the keyboard arrow keys to look. Switching between existing and proposed keeps the same viewpoint.
3. In **Aerial map**, choose **Mark keep-clear area** and click two corners around a driveway or proposed treatment. Choose **Ask Grok to revise**. The completed proposal gets a new version, with recalculated footprint, crossing width, and modeled tree-shade area. Overlapping physical treatments are rejected by the geometry tool so the agent can try a different position.
4. Under **Nearby property access**, open the linked Matterport exterior and loading-dock scan at 510 E Olympic Boulevard. CoStar properties supply recorded use, parking and loading fields where known. The user confirms access footprints from imagery and scans.

Vexcel's city mesh captures the existing street at aerial photogrammetry quality. The proposal is a 3D concept over that mesh. It uses the same projected geometry as the map. The shade figure is the projected footprint of the proposed tree crowns at 4 p.m. PDT on July 15, before overlap with existing shadows. It is not a temperature estimate. Crossing widths use concept dimensions, and keep-clear checks test footprint overlap. Vehicle swept paths, accessible clearances and right-of-way need separate verification.

## Credentials and data

Use `.env.example` as a template for the Git-ignored `.env`:

- `VEXCEL_API_KEY` supplies the orthomosaic, aerial extracts and street-level 3D mesh through the local server.
- `GROK_API_KEY` enables design chat and investigation using LangChain Deep Agents. `GROK_MODEL` selects the model and defaults to `grok-4.7`.
- `COSTAR_KIT_DIR` points to the extracted kit. The property context reads records within 250 m of the site, including links to relevant scan captions.
- `MATTERPORT_API_KEY` and `MATTERPORT_API_TOKEN` verify access to a linked public Showcase model. The server sends only the verified URL to the browser.

The server binds to loopback. Credentials stay on the server. Git ignores `.env`, the CoStar kit, local data imports and ZIP archives.

The [LA Open Data legacy collision dataset](https://data.lacity.org/Public-Safety/Traffic-Collision-Data-from-2010-to-Present/d5tf-ez2w/about_data) supplies the 2022–2023 Central reporting area extract. The import requests only date, streets, and coordinates. It writes ignored aggregates containing street pairs, representative coordinates, and annual totals. It skips missing or duplicate street names, missing or out-of-area coordinates, and street pairs with fewer than three reports across the two years. The app groups reports by normalized street pair, so different street spellings may appear separately. The map uses the most frequent reported point for each pair. The ranking uses raw counts. Severity and road-user mode are unavailable in this extract.

## Crash history

After importing the LA street-pair list, run `.venv/bin/python scripts/import_ccrs.py` to fetch the 2023 and 2024 CHP crash records for the City of Los Angeles. The importer keeps a limited set of public crash fields in ignored `public/data/ccrs.json` and only includes reports matching the names of both streets at a selectable site. It normalizes abbreviations and punctuation and treats omitted directions or suffixes as possible matches. Matching street names may be ambiguous. Different spellings in the legacy list can show the same reports, so do not sum across its entries.

The panel uses a 150 ft screening distance from the reported cross street to separate junction-area records from records farther along the named primary road. Records without a usable offset are listed separately. The injury and collision-type patterns are descriptive. The legacy ranking and crash history use separate sources and periods, and their counts should not be combined.

## Aerial map and crash overlay

The explorer opens on Vexcel orthomosaic tiles, with a separately toggleable Esri place-label overlay. There is no alternate imagery fallback. It supports drag/inertial panning, wheel and pinch zoom, keyboard navigation, view-all and selected-intersection controls, and automatic resizing. The map requests native Vexcel tiles from zoom levels 10 through 20 using the documented `/v2/ortho/tile` endpoint. The optional close-up button still requests a separate Vexcel extract.

Turn on **Crash heat map** to show count-weighted concentration for the current LAPD year and street filters. The overlay uses each legacy street-pair group's representative coordinate and report count, not individual crash positions. Blurred colors are relative concentration at the current zoom, not a numeric risk score or physical crash radius. The color scale stays fixed across street searches within a period. Lower-count groups excluded by the original import remain excluded. CHP name-matched reports are not mixed into this layer, because uncertain locations and aliases could misrepresent or double-count them. The opacity slider changes only visibility, not the underlying counts.

Leaflet 1.9.4 and Leaflet.heat 0.2.0 are bundled in `public/vendor/` with their licenses. This removes the original broken stylesheet integrity reference and the runtime CDN dependency. Imagery and labels still need a network connection; Vexcel tile failures show a visible message and a retry control. The local tile route validates coordinates, rejects cross-site browser requests, only contacts Vexcel’s fixed API endpoint, and sends the key in an upstream header. At most four tile fetches run concurrently. A bounded 128-tile memory cache (at most 64 MiB) avoids repeated requests while navigating; it clears when the server stops. Responses use `no-store`, so sponsor imagery is not persisted in browser caches. Missing credentials or missing coverage do not silently switch providers. Restart the server after changing a key.
