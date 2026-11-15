# Sustainability Map — current agent handoff

Updated November 14, 2026. User instructions take precedence. Historical checkpoint reports describe the build at their review date, not necessarily today's implementation.

## Current state

Checkpoint PRs #4, #5 and #6 were merged into main at `5cc4a13`. The current local branch is `codex/checkpoint-5`, with uncommitted Checkpoint 5 implementation and a subsequent full-codebase correctness audit. No audit push or merge has been requested. See [README](README.md), [Checkpoint 5](docs/CHECKPOINT_5.md) and [audit report](docs/CODEBASE_AUDIT.md) first.

The app has two planning modes: Traffic & Emissions and Stormwater. The old Home Buyers/three-workspace instructions are obsolete. Python serves localhost on port 8001; bundled Leaflet handles the map. Vexcel imagery is the base, with optional Esri labels and zoom-gated CoStar property points. Only the map center must remain in exact sourced imagery coverage.

- Discovery uses dated historical LADOT counts and sourced terrain/rainfall/catchment context, without a model call. The old illustrative emissions layer is disabled.
- Site analysis uses one lead Deep Agent and two concurrent source specialists with sanitized activity events. Measurements and calculations run locally. Findings cite returned facts; numerical citation validation is useful but does not prove semantic or engineering correctness.
- Traffic compares bounded physical lane reallocations under official turning counts and explicitly approved generated timing. Ranking requires total CO₂ improvement, at least 98% of baseline completions, no more than 2 percentage points additional entry failures, and at most 10% regressions in delay, queues or noise energy; building/access conflicts block eligibility. Tested sites have not produced a supported recommended design.
- Stormwater compares 2–3 planner-drawn treatments using real source context and explicitly entered/confirmed coefficient, storage depth, surface connections, access and overflow. Direct rain reserves surface storage first. No infiltration, permanent retention or flood protection is calculated. Missing inputs remain unassessed. Changing physical inputs clears relevant confirmations.
- The 510 E Olympic exterior Matterport viewer is existing-site only. Proposed 3D remains disabled pending a supported 2D design, intervention coverage and verified alignment.

## Data and privacy

Keep `.env`, `private/`, `sim/`, raw CoStar data and credentials out of Git. The local CoStar kit location is configured through `COSTAR_KIT_DIR`. Select a property search result to bind its details; an arbitrary map point does not automatically inherit those details.

xAI receives approved scalar measurements, county facts, selected CoStar fields and the planner's typed question. Exact coordinates, polygons, property names/addresses, full source records, vacancy and credentials remain out of automatic model messages. Stormwater confirmation-note text remains local. Tracing stays disabled.

Source failures are not zero. Incomplete reported parking/loading categories cannot establish total spaces/docks. Historical reports quoting 25 parking spaces at Kipling or 60 at Olympic reflected known categories; the audit found other categories without counts, so current complete-total fields are unknown.

The OSM extract, road network and traffic discovery were rebuilt on November 14, 2026 (EST). The source now contains 515 restrictions. The new network builder corrected 55 lane connections affecting 52 static restrictions after the initial import; 359 represented static restrictions pass for cars/trucks/buses. Nine Main/1st runs pass exact-demand/cohort accounting with zero teleports, and its six represented restrictions survive both layouts. Both tested designs remain rejected. See [road-network verification](docs/ROAD_NETWORK_VERIFICATION.md). Main/1st and Beaudry/1st are available; Hill/1st and Beaudry/Temple fail closed on unresolved conditional restrictions. Do not claim complete real-world turn permissions. Use `scripts/build_road_network.py`, then rebuild discovery; source/network hashes and runtime turn audits prevent reuse of stale or unresolved inputs. Simulation version is `8-verified-restrictions`.

## Runtime and verification

Install `requirements.txt`; add `requirements-sim.txt` for traffic and `requirements-discovery.txt` for building discovery and runtime Stormwater terrain sampling. Run `PORT=8001 .venv/bin/python server.py`. Verify the existing listener belongs to this checkout before restarting. Reload after backend or asset changes.

Run Python unittest discovery and all six Node suites listed in README. Node is available through the supplied Node tool if absent from the shell PATH. Tests include synthetic development fixtures, which are not live benefit evidence. Current source/geometry/privacy tests do not replace real-site acceptance or browser visual review.

Browser automation is disabled in Work settings; native browser control has been intermittent and user-interrupted. Do not claim a completed desktop/narrow visual acceptance pass without actually observing it. Use CUA for UI interactions.

## Next boundary

The user requested a full logic/code audit before working on how data is portrayed. Review the audit findings and remaining artifact/acceptance gaps, then discuss presentation. Do not silently re-enable the archived scenario layer or fabricate confirmations/benefits to fill missing data. The original checkpoint plan requires explicit approval before advancing; the audit does not complete missing real-site acceptance.
