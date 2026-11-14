# Crossing Lab

Local intersection planning demo using historical collision reports for Central Los Angeles. Houston links to the H-GAC regional crash explorer.

## Run locally

From the repository root, run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

If `public/data/la.json` is missing, run `.venv/bin/python scripts/import_la.py` to download the LA collision totals.

Open [Crossing Lab](http://127.0.0.1:8000). The data import and aerial map tiles need internet access. The ranking and crossing comparison still work if map tiles are unavailable after the import.

## Credentials and data

The collision rankings and walking-time comparison work without API keys. The main aerial map requires the configured Vexcel key. Add optional settings to the Git-ignored `.env`:

- `COSTAR_KIT_DIR` points to the extracted kit. The app reads the commercial property JSONL and enum lookup from that folder, then shows counts by property type within 250 m of the selected crash point. This is coverage within the kit, not a full property inventory. An extracted kit does not need a ZIP password.
- `VEXCEL_API_KEY` supplies the main, pannable aerial map and the optional close-up image button. The server authenticates requests to Vexcel; the browser never receives the key. No imagery is saved to disk.
- `GROK_API_KEY` enables the planning brief. The app sends the public collision aggregate and calculated crossing comparison to xAI through LangChain Deep Agents when you request a brief. The model defaults to `grok-4.3` and can be overridden with `GROK_MODEL`. Review the brief against the evidence shown on the page.

Start `server.py` for these features. It binds to your computer and serves only the app files and public collision totals. Keep the original kit outside the repository. Git ignores the local `.env`, data folders, and ZIP archives.

The [LA Open Data legacy collision dataset](https://data.lacity.org/Public-Safety/Traffic-Collision-Data-from-2010-to-Present/d5tf-ez2w/about_data) supplies the 2022–2023 Central reporting area extract. The import requests only date, streets, and coordinates. It writes ignored aggregates containing street pairs, representative coordinates, and annual totals. It skips missing or duplicate street names, missing or out-of-area coordinates, and street pairs with fewer than three reports across the two years. The app groups reports by normalized street pair, so different street spellings may appear separately. The map uses the most frequent reported point for each pair. The ranking uses raw counts. Severity and road-user mode are unavailable in this extract.

The crossing comparison divides an assumed crossing length by an assumed walking speed. It does not estimate traffic delay, emissions, or crash reduction.

## Crash history

After importing the LA street-pair list, run `.venv/bin/python scripts/import_ccrs.py` to fetch the 2023 and 2024 CHP crash records for the City of Los Angeles. The importer keeps a limited set of public crash fields in ignored `public/data/ccrs.json` and only includes reports matching the names of both streets at a selectable site. It normalizes abbreviations and punctuation and treats omitted directions or suffixes as possible matches. Matching street names may be ambiguous. Different spellings in the legacy list can show the same reports, so do not sum across its entries.

The panel uses a 150 ft screening distance from the reported cross street to separate junction-area records from records farther along the named primary road. Records without a usable offset are listed separately. The injury and collision-type patterns are descriptive. The legacy ranking and crash history use separate sources and periods, and their counts should not be combined.

## Aerial map and crash overlay

The explorer opens on Vexcel orthomosaic tiles, with a separately toggleable Esri place-label overlay. There is no alternate imagery fallback. It supports drag/inertial panning, wheel and pinch zoom, keyboard navigation, view-all and selected-intersection controls, and automatic resizing. The map requests native Vexcel tiles from zoom levels 10 through 20 using the documented `/v2/ortho/tile` endpoint. The optional close-up button still requests a separate Vexcel extract.

Turn on **Crash heat map** to show count-weighted concentration for the current LAPD year and street filters. The overlay uses each legacy street-pair group's representative coordinate and report count, not individual crash positions. Blurred colors are relative concentration at the current zoom, not a numeric risk score or physical crash radius. The color scale stays fixed across street searches within a period. Lower-count groups excluded by the original import remain excluded. CHP name-matched reports are not mixed into this layer, because uncertain locations and aliases could misrepresent or double-count them. The opacity slider changes only visibility, not the underlying counts.

Leaflet 1.9.4 and Leaflet.heat 0.2.0 are bundled in `public/vendor/` with their licenses. This removes the original broken stylesheet integrity reference and the runtime CDN dependency. Imagery and labels still need a network connection; Vexcel tile failures show a visible message and a retry control. The local tile route validates coordinates, rejects cross-site browser requests, only contacts Vexcel’s fixed API endpoint, and sends the key in an upstream header. At most four tile fetches run concurrently. A bounded 128-tile memory cache (at most 64 MiB) avoids repeated requests while navigating; it clears when the server stops. Responses use `no-store`, so sponsor imagery is not persisted in browser caches. Missing credentials or missing coverage do not silently switch providers. Restart the server after changing a key.
