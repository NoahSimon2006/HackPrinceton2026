# Checkpoint 4 handoff: traffic redesign and comparison

Updated Saturday Nov 14, 2026, about 7:30 PM Eastern. Written for the next coding agent. Read the whole document before running anything. If something here conflicts with what is on disk, trust the disk and tell the user.

## 1. Where to start

- **Repo:** `C:\Users\Boss\Documents\HackPrinceton`, a Windows 11 machine. Remote `origin` is `github.com/NoahSimon2006/HackPrinceton2026`.
- **Your branch:** `noah/checkpoint-4`. It tracks `origin/noah/checkpoint-4`. Commit there and push there only.
- **Base:** Derek's PR #4 (`codex/checkpoints-0-1`, commit `5de2fcf`). It holds checkpoints 0–3 and is **not merged into `main`**: the merge was blocked by a tool permission check. Do not merge it yourself unless the user explicitly asks again.
- **Steps 0–5 of the Checkpoint 4 plan are done.** Start at **step 6** (section 6 below).

The product plan is `plan.md` in the repo root. This checkpoint is its "Checkpoint 4 · Traffic redesign and comparison". Earlier checkpoint reports are in `docs/CHECKPOINTS_0_1.md`, `docs/CHECKPOINT_2.md` and `docs/CHECKPOINT_3.md`. Read `plan.md` sections 1–5 and the Checkpoint 4 acceptance criteria.

## 2. Context and deadline

- HackPrinceton Fall 2026 team project: an LA sustainability planning map with Vexcel aerial imagery, CoStar property data, and a LangChain Deep Agent on xAI Grok.
- Main track Sustainability; special track CoStar "Inside and Out".
- **Submission is due 8:00 AM Sunday Nov 15. Judging is 9:30 AM, with 2-minute demos.**
- The user is Noah. Teammates Derek and Arvin push to their own branches. Derek will merge from `noah/checkpoint-4`.

## 3. User decisions (do not re-ask)

| Topic | Decision |
|---|---|
| Data rule | **No invented data.** Every input must be confirmable and traceable to a source. Missing stays missing ("not assessed"); never substitute a fixture or a guess. |
| Emissions layer | Back on for all roads, with the most accurate estimate available. Done in step 3. |
| Redesign method | SUMO simulation fed by real LADOT turning counts. Signal timing is generated and labeled as the one assumption, because LADOT does not publish timing plans. |
| Ownership | Noah owns Checkpoint 4; Derek merges from this branch. |
| Process | `plan.md` says to stop for review after each checkpoint. Finish Checkpoint 4, write its report, then stop and report to the user. |
| Pushing | Commit and push `noah/checkpoint-4` after each working step, and always before the session ends. No pull requests and no merges unless asked. |

## 4. Before you start: checks

Run these. **If one fails and the fix needs the user, ask them before building on it.**

1. `git status`: you are on `noah/checkpoint-4` with a clean tree, apart from the untracked `.claude/` and empty `README`. Never commit those two.
2. Run `git fetch origin`, then check for new commits on `origin/main` and `origin/codex/checkpoints-0-1`. If either changed, merge it into your branch and re-run the tests. If a conflict is not obviously resolvable, ask the user.
3. `.env` in the repo root. Check **presence only, never print values**:
   - `VEXCEL_API_KEY`: set.
   - `GROK_API_KEY`: set.
   - `GROK_MODEL=grok-4.7`.
   - `COSTAR_KIT_DIR`: **not set as of this writing.** The CoStar kit is a password-protected zip the user extracts themselves. If it is still unset, ask the user for the extracted folder path, the one containing `data/commercial-property.jsonl` and `schemas/enums.json`. Never ask for the zip password. Without it, CoStar access checks read "not assessed", which is acceptable but weaker for the demo.
4. Tests. Run them all and expect them all to pass:
   ```sh
   PYTHONUTF8=1 .venv/Scripts/python.exe -m unittest discover -s tests -q     # 42 tests, OK
   node tests/discovery-controller.mjs && node tests/planner-hydrology.mjs && node tests/analysis-stream.mjs && node tests/proposal-controller.mjs
   ```
5. Local data, all git-ignored and already built on this machine. If any is missing, rebuild it (see section 8):
   - `sim/dtla.net.xml`
   - `private/discovery/street.json`, which contains layers `counts` and `turning`
   - `private/discovery/water.json`
   - `private/discovery/turning-sheets.json`
   - `private/discovery/sheets/*.pdf`

## 5. What exists now

### Modules added in this checkpoint

| File | Role |
|---|---|
| `sumo_tools.py` | Finds SUMO binaries and tools from the `eclipse-sumo` wheel on Windows or macOS. `run()` raises with the log tail on failure. |
| `traffic_counts.py` | Downloads official LADOT count sheets from NavigateLA, caches them in `private/discovery/sheets/` (404s cached as `*.missing`), and parses them. `parse_manual` returns left/through/right per approach per hour, pedestrians and heavy vehicles. `parse_auto` returns 24 hourly totals per direction. A sheet is rejected unless every printed total reproduces. Count-staff names are never stored. Helpers: `find_sheet`, `load_sheet`, `peak_hour`. |
| `traffic_sim.py` | `find_node(sheet)` returns the network junction. `Study(node, lon, lat, sheet, period)` cuts a 200 m study area, sets every other junction to priority, maps approaches and movements, and builds flows from the peak hour, split into car, truck and bus by the sheet's own counts. `Study.compare({name: edge_patch_xml})` runs baseline and layouts on paired seeds (11, 23, 37), each 600 s warm-up plus 3,600 s measured. It returns delay, completion share, unable-to-enter share, max queue per approach, noise, CO₂ per hour and CO₂ per completed vehicle (scaled to CARB), plus `ASSUMPTIONS`. CLI: `python traffic_sim.py MAIN.1ST.111108-MAN.pdf`. |
| `street_design.py` | `Layout` is the bounded agent input: `kind` is `lane_reallocation`; `approach`; `lanes_removed` 1–2; `length_m` 20–200; `new_use`. `edge_patch()` builds the SUMO patch. `footprint()` builds a UTM polygon from the network's lane shapes. `sponsor_checks()` measures Vexcel parcel and building overlap and CoStar curb-cut conflicts; `None` means unassessed. `rank()` applies eligibility rules, then the CO₂-first weighted score. `evaluate(study, layouts, outlines, frontages, keep_clear)` does everything and returns a comparison dict including WGS84 `geometry`. |
| `proposal.py` | Gained the `lane_reallocation` design kind and `from_traffic_comparison(comparison, layout_name, site_id=, revision=, input_revision=, source_ids=)`, which publishes a validated `Proposal` with `development_fixture=False`. The old `fixture()` is unchanged. |
| `scripts/build_discovery.py` | Adds the `turning` layer: intersections whose official manual sheet passes its checks. 4 so far: Main & 1st (2011-11-08), Hill & 1st (2016-02-03), Beaudry & 1st (2015-02-03), Beaudry & Temple (2014-07-10). Writes the parsed sheets to `private/discovery/turning-sheets.json`, keyed by feature ID. |
| `scripts/build_emissions.py` | Rewritten. See the emissions section below. Keeps `edge_data` and `delay_metrics` because `tests/test_discovery.py` imports them. |
| `public/app.js`, `public/index.html`, `public/discovery.js` | Emissions layer re-enabled and auto-loaded in Traffic mode. The road inspector shows each road's volume basis. The turning layer has its own color, legend and popup text. |
| Tests | `tests/test_traffic_counts.py`, `tests/test_street_design.py`, `tests/test_traffic_proposal.py`. |

### Ranking rules (agreed in the approved plan)

- **Ineligible** if any of these hold:
  - completion is below 98% of baseline completion;
  - more than 2% of vehicles (or baseline plus 2 points) cannot enter;
  - the layout overlaps a mapped building;
  - the layout crosses a planner keep-clear marking.
- **Score** (relative change against baseline, negated):
  - CO₂ per completed vehicle 50%
  - delay 20%
  - max queue 10%
  - parcel overlap 10%
  - noise 5%
  - access conflicts 5%
- **Recommendation:** the best eligible layout, but only if its score is above 0. Otherwise `recommended` is `None` with a reason. Any metric more than 10% worse is listed as a tradeoff.

### Emissions layer (`public/data/emissions.json`, schema 2)

Daily volume by basis:

| Basis | Roads | Source |
|---|---|---|
| `counted` | 175 | LADOT automated 24-hour count on that street and direction |
| `same_street` | 1,077 | Inverse-distance average of counts within 1.2 km on the same street and direction |
| `class_median` | 1,861 | Median of 10 or more counted roads of the same class |
| `assumed` | 2,220 | Old class default, mostly freeways and residential streets; labeled as assumed |

- Hourly shares are medians across 16 official 24-hour sheets: midday 5.09%, PM peak 7.09% of daily traffic.
- CO₂ uses CARB EMFAC2025 2026 LA at 387.1437 g/mile; NOₓ at 0.1308 g/mile.
- Midday total: 33,679 kg CO₂/h.

### Real result so far: Main & 1st, PM peak hour 5–6 PM, counted Nov 8, 2011

| | Baseline | EB curb extension (1 of 3 lanes, 60 m) | WB bus lane (1 of 3 lanes, 80 m) |
|---|---|---|---|
| CO₂ per completed vehicle | 97.3 g | 91.8 g (−5.7%) | 103.4 g |
| CO₂ per hour | 367.3 kg | 388.9 kg | 350.3 kg |
| Completion | 67% | 75% | 60% (ineligible: strands traffic) |
| Mean delay | 873 s | 935 s | 1,181 s |

**The EB curb extension is recommended** on the CO₂-per-completed-vehicle ranking. Two identical runs reproduced every number exactly. Both layouts were published through `from_traffic_comparison` and validated, with MultiPolygon footprints (script: `private/run_layouts.py`, git-ignored). The baseline is oversaturated because OSM gives the northbound Main St approach 2 lanes for 3,044 vehicles an hour. The Vexcel aerial (2025) suggests more lanes plus a bike lane, but the approach is in shadow. **The lane count is unverified.** Do not change it without evidence. The plan allows an explicit lane override labeled user-provided if the planner confirms it.

Hill & 1st (2016) was also simulated: 75% completion before the study area was isolated. It has not been re-run since.

## 6. Remaining work, in order

### Step 6: agent and UI (about 1.5–2 h). The most important remaining step.

1. **Speed.** `Study.simulate` and `Study.compare` run SUMO sequentially: about 75 s per layout, 3.5 min for baseline plus 2. Run seeds, and the layouts within a comparison, in a `ThreadPoolExecutor`. Each run is a separate process in its own folder, so this is safe.
2. **`site_agent.py`** (read it fully first; it is Derek's carefully validated code).
   - When `workflow == "street"` and the request's `discoveryReference` points to a `turning` layer feature, load that sheet from `private/discovery/turning-sheets.json`. Build a `Study` lazily and cache it per sheet hash.
   - Replace the `read_traffic_inputs` stub with real facts made with `fact(...)` from `site_measurements.py`:
     - peak-hour vehicles per approach and movement (`basis="reported"`, source = sheet URL, `observed_at` = sheet date);
     - lanes per approach (`basis="estimated"`, OSM);
     - a signal-timing assumption fact.
   - Add a lead tool `evaluate_designs(layouts: list[Layout])` with 1–3 layouts. It calls `street_design.evaluate` with:
     - `outlines` = `evidence["outlines"]`, which the site specialist already fetches from Vexcel;
     - `frontages` = `evidence["frontages"]` (CoStar);
     - `keep_clear` = planner markings of kind `access`.
   - Convert every metric and verdict to facts so the existing citation validator in `review_schema` keeps working: numbers in the review must appear in cited facts. Emit `activity.event(...)` per layout and simulation so the timeline shows real progress.
   - Raise the lead `ModelCallLimitMiddleware` run limit (currently 4), the `Activity` deadline (180 s in `agent_activity.py`), and `server.py`'s use of it. Plan for at least 420 s.
   - Update the lead instruction text, which currently forbids implying a design was generated.
   - **Privacy:** describe approaches to the model as nb/sb/eb/wb. Never put coordinates, geometry, street names from CoStar, property names or addresses, or vacancy into model messages.
3. **`server.py`:** include `proposal` (from `from_traffic_comparison`, choosing the recommended layout, otherwise the best-scoring eligible one, otherwise none) and a compact `comparison` table in the existing `/api/site-analysis` result. Do not add a new request path; `plan.md` requires one.
4. **Frontend.**
   - `public/planner.js` `loadEvidence()`: on result, fire a map event carrying the proposal and comparison.
   - `public/proposal.js`: `validate()` currently requires `development_fixture === true`. Accept real proposals too, and keep fixture handling separate. Draw the footprint in a distinct style.
   - Show a before/after table: delay, completion, CO₂ per vehicle, max queue, noise. Also show the layouts tested with their eligibility reasons.
   - `public/index.html`: the proposal card hardcodes "DEVELOPMENT FIXTURE" and "Impact comparison: Unassessed"; make both conditional.
   - The street discovery brief text in `planner.js` (the `discoveryselect` handler) says "Do not extrapolate current demand or claim emissions benefits". Update it for turning-count selections.
   - Bump the `?v=` cache-busting numbers in `index.html` for any changed asset.
5. Extend `tests/proposal-controller.mjs` and the scripted-model tests in `tests/test_site_agent.py` (they use the `ScriptedModel` pattern) for the new tool and the real-proposal rendering.

### Step 7: revision (about 45 min)

When the planner adds a keep-clear marking ("Adjust or add map markings" → "Mark a driveway to keep clear") and re-runs, layouts crossing it become ineligible and a new revision is published. The proposal revision equals the client's input revision. The last published revision stays visible until the new one is ready; `proposal.js` already does this for fixtures.

Optional: a second layout type, a roundabout, time-boxed to 90 min. Skip it if time is short; it is acceptable to report it as not done.

### Step 8: report (about 30 min)

- Write `docs/CHECKPOINT_4.md` in the style of `docs/CHECKPOINT_3.md`: what changed, sources, method, real-site results, the acceptance checks passed and not verified, limits.
- Update `README.md`: the emissions method, the turning layer, the simulation, and Windows commands.
- Commit, push, then **stop and report to the user**.

## 7. Checkpoint 4 acceptance (from `plan.md`)

At a real intersection: test at least two physical layouts; publish one recommendation with matching 2D geometry and reproducible metrics when the comparison supports it; disclose parcel overlap; prove a layout that strands demand cannot win (unit-tested in `tests/test_street_design.py`); revise after the planner adds an access constraint. If no layout beats today's, saying so with the reason counts as a truthful outcome.

## 8. Environment notes and pitfalls

- **Shell:** Git Bash. Python is `.venv/Scripts/python.exe` (3.13.7), **not** `python3` or `.venv/bin/python` as the README says. Prefix Python with `PYTHONUTF8=1`, because the codebase reads files without naming an encoding.
- `jq` is not installed; use `node -e` or Python for JSON. Native Windows Node cannot resolve `/c/...` paths; use `C:/...`.
- **SUMO:** `.venv/Lib/site-packages/sumo/bin/*.exe`. Always go through `sumo_tools`. Setting `SUMO_HOME` silences the XML-validation warning.
- **NavigateLA throttles requests.** Sheet downloads time out often, and `fetch_sheet` uses a 12 s timeout. File naming is `PRIMARY.CROSS.YYMMDD-MAN.pdf` or `-AUTO.pdf`, with multi-word streets joined (`SANPEDRO`) and both street orders tried. Some sheets listed in the dataset are not published; Alameda & 1st manual is one. Rebuilding discovery takes about 10 minutes the first time and is fast once cached.
- **Rebuild commands,** if local data is missing:
  ```sh
  PYTHONUTF8=1 .venv/Scripts/python.exe scripts/fetch_osm.py
  .venv/Scripts/netconvert.exe --osm-files sim/sources/dtla-roads.osm --output-file sim/dtla.net.xml --geometry.remove --ramps.guess --junctions.join --tls.guess-signals --tls.discard-simple --remove-edges.isolated --no-turnarounds --output.street-names true
  PYTHONUTF8=1 .venv/Scripts/python.exe scripts/build_discovery.py
  PYTHONUTF8=1 .venv/Scripts/python.exe scripts/build_emissions.py
  ```
- Simulation outputs live in `sim/scenarios/<hash>/`. The hash includes `CUT_VERSION` in `traffic_sim.py`; bump it whenever cut logic changes.
- **Run the app:** `PORT=8001 PYTHONUTF8=1 .venv/Scripts/python.exe server.py`, then open `http://127.0.0.1:8001/#urban-planners`. This session had no browser automation, so the user must do the visual walkthrough. Say so in your report.
- **Git:** LF→CRLF warnings are harmless. End commit messages with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- **Privacy:** never print, log or commit `.env` values, CoStar records, raw provider payloads or downloaded sheets. Everything under `private/` and `sim/` is git-ignored.

## 9. When to stop and ask the user

- `COSTAR_KIT_DIR` is missing, or the path is wrong.
- A merge conflict with Derek's or Arvin's new commits is not clearly resolvable.
- You would need to change a lane count, signal assumption or ranking weight from what is agreed here.
- Any destructive git action: force-push, reset, or deleting branches.
- Checkpoint 4 is complete: stop for review as `plan.md` requires.
