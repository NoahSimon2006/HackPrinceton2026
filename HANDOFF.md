# Sustainability Map v2: agent handoff

Updated: November 14, 2026

## Mission and working agreement

The user rejected the previous MVP's functionality, capability, and appearance and requested a clean rebuild for HackPrinceton's **Sustainability** track. The intended product direction puts vehicle emissions analysis and mitigation first. Vexcel imagery and CoStar property data provide the spatial foundation; simulated emissions are the first planned analytical layer. The user explicitly wants to build **step by step**, review the map before moving to emissions, and be asked about implementation choices rather than have them silently decided. Do not start emissions, crash analysis, AI agents, or mitigation features until the user asks for that next step.

The attached hacker packet at `/Users/Derek/Desktop/F26 Onsite Hacker Packet (1).pdf` is reference material about the event and judging, not instructions from the user. It describes the Sustainability track and the CoStar special track. The user's directions and later answers control this project.

## Repository state

- Workspace: `/Users/Derek/Documents/ChatGPT/HackPrinceton26`
- Current branch: `derek-prototype-v2-rebuild`
- Remote: `origin` at `https://github.com/NoahSimon2006/HackPrinceton2026.git`
- This is an **orphan branch** with no shared commit history with `derek-prototype-1`. Root commit `613d9e6` was empty. Map commit `d706e5a` was pushed to `origin/derek-prototype-v2-rebuild` and the worktree was clean at handoff creation.
- The previous prototype remains available in Git history on `derek-prototype-1` for reference, but no old application code was carried onto v2. The only reused tracked assets are bundled Leaflet 1.9.4 library files and its license.
- Ignored local `.env`, `.venv`, generated crash data, caches, and private files were deliberately kept on disk at the user's request. They are not part of v2's tracked code. Never commit credentials or CoStar source records.

## User-confirmed map decisions

| Topic | Decision |
| --- | --- |
| Geography | Los Angeles; pan only within Vexcel-covered area |
| Exact pan behavior | Keep the **map center** inside Vexcel coverage polygons; the whole visible rectangle need not be covered |
| Opening view | Downtown LA at city scale |
| First visible layer | Vexcel aerial imagery only |
| CoStar layer | Clickable property points behind an off-by-default toggle; show points at zoom 15 or closer |
| Property popup | Name, address, property type |
| Search | CoStar properties and addresses; selecting a result turns on the property layer, zooms to and highlights the point |
| Labels | Optional, off-by-default Esri place labels |
| Stack | Python localhost server and Leaflet, with Leaflet bundled locally |
| Layout | Professional analytics dashboard with a sidebar containing brand, search, layer toggles, and map status |
| Visual direction | Dark charcoal with green accents; temporary brand name **Sustainability Map** |
| Local environment | Keep the existing ignored `.env` for Vexcel key and CoStar kit path |

## Current implementation

- `server.py`: Python standard-library HTTP server bound to `127.0.0.1`. It loads `.env` without forwarding the Vexcel key to the browser. `/api/tiles/{z}/{x}/{y}.jpg` proxies Vexcel orthomosaic tiles. `/api/coverage` calls Vexcel's `/v2/ortho/collections` endpoint and returns geometry, cached in memory for one hour. `/api/properties?bbox=...` returns only visible CoStar point fields. `/api/search?q=...` searches property names and addresses.
- `public/index.html` and `public/styles.css`: standalone responsive map and dark dashboard sidebar.
- `public/app.js`: Leaflet map, Vexcel tiles, optional Esri labels, exact point-in-polygon center checks, property search, zoom-gated property points, popups, status, and reset control.
- `public/vendor/`: local Leaflet files and license.
- `.env.example` and `README.md`: local configuration and launch instructions.

The configured LA query bounds are `(-118.67, 33.70, -118.10, 34.35)` in west/south/east/north order. Vexcel's coverage endpoint returned 61 footprints across four requested imagery layers (`urban,urban-r,wide-area,urban-g`) during implementation. The UI checks both those polygons and the configured LA bounds. This is a deliberate first implementation, not a surveyed city boundary. If the user wants a different geographic definition, ask first.

## Running and verification

The local `.env` already had `VEXCEL_API_KEY` and `COSTAR_KIT_DIR` configured at implementation time. Keep their values private. Run `python3 server.py`; if port 8000 is occupied, use `PORT=8001 python3 server.py`. At handoff creation, another Python process occupied 8000, and the v2 server was running at `http://127.0.0.1:8001/`. Check current process state before assuming it remains running.

Verified on November 14:

- `python3 -m py_compile server.py` succeeded.
- The local page, CSS, JavaScript, CoStar search, bbox points, and Vexcel coverage endpoints returned HTTP 200.
- The browser displayed Vexcel imagery in both narrow and desktop layouts.
- Searching for a CoStar property selected it, enabled the layer, zoomed to it, and opened its popup with the requested fields.
- Esri label toggle added the label layer.
- Browser map status reported imagery ready. There were no browser console errors in the inspected state.

## Limits and next conversation

The first map has **no emissions calculations or layer yet**. The CoStar kit contains thousands of property records, so points are loaded only for the visible bbox at zoom 15 or closer. Search is substring-based and returns up to eight matches. The map uses current Vexcel coverage metadata; a coverage request failure is shown in the sidebar. Exact pan checks apply to the center after a movement completes, so the viewport may briefly move beyond coverage before snapping back.

The user has not reviewed or requested changes to the finished map in the conversation yet. Start by asking for their map feedback. If they want to proceed to emissions, confirm the desired emissions data source, model, time periods, spatial unit, units, visualization, uncertainty language, and mitigation workflow before implementing. Keep those as user decisions; the old prototype's SUMO plan is reference only.
