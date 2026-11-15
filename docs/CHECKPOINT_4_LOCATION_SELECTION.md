# Checkpoint 4 — researched location selection

Implemented November 15, 2026, committed as `26e3639` (`Add researched area opportunities and location selection`) and pushed to `origin/main`. Checkpoint 3 is `3515bd1`; the push includes the preceding checkpoints. This report concerns Checkpoint 4 of the revised implementation plan; older numbered discovery/simulation reports describe earlier milestones.

## Delivered behavior

The desktop planner starts with an environmental goal and a bounded map area. **Find locations** investigates up to three distinct opportunities, displays numbered source extents and cards, and waits for an explicit choice. The area boundary remains fixed while the user pans to inspect evidence. **Use current map area**, a new goal, cancellation or a workflow change invalidates pending browser publication. Direct property search and map selection remain available.

Each card separates environmental screening, feasibility/disruption and data readiness. The compact view shows the signal, possible intervention direction and readiness. **Investigation and evidence** expands the practical constraints, goal-specific agent assessment, numbered source citations, missing inputs and source ledger. The comparison method explains the bounded screen and its limits. Incomplete model assessment is labeled separately from successful source retrieval.

**Choose this location** saves a site project with the original goal and a canonical scouting-selection artifact. It does not launch analysis, generate a footprint or run a simulation. The site agent receives the selected opportunity context on continuation and refreshes its source evidence. Selecting A, then B, then A reopens A's existing project, preserving edits. **Show more locations** retains earlier batches and the user's choice while excluding previously grouped locations.

## Source research and comparison

`opportunity_scout.py` screens at most 50 source features per relevant layer and investigates up to three distinct locations per request. Sorting occurs before the bound. Nearby/overlapping terrain signals and connected traffic signals are grouped before history exclusions. Traffic groups retain opaque identities for their underlying segments, so a changing group or a group dissolving into individual segments cannot silently reappear in show-more.

Stormwater screening uses the expanded USGS terrain inventory. Window-edge contributions are excluded. Candidates show the terrain-inferred contribution extent and collection location, not a proposed treatment footprint. Traffic screening uses current direction-verified, non-closed slow surface-street segments and approaches from TomTom. Neither screen asserts environmental benefit: raster contribution is not verified drainage or runoff capture, and slowdown is not measured emissions or demonstrated CO₂ savings.

The ordered screen uses larger terrain contribution or stronger relative slowdown within each workflow's common source method. **Readiness never enters the ordering key.** Feasibility and disruption remain explicit practical tradeoffs; the app does not fabricate a numerical winner when intervention benefits have not been evaluated. These are opportunities to investigate, not recommended construction projects.

Every investigated location attempts Vexcel parcel/building extraction and local CoStar association/operating context. Vexcel measurements distinguish returned nearby outlines from a unique containing parcel, building coverage and area outside footprints. CoStar contributes matched property facts where an unambiguous parcel association exists, otherwise explicitly nearby uses and frontage context. Nearby properties never become assumed owners. Missing configuration, failed requests and no returned feature remain different conditions; only transient source failures receive one retry.

The screen can return fewer than three or none. Its finite-pool exhaustion is explicit; a truncated source screen suggests narrowing the area rather than offering an endless empty show-more loop. Coverage gaps preserve the direct-site shortcut.

## Native agent and persistence

`scout_agent.py` provides a native Deep Agents lead with `query_area_opportunities`, native `task` delegation to `site-evidence` and `domain-analysis`, and scoped virtual file tools. The specialists assess practical constraints/readiness and environmental opportunity concurrently. They read the trusted scouting skill, inspect curated candidate facts and save reports. The lead writes its plan, reads both current-run reports and produces cited findings relative to the user's goal. Numeric claims must occur in the cited source facts. The model cannot reorder the deterministic screen, switch the selected site or call design/simulation tools during scouting.

Only curated facts and opaque candidate identifiers reach the model. Exact coordinates, polygons, property names/addresses, raw sponsor rows and credentials remain local. Model notes cannot overwrite canonical inputs, evidence or trusted skills. Each agent is bounded to eight model calls; the investigation has a 240-second activity budget. Unstructured/failed specialist synthesis produces a partial report from available evidence; cancellation never publishes this fallback as a new shortlist.

`scout_store.py` adds local search records to the existing SQLite workspace. Immutable goal/area identity, run identifiers and guarded completion prevent superseded publication. Cancellation names the run as well as the search, so a delayed cancellation cannot stop a newer show-more request. A restart marks unfinished work interrupted and restores completed searches and choices. Water reports are preserved per run instead of being overwritten by later batches.

Traffic source facts, geometry and derived model text are never written into the durable search history. They are kept only until the provider's cache expiry, at most 60 seconds, then removed from the server's live cache and the browser's cards. Durable history retains opaque candidate/group identifiers and explicit selected-project references with a refresh notice. A user-selected point is canonical planner input. It can reopen its project after feed expiry; its earlier live observation cannot be selected as current evidence. The source is refreshed after a long research/synthesis pass, disappearing candidates are removed, and model commentary is discarded when the snapshot changes. The existing provider request budget still applies.

## Verification

- **185 Python tests and eight JavaScript test files pass.** The diff whitespace check and configured-secret scan pass.
- Real native-graph tests verify concurrent specialist work, skill reads, current report consumption, citation/numeric validation, role/tool boundaries, no design calls, cancellation and partial recovery.
- Candidate tests cover environmental ordering independent of readiness, geometry grouping, changing traffic membership, history exclusions, bounds, fewer/empty results, source expiry refresh, sponsor outages and unique parcel association.
- Store/API tests cover stale runs, cross-site writes, guarded cancellation, interrupted recovery, selection ownership, persistent history, A → B → A continuity and absence of live traffic measurements/geometry in SQLite.
- Browser-controller tests cover delayed responses after area/goal/workflow changes, cancellation of only the originating run, history restoration, compact disclosures/citations, explicit selection without automatic analysis and expiry removal.

### Observed live desktop checks

The stormwater pilot search returned three independent locations. **Show more** returned three additional distinct locations and retained the first batch and selected project. All six had real Vexcel outline evidence; four had CoStar nearby-use context and two had no nearby CoStar feature. Those gaps were preserved rather than replacing stronger environmental signals with easier-data locations. A second-batch investigation completed in about 67 seconds with 13 total model calls. The two specialists started approximately 13 milliseconds apart; site-evidence completed and domain synthesis was partial. Both current reports were consumed by the lead.

A real downtown traffic search returned three current street opportunities after refreshing measurements that changed during synthesis. It completed in about 129 seconds with 17 total model calls and overlapping specialists. The domain summary was partial; source-backed cards remained usable, and older model commentary was discarded after refresh. No live measurements are reproduced in this report or retained as an outage replay.

Both workflows accepted a browser selection and created a saved revision-1 site project with no design result and no active analysis. An actual server restart restored the selected projects, both stormwater batches and expired traffic history placeholders. The existing direct-site project also restored successfully. Desktop visual verification retained the source map and numbered opportunity extents; broad mobile QA was not part of this checkpoint.

## Remaining scope

This checkpoint completes scouting and selection. Checkpoint 5 adds the fuller stormwater design/revision loop, Checkpoint 6 deepens traffic design/evaluation, and conceptual 3D remains later work. These candidate extents are source observations, not construction designs.

Live specialist synthesis can still be partial; source research and its limits remain visible. The current screen is bounded pilot coverage, not exhaustive metropolitan optimization. Some candidates have only nearby CoStar context or missing sponsor coverage. A complete sponsor demonstration still needs a selected design in which both sponsor findings materially shape geometry or an operational constraint. No verified drainage connection, quantified capture benefit, newly eligible traffic design or current-demand emissions claim was established by this checkpoint.
