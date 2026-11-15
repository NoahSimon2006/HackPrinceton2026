# Sustainability Map implementation plan

Prepared November 14, 2026. Product decisions approved; implementation proceeds one authorized checkpoint at a time.

**Current implementation:** Checkpoints 0–3 are pushed to `main` through `3515bd1` (Checkpoint 3), following `07c57af` and `e8fed6a`. [Checkpoint 4 researched location selection](CHECKPOINT_4_LOCATION_SELECTION.md) is implemented and uncommitted on `codex/checkpoint-4-location-selection`. Goal plus area now produces researched choices and waits for selection. Historical count layers remain removed; verified sheets remain internal simulation inputs. Desktop is the priority. Checkpoint 5 has not started.

Sustainability Map will help Los Angeles urban planners and traffic engineers discover environmental improvement opportunities, choose a location, and develop an inspectable physical concept through conversation. The primary workflow begins with a goal and a map area. The agent investigates that area, presents up to three supported locations, and waits for the user to choose one before developing and evaluating designs.

Prioritize environmental impact, then feasibility and disruption. Show the information available for drafting and evaluation separately as data readiness. CoStar and Vexcel must materially affect the demonstration workflows, alongside external sources suited to traffic, drainage, terrain and environmental evaluation.

This plan incorporates the product decisions made after the existing repository handoff. It replaces the earlier assumptions that site selection must come first, that a request-generated shortlist is unwanted, and that proposed 3D requires a Matterport scan. Implementation begins only after review of the relevant checkpoint. The original planning pass changed no application code, dependencies, credentials or source datasets. The checkpoint report records subsequent implementation work.

## 1 Agreed product decisions

| Decision | Implementation consequence |
| --- | --- |
| Start with a goal and an area | Accept requests such as “Find promising stormwater improvements in this area.” Use the current map extent when no other area is specified, and show that boundary. |
| Present up to three locations | Research candidates before displaying them. Recommend a starting point, explain the alternatives, and wait for the user's selection. Return fewer when fewer are supported. |
| Preserve direct site selection | An address, property search result or explicit map location can bypass scouting. |
| Prioritize environmental impact | Assess opportunities within the selected workflow using explicit evidence and a common comparison basis where possible. |
| Consider feasibility and disruption next | Explain physical constraints, access conflicts and implementation difficulty after environmental opportunity. Preserve hard validity and safety checks. |
| Display data readiness separately | Show what can be drafted or evaluated now, what is missing, and the next useful check. Do not blend completeness into an impact score. |
| Use both sponsor layers substantively | Record which CoStar and Vexcel findings changed location selection, geometry, constraints or tradeoffs. |
| Use external information freely where relevant | Add traffic, terrain, drainage and other authoritative sources through bounded tools. Sponsor data does not need to answer every question. |
| Give the agent responsibility for investigation | Resolve locations, recover from source failures, gather additional evidence and revise designs before transferring avoidable work to the user. |
| Remove the manual placement comparison | Keep one stormwater project workflow. The agent can compare alternatives internally; users can request another option or add a constraint. |
| Make 2D the core physical artifact | Every mapped proposal must have matching geometry, explanation, assumptions and evaluation revision. |
| Support simple conceptual 3D afterward | Render the same design using basic geometry. No Gaussian splat generation is required. |
| Keep Matterport tied to the selected site | Open a tour only for a verified selected-property association and a relevant exterior/site-context description. Exclude interior-only and unspecified tours. A missing scan does not block 2D or conceptual 3D. |
| Preserve project context | Follow-ups retain the objective, selected location, constraints, prior alternatives and relevant evidence. |

## 2 Baseline and scope

The product repository on this machine is `/Users/Derek/Desktop/HackPrinceton26`. It is the repository root; references to a nested `sustainability-map-v2` checkout describe another development machine. The reviewed baseline is `main` at `99333b30c8fabd46b78a9b9fb4db38f497e520f7`. Recheck the remote and working tree when implementation begins.

The existing application uses a local Python HTTP server, plain JavaScript, Leaflet, scoped Deep Agents with Grok/xAI, deterministic geometry and hydrology tools, and SUMO traffic comparisons. Reuse this stack. A framework replacement is outside the planned work.

### Existing capabilities to retain

- Independent Traffic and Stormwater modes, property search, direct map selection and keyboard selection.
- Source facts, citations, activity streaming, cancellation and protection against late responses.
- A shared proposal contract with site identity, workflow, revision, input hash and geometry references.
- Local projected geometry calculations and WGS84 display geometry.
- An agent-generated stormwater draft and reusable event-storage calculation.
- Historical turning-count traffic comparisons and inspectable rejected footprints.
- Source/network provenance checks and strict traffic eligibility rules.
- Selected-property exterior-tour association, with the warehouse tour available only at its own property.

### Gaps identified before Checkpoint 0

At planning time, this checkout lacked Shapely/Rasterio, an absolute CoStar kit path, discovery inputs, current network provenance and the official CARB export. Those inputs have now been restored. Checkpoint 0 verifies 133 Python tests, six JavaScript test files and nine real-count simulation runs. TomTom point-flow and Orbis tile access are now verified; their application integration and expanded stormwater coverage have not been built. Consult the checkpoint report for the current source inventory and limits.

The application currently creates fresh agent context per analysis. A custom lead tool launches two real specialist agents concurrently, but delegation is fixed. No skill library is configured. Virtual files are mostly application-authored and scoped to one run. The lead's allowed tools are tightly restricted by stage. These choices support a bounded single-site review but do not yet support the proposed investigation and revision loop.

Previous live checks establish a Normandie rain-garden draft and rejected Main/1st traffic alternatives. Separate Checkpoint 0 follow-up probes establish bounded TomTom access. These checks do not establish pilot-wide flow completeness, an eligible traffic winner, expanded stormwater coverage or final desktop and narrow-screen acceptance.

### Scope boundaries

Core delivery includes both workflows, useful discovery, location selection, persistent project context, source-informed concepts, evaluations where supported and revision. A hypothetical scenario is allowed when explicit and inspectable. Unsupported real-world benefit claims are not.

Broader metropolitan coverage, automated surveyed drainage, full hydraulic flood modeling, arbitrary intersection geometry, building-level noise exposure and photorealistic reconstruction are outside the initial scope. Add a design family only when its geometry and evaluation can be supported together.

## 3 User experience

### Discover locations

The user chooses Traffic or Stormwater and writes a goal. The application captures the map extent as the search area and offers a simple way to change it. A named neighborhood can be resolved to an area when an appropriate location service is available. The agent asks for clarification only when the objective or area is too ambiguous to make useful progress.

The agent performs a broad source screen, groups adjacent signals into meaningful locations, resolves relevant properties and investigates a bounded set of candidates. It should not run expensive full design simulations for every road segment or parcel during scouting.

The interface displays up to three numbered map locations and corresponding cards. These are results of the user's current request, not a permanent predefined candidate feed. Each card contains:

- Location and mapped extent, with an unambiguous property or corridor association.
- The environmental issue or opportunity and the evidence supporting it.
- A plausible intervention direction, without implying a completed design.
- Environmental opportunity, with units and scenario when quantified, or a clearly identified qualitative basis.
- Feasibility and likely disruption, including important access or operational constraints.
- A separate readiness statement: what can be drafted or evaluated now and what remains missing.
- A short explanation of why this location appears in the shortlist.
- Actions to select the location, inspect evidence or request more candidates.

Highlight a recommended starting point when the comparison supports one. Do not invent a precise rank when the candidates' impacts are not comparable. The user can choose any supported candidate, select a different location, or ask the agent to choose explicitly.

### Develop the selected location

Selection creates or resumes a site project without discarding the area investigation. The agent develops a small set of physical alternatives, evaluates them with local tools, and presents one preferred concept when justified. Retain alternatives, their exact footprints and rejection reasons for inspection.

The main result answers: what changes, why it is placed there, what the evidence supports, how it performs under the stated inputs, what it disrupts, and what the next useful verification is. Show the physical concept prominently. Keep the source ledger and detailed calculations expandable.

Use distinct result labels: opportunity, draft concept, evaluated scenario, recommended design and tested rejected. A location that is worth investigating is not automatically a recommended intervention.

### Revise in conversation

Requests such as “Keep that loading entrance clear,” “Try a longer planting strip,” or “Show another location with less disruption” update the active project. The agent identifies which evidence and evaluations must change, preserves valid prior work and creates a new revision.

Keep the previous publication visible and labeled stale while replacement work is pending. Do not attach old metrics to changed geometry. A canceled or superseded run cannot publish into a different site or revision. Reopening a saved project restores the selected candidate, constraints and prior artifacts; live data retains its timestamp and refresh status.

## 4 Ranking and data readiness

### Environmental impact first

Use an ordered comparison rather than an opaque weighted total:

1. Establish that the candidate or design is meaningful for the requested environmental goal and does not violate known hard constraints.
2. Compare environmental opportunity or evaluated benefit on a consistent basis.
3. Where environmental outcomes are materially similar or cannot be distinguished within their uncertainty, prefer stronger feasibility and lower disruption.
4. Explain unresolved tradeoffs instead of forcing a single numerical winner.

For traffic, the primary evaluated environmental outcome is total modeled tailpipe CO₂ for the same offered demand and study period. Slow traffic is a discovery signal, not a direct CO₂ measurement or a demonstrated redesign benefit. NOₓ and other supported outcomes can appear as additional metrics.

For stormwater, initial discovery identifies potential runoff-interception opportunities. Where inputs support a scenario, compare temporary external runoff storage under the same named rainfall event. Gross ponding capacity alone is not realized capture. Do not equate storage volume with permanent retention, flood protection or water-quality improvement.

Do not combine traffic CO₂ and stormwater volume into a universal sustainability score. Each mode has its own comparison basis. Document uncertainties and model assumptions alongside the environmental assessment.

### Feasibility and disruption

Feasibility includes whether geometry fits, the terrain evidence is suitable, access can be preserved, the modeled design is supported, and major physical conflicts are unresolved. Disruption includes parking/loading changes, entrance impacts, pedestrian conflicts and likely construction or property coordination needs. Use qualitative judgments until evidence supports quantities; do not invent construction costs or permitting conclusions.

A known building collision or invalid network can block a recommendation. Unverified land permission can remain an implementation condition on a preliminary concept. The evidence needed to draw a concept is different from the evidence needed to claim evaluated performance or construction readiness.

The existing traffic ranker uses a weighted score. Preserve its hard eligibility gates, but introduce and test a versioned environmental-priority selection policy for the new workflow. Keep historical evaluations tied to their original policy. Define any numerical tie tolerance from measurement precision or simulation variability, and expose it in methodology; do not quietly adjust it to produce a winner.

### Data readiness is a separate explanation

Data readiness answers “What can we do with the information available?” It does not add a bonus or penalty to environmental impact. Example statements include:

- “Ready to draft; runoff capture needs a drainage connection assumption.”
- “Ready for a historical-demand traffic comparison; current turning demand is unavailable.”
- “Promising area; mapped parcel geometry is needed before locating a treatment.”

Track readiness by requirement: spatial geometry, property association, domain inputs, evaluation inputs and freshness. A provider outage, missing configuration, no returned feature, insufficient resolution and an ambiguous association are different states with different recovery actions.

A hypothetical high-opportunity location may have less complete data than a moderate-opportunity location. Show that distinction so the user can choose. However, missing evidence cannot support an asserted high benefit: if impact is unknown, say so and present the location as requiring investigation. Evidence uncertainty affects what can be claimed; readiness is not a hidden ranking weight.

## 5 Data integration and sponsor contribution

### CoStar

Resolve the selected property and nearby affected properties locally. Match returned identifiers and available parcel references where possible; use geospatial association only with explicit confidence and ambiguity handling. A nearby point alone does not prove a parcel match or ownership. Do not silently select a neighboring record.

Use reported property type, apartment units, gross floor area, complete parking/loading totals and usable frontage/curb-cut records to understand operations and constraints. Preserve missing values. Floor area is not roof area; apartment units are not occupied residents; parking supply is not observed demand. The current kit's actual fields and completeness determine which findings are available.

Inspect the kit schema for additional useful fields, but add them only when they change a planning decision and are permitted within the existing sharing boundary. Market, lease or tenant fields should not expand scope by default. Never infer resident change, traffic generation or vacancy trends from an unrelated snapshot.

### Vexcel

Keep aerial imagery, parcel/building extraction, feature detection and semantic imagery search. Expand point-only stormwater queries into bounded area and candidate-specific investigation. Preserve returned imagery dates, geometry quality, coverage and confidence.

Add local spatial tools that can answer questions such as which candidate regions fit a treatment, which entrances a footprint may affect, and which mapped objects overlap a proposal. Return object references and useful measured relationships to the model; keep exact raw geometry local under the existing provider-sharing policy.

Audit account access and local coverage for additional property attributes, roadway attributes and elevation. Public product availability does not establish this account's entitlement. Detection boxes and imagery-search tiles remain distinct from verified feature polygons. Do not use an unconfirmed box to claim exact paving area, crossing length or runoff contribution.

### External sources

| Need | Source direction | Required validation |
| --- | --- | --- |
| Current road slowdown and travel time | Use TomTom Traffic Flow; v4 point data and Orbis v2 tile access verified in Checkpoint 0. HERE structured area-flow access is also verified | Decode Orbis tiles, associate surface-street geometry/directions, validate fields and timestamp semantics, show confidence only where provided, confirm permitted display/storage and request budget |
| Corridor travel-time comparison | HERE Routing or the selected provider's appropriate routing product | Meaning of current, typical and free-flow baselines; direction and route consistency |
| Intersection demand | Official verified turning sheets and suitable newer counts when available | Location, count date/window, movement totals and consistency with the study network |
| Traffic geometry and emissions | Existing OSM/SUMO/CARB pipeline | Network provenance, turn restrictions, fleet source, demand conservation and comparable runs |
| Terrain and surface-flow screening | Existing USGS elevation pipeline; Vexcel terrain where verified and suitable | Resolution, acquisition metadata, terrain/surface distinction, boundaries, NoData and processing provenance |
| Rainfall and drainage context | LA County rainfall, watershed, catchment and verified drainage inventories | Scale, event meaning, coverage and whether a record establishes a site connection |
| Additional planning evidence | Relevant official collision, transit, soil or flood records | A specific decision they improve, appropriate geography/time and clear source semantics |

Choose one working traffic integration after the feasibility test. Use the provider's currently supported API version. Reuse existing adapters rather than adding duplicate REST and MCP paths for the same operation. Add bounded external search/fetch tools for authoritative research and discovery of relevant sources; quantitative map layers still need validated structured adapters.

Do not diagnose a configuration failure as a geographical data gap. Restore missing local prerequisites before concluding that a provider has no useful data for a location.

### Demonstrate the combination

For each core demo project, retain a short decision record connecting a source fact to an action. For example, Vexcel geometry may establish a possible planting region while CoStar loading context causes the design to preserve an entrance. An external terrain source then informs a runoff scenario.

The product may continue a partial investigation during a sponsor outage, but a run with no meaningful sponsor contribution cannot serve as the completed sponsor demonstration. Sponsor availability is displayed separately from environmental priority, and the application does not fabricate a contribution to satisfy the rubric.

## 6 Useful discovery maps

### Traffic

Show current estimated speed relative to the provider's reference speed, travel-time penalty when valid, update time, direction and coverage. Preserve the meaning of provider confidence and distinguish live estimates from historical or speed-limit fallbacks. A traffic tile can support display; agent ranking needs inspectable structured records.

Group connected slow segments into interpretable corridors or approaches. Avoid three cards describing the same queue. A one-time slowdown cannot be labeled recurring; recurring patterns require suitable history or observations across the claimed periods. Do not extrapolate a segment observation to an entire junction without checking association.

Retain historical count layers as supporting demand evidence. Replace vague “vehicles reported” wording with movement/count type, quantity, date and interval. Keep current conditions, historical demand and modeled redesign results visually distinct. Current flow data supplements rather than replaces turning counts.

### Stormwater

Expand from the Kipling window into a documented pilot area containing several independent properties. Build terrain with enough surrounding context to avoid presenting analysis-window boundaries as drainage features. Test a location outside the old window and a real coverage-gap case.

Display terrain-derived flow/collection candidates, relevant surface and planting-space evidence, rainfall, catchments and verified drainage infrastructure as separate layers. Include documented flooding only when an appropriate source is available, with the observed event and coverage. Do not relabel terrain indications as recorded flooding.

Feature inspection should explain the practical meaning first. A raster contribution of 901 m² should be described as an area inferred from the terrain screen, with a visual of that area and its limits, rather than a bare number or a claimed rain-garden footprint. Candidate cards should connect the area signal to an actual possible intervention location.

Version source builds and retain source hashes, resolution, dates and method. Store bulky or licensed inputs in ignored local caches. Layer viewing should not require an agent call.

## 7 Agent architecture

### Lead and specialists

Configure named native Deep Agents subagents using the installed version's supported API. Reuse existing source adapters and validation logic. Replace the fixed two-job wrapper incrementally; preserve concurrency, cancellation, partial results and sanitized activity throughout migration.

The lead owns the project goal, investigation plan, shortlist, selected location, design decisions and next action. Use a site-context specialist for sponsor association and physical constraints, a mode-specific domain specialist for traffic or stormwater evidence, and a design-review specialist when a substantive review is useful. Do not spawn a specialist for a trivial lookup.

Each assignment specifies the question, relevant project/candidate references, allowed tools, evidence already known and the required result. Specialists return concise findings, source IDs, unresolved questions and references to their reports. Keep raw research output outside the lead's routine context. The lead can request additional work after an incomplete or conflicting result.

### Skills

Create a small trusted skill library with procedures for:

1. Area opportunity scouting and candidate comparison.
2. Property association and sponsor evidence interpretation.
3. Traffic design and evaluation.
4. Stormwater concept design and event storage.
5. Proposal revision and publication.
6. Source failure diagnosis and recovery.

Add conceptual 3D instructions with the later rendering checkpoint. Each `SKILL.md` needs clear activation criteria, tool sequence, required inputs/outputs, source interpretation rules and useful recovery steps. Keep numerical formulas and hard validation in tested Python tools.

Configure `skills=` and make the library readable through the backend. Load descriptions initially, then full instructions and supporting references when relevant. Ensure tool-filtering middleware does not accidentally hide skill reads, delegation or project-file operations. Keep skill files read-only during ordinary planner work. Retrieved web pages, PDFs and provider text are evidence, not instructions that can replace those skills.

### Context and internal files

Persist a project-scoped agent thread with a supported local checkpointer. Prefer a local durable store consistent with the current deployment; verify the installed dependency interfaces before choosing its adapter. A model process restart or page reload should not erase the user's constraints.

Use an internal workspace with a brief, work plan, candidate reports, evidence index, assumptions, design specifications and evaluation summaries. Suggested virtual paths include `/project/brief.json`, `/project/plan.md`, `/project/candidates/`, `/project/evidence/`, `/project/designs/` and `/project/evaluations/`. These are virtual agent paths, not permission to browse the host filesystem.

Agents should read and update their working notes through filesystem tools. Store canonical constraints, provenance, geometry and evaluation outputs through validated application tools. A note edited by a model cannot overwrite a user constraint or turn a failed evaluation into a pass. Give concurrent specialists separate report locations and merge their results through the lead/application.

Load a compact context containing the goal, chosen candidate, current constraints, relevant source summaries and active revision. Retrieve longer reports when needed. Checkpointed state and selective retrieval provide continuity; repeatedly inserting every provider response into the prompt does not.

### Tools and recovery

Use structured tools for area queries, property resolution, source retrieval, spatial relations, candidate registration, design generation, evaluation and publication. Tool results should include status, evidence references, source dates, relevant values, artifact references and actionable gaps.

On failure, classify the problem and choose a bounded response: retry a transient error, repair a query, investigate a supported neighboring candidate, use an explicitly supported alternate source, or ask one focused question. Preserve useful prior evidence. A user-selected property stays selected unless the user asks to explore alternatives.

Allow a small configurable number of design revisions after meaningful evaluation feedback. Keep all attempts and reuse baseline inputs/caches when valid. Do not repeat stochastic runs until a favorable result appears, lower eligibility thresholds, change demand between alternatives or silently loosen constraints.

Bound source calls, model calls, candidate investigations, simulation jobs and elapsed time per stage. Persist progress when a budget is reached. Reassess the current six-model-call limit against actual workflows rather than removing limits. Cancellation must stop new work, propagate to simulations and prevent publication by obsolete runs.

### Visibility and data boundaries

The optional activity panel should show the lead's short work plan, specialist assignments, tools used, source outcomes, skill use, produced artifacts and concise decision summaries. Do not expose private model reasoning, credentials or raw restricted records.

Preserve the existing automatic provider-sharing boundary: the planner's text, approved scalar facts and source/artifact references can reach the model; raw sponsor records, exact generated coordinates/polygons and restricted property fields remain local. Apply the same checks to filesystem content, subagent messages, summaries and events. Keep external tracing disabled unless a separate reviewed configuration permits it.

## 8 Project and publication contracts

Extend the current schema rather than creating an unrelated frontend state system.

| Record | Minimum content |
| --- | --- |
| Project | Project ID, workflow, goal, search area reference, status, selected candidate, constraints, revision and agent thread reference |
| Candidate | Stable ID, site/area reference, property association status, environmental assessment, feasibility/disruption, separate readiness, evidence IDs and selection rationale |
| Evidence | Provider/source ID, feature or record reference, observation and retrieval times, units, status, quality, coverage and local artifact reference |
| Design | Candidate/site ID, design family, parameters, geometry references, constraints, assumptions and design revision |
| Evaluation | Exact design and input hash, source versions, baseline/scenario, metrics, method, policy version and eligibility reasons |
| Publication | Site/workflow/project identity, matching design/evaluation revisions, rendered geometry, explanation, status and sponsor decision references |

Support states for scouting, awaiting location selection, investigating, designing, evaluating, ready, needs input, canceled and failed. Keep request IDs separate from project identity. Changing the search area invalidates the current shortlist; selecting a new candidate prevents late work from publishing to it.

Maintain one user-facing project workflow per mode. Backend services may separate project storage, source access and computation without introducing another disconnected form-driven analysis route. Migrate the existing endpoint and controllers compatibly, then remove obsolete request fields only after callers and tests are updated.

## 9 Stormwater design and evaluation

Remove the “Compare your own placements” disclosure, “Update comparison” action, `waterDesign` request branch and dead comparison-specific UI. Retain useful geometry, terrain code and one shared event-storage function. Optional keep-clear, contributing-area and treatment-area markings become constraints on the active agent project.

The agent should investigate plausible planting space before asking for drawings. Generate designs that fit mapped constraints; retain the current circular draft as a supported starting template and add shaped beds or bioswale segments only with validated dimensions and placement checks. Available unbuilt parcel area is not automatically usable planting space.

Allow a draft with labeled design depth when spatial evidence is sufficient. External runoff calculations need an event depth, contributing area and a supported or explicitly hypothetical runoff coefficient. The agent can propose a scenario and show its assumptions; it cannot invent a confirmed connection or mark field checks complete.

Use the existing storage-only event balance:

```text
external runoff = rainfall depth × unioned contributing area × runoff coefficient
gross storage = treatment area × effective ponding depth
direct rain = rainfall depth × treatment area
temporary external storage = min(external runoff, max(gross storage − direct rain, 0))
excess external runoff = external runoff − temporary external storage
excess direct rain = max(direct rain − gross storage, 0)
```

Use consistent units, handle overlapping contributing surfaces, and prevent treatment area from being double-counted as external runoff. Show the source event separately from user scenarios. Any modeled contributing polygon or flow direction must identify its inference basis; do not draw a definitive roof-drain or overflow connection without evidence.

Compare alternatives internally and show one supported concept with its footprint, storage quantities, source-driven siting decisions and focused verification needs. Changing rainfall or physical constraints creates a new evaluation revision. Infiltration, drain-out, routed peak flow and flood protection require additional models and evidence.

## 10 Traffic design and evaluation

Use new flow discovery to identify investigation locations, then determine whether each selected site has the demand and network inputs required for quantitative redesign evaluation. A geometry-based concept may be possible before a supported simulation; label its performance unassessed.

Retain bounded lane reallocation as the first evaluated design family. Generate materially distinct alternatives based on actual approach geometry and sponsor constraints. Changing only a use label does not create a new traffic alternative. Signal timing can support a physical change. Add turn-lane modifications or pedestrian islands only after geometry, connectivity and evaluator support are implemented together. Roundabouts and jughandles remain later extensions.

Preserve the existing hard gates:

- Total same-cohort modeled CO₂ must improve.
- Completions must be at least 98% of baseline completions.
- Entry failures may increase by at most two percentage points.
- Delay, queues and noise energy must stay within the existing 10% regression limits.
- Unresolved required building, access, crossing and turn-restriction checks block recommendation.
- Teleports or invalid demand accounting invalidate the comparison.

Use equal offered demand, consistent fleet and timing assumptions, paired seeds and a common study boundary. Preserve network/source hashes and restriction audits for modified layouts and caches. A lower emissions total caused by vehicles failing to enter is not an environmental benefit.

When alternatives fail, show their footprints and reasons. The agent may diagnose and revise within its budget, while retaining failed attempts. Show all material tradeoffs, including parcel overlap; parcel overlap is an impact to disclose rather than an automatic universal rejection. An actual building conflict is a different condition.

A traffic recommendation must identify the historical count date/window, current flow evidence if used, and modeled scenario separately. Main/1st remains a useful rejection/accounting regression case. Finding an eligible real layout is an open acceptance objective, not a reason to alter the gates.

## 11 Visuals and Matterport

Make the 2D footprint available directly from each published concept and each tested traffic alternative. Use consistent styles for evidence, proposed changes, contributing areas and conflicts. Geometry, displayed metrics and narrative must belong to the same revision. Preserve accessible toggles, keyboard focus and usable narrow-screen controls.

Replace the global warehouse entry behavior with selected-site association lookup. Checkpoint 1 implements this as optional exterior context under site evidence; interior-only and unspecified tour captions are excluded. A caption cue still requires visual coverage checks. Verify a CoStar property/model match before initializing Matterport. Opening an existing view must not silently change the active project to 510 E Olympic Blvd. If the catalog contains only that scan, show it only for its matching site. Preserve on-demand loading, retry, close, focus restoration and unload on site change.

After core review, create a simple 3D scene from the validated 2D design: roads and planting surfaces, curb or island volumes, and simple surrounding building forms where dimensions are available. Label assumed heights and conceptual materials. Keep rendering separate from performance calculation.

A conceptual existing scene and proposed scene can use a shared camera even without Matterport. A real scan comparison requires verified coverage and registration to the intervention; do not claim alignment merely because both views share an address. A change to the 2D proposal invalidates its old proposed 3D scene. Gaussian splat generation is excluded.

## 12 Implementation checkpoints

Implement one approved checkpoint at a time on a separate branch from the current verified baseline. At each review, provide the change summary, runnable walkthrough, relevant tests, real-source evidence, fixture-only checks and open gaps. Keep the app runnable. Commit, push and merge only within the user's authorization. Historical checkpoint reports remain historical records.

### Checkpoint 0 Restore the baseline and verify source access

**Outcome:** A reproducible local app and an evidence-based scope for the first implementation.

Restore pinned Python dependencies, an absolute CoStar kit path, the expected discovery inputs, current network/provenance and the official fleet export. Confirm the running server belongs to this checkout. Diagnose certificate/configuration problems separately from source coverage. Keep all credentials and licensed/raw assets ignored by Git.

Audit available CoStar fields, Vexcel capabilities and Matterport associations. Perform a small authorized TomTom feasibility request, or assess HERE if TomTom is unavailable. Identify a bounded LA pilot area with meaningful sponsor and domain coverage. Verify costs and quotas before introducing paid requests beyond available entitlements.

**Acceptance:** Python and JavaScript baselines run with explicit skips where legitimate; missing inputs have concrete remedies; sponsor association works at a supported property; a traffic-provider decision and stormwater coverage inventory are recorded. This checkpoint does not claim that every source or traffic design is ready.

### Checkpoint 1 Simplify the current workflow and resolve site identity

**Status: complete.** See the [implementation and live verification report](CHECKPOINT_1_WORKFLOW.md).

**Outcome:** The existing direct-site path behaves coherently while later capabilities are built.

Remove the standalone placement UI and second stormwater request branch while preserving shared storage math and optional constraints. Add local property resolution for map/discovery selections with explicit ambiguity handling. Improve bounded Vexcel queries. Correct the global Matterport entry so it follows the active site. Preserve traffic alternatives and all revision/cancellation checks.

**Acceptance:** A supported property produces a zero-drawing draft; adding a keep-clear constraint yields a matching revision; missing runoff inputs remain unassessed; a map point cannot silently inherit the wrong property; an unsupported site cannot open the warehouse tour; Main/1st rejected footprints remain inspectable.

### Checkpoint 2A Deliver useful traffic discovery

**Status: complete.** See the [implementation and verification report](CHECKPOINT_2_DISCOVERY.md).

**Outcome:** A planner can locate and interpret a real traffic slowdown in the pilot area.

Implement the TomTom flow adapter, starting with the verified Orbis v2 tile endpoint for area/map coverage. Validate decoded geometry/direction association, units, source/retrieval timestamps, unavailable-confidence states, display layer and structured area-query tool. Any v4 point-detail enrichment needs explicit version attribution and verified association; v4 confidence must not be assumed to exist on Orbis records. Add an interpretable corridor/approach grouping. Correct count labels and retain turning-count references for simulation. Document the exact comparison baseline for any travel-time penalty.

**Acceptance:** A real surface-street response renders with correct units and time; a gap/outage is shown honestly; structured records match the map; historical counts remain available; a single snapshot is never labeled recurring congestion or measured emissions.

### Checkpoint 2B Expand stormwater discovery

**Status: complete.** See the [implementation and verification report](CHECKPOINT_2_DISCOVERY.md).

**Outcome:** The map supports investigation beyond the original Kipling terrain window.

Build and version terrain over the agreed pilot, including adequate surrounding context. Add source-supported flow/collection signals, rainfall and drainage layers; include surface and landscape evidence where validated. Improve feature explanations and expose area-query tools for the agent.

**Acceptance:** Inspect a meaningful feature outside the old window and a gap case; trace a feature to its input and method; show the difference between terrain indication, event rainfall and any verified flooding; identify several independent sites that can be investigated without inventing connections.

### Checkpoint 3 Build the persistent agent workspace

**Implemented:** see [Checkpoint 3 report](CHECKPOINT_3_AGENT_WORKSPACE.md) for verification and the live-traffic retention boundary.

**Outcome:** The lead can plan, delegate, use skills and continue a project across turns.

Introduce project state/checkpoints and configured native subagents. Load the trusted skill library and permit appropriate internal filesystem operations. Reuse deterministic tools and existing source boundaries. Add bounded recovery, activity events and resumable state. Validate actual tool names and middleware behavior against the pinned Deep Agents version.

**Acceptance:** Observe independent specialist work overlap; observe a relevant skill being read and used; inspect a saved specialist artifact used by the lead; restart/reload and continue a project with its constraints intact; verify cancellation and that restricted data does not leak through files, messages or events. Importing the SDK alone does not satisfy this checkpoint.

### Checkpoint 4 Add researched location selection

**Implemented:** see [Checkpoint 4 report](CHECKPOINT_4_LOCATION_SELECTION.md) for live verification, screening limits and partial specialist recovery.

**Outcome:** Goal plus area yields up to three useful choices and waits for selection.

Connect discovery and sponsor-association tools to the lead's scouting procedure. Investigate a bounded candidate pool, deduplicate nearby signals, apply environmental-first comparison and display feasibility/disruption and readiness separately. Store candidate provenance and the user's choice. Preserve the direct-site shortcut.

**Acceptance:** Both modes can return a supported shortlist from a real area; candidates have distinct reasons and mapped extents; fewer than three is handled; no detailed design proceeds before selection unless explicitly requested; “show more” preserves history; area changes and canceled runs cannot publish obsolete candidates. A more complete dataset cannot silently outrank a better supported environmental opportunity solely through readiness points.

### Checkpoint 5 Complete the stormwater design loop

**Outcome:** A selected opportunity becomes a sourced, revisable physical concept.

Develop candidate-specific treatment geometry, internal alternatives, explicit event scenarios and supported contributing-area handling. Use both sponsor sources to shape a siting decision. Publish the footprint, storage calculation, assumptions and field checks. Reuse persistent context for changes to geometry, access or rainfall.

**Acceptance:** Complete scout → select → draft → inspect → revise at a real site. Verify storage math, direct-rain reservation, contributing-area union and unknown capture. Show one constraint that changes the geometry and cite the sponsor evidence that influenced it. An explicit what-if can demonstrate capture, but the UI must preserve its assumptions.

### Checkpoint 6 Complete the traffic design loop

**Outcome:** A selected traffic opportunity yields inspectable alternatives and reproducible evaluations where supported.

Connect location findings to source-verified demand and valid network inputs. Generate distinct supported layouts, run consistent comparisons, implement the versioned environmental-priority selection policy and allow a bounded evidence-driven revision. Preserve every rejected footprint and its rationale.

**Acceptance:** Complete scout → select → design → evaluate → revise. Verify the hard gates and exact geometry/metric agreement. Demonstrate a valid failed alternative and pursue an eligible real alternative. If data or results prevent an eligible recommendation, record that release gap explicitly; a transparent rejection may still be shown in the demo.

### Checkpoint 7 Verify the core product and demonstration

**Outcome:** Both workflows are usable and the sponsor/agent contributions are demonstrable.

Run complete real-site journeys on desktop and narrow screens with keyboard and pointer. Exercise failures, retries, source expiry, project resume, candidate switching, cancellation, map bounds, stale results and publication races. Verify both sponsor contributions in each demonstrated workflow. Distinguish observed live checks from fixtures.

Prepare a concise demo: request opportunities, choose a location, inspect the agent's investigation, reveal a design, then revise a meaningful constraint. Retain a sourced cached replay for outages only if visibly labeled with its original time and replay status. Do not present a replay as a live provider result.

**Acceptance:** Review the walkthrough, automated results and remaining gaps. Core readiness requires useful actions and artifacts in both modes. A missing eligible traffic recommendation remains separately recorded even if the rejection demo is accepted for presentation.

### Checkpoint 8 Add conceptual 3D

**Outcome:** The same published design can be inspected in a simple 3D scene.

Begin after core review and explicit approval. Select a suitable rendering approach for the existing frontend, define a local coordinate origin and create basic scene objects from the proposal geometry. Support comparable existing/proposed conceptual views and update them from the same revision. Integrate a matching Matterport view only where registration and coverage are verified.

**Acceptance:** Scene geometry agrees with 2D; units, origin and camera alignment are checked; revisions update or invalidate the scene; unsupported scans stay unavailable; a site without Matterport can still show a properly labeled conceptual 3D proposal.

## 13 Code ownership and migration map

The following are intended implementation areas, not changes made by this plan. Add focused modules only where responsibility becomes clearer; avoid another orchestration or frontend stack.

| Area | Existing code to extend |
| --- | --- |
| Project API, configuration and property lookup | [server.py](../server.py); a focused project-state module if needed |
| Lead, native delegation, skills and context | [site_agent.py](../site_agent.py), [agent_activity.py](../agent_activity.py); proposed `agent_skills` directory |
| Sponsor extraction and spatial facts | [site_evidence.py](../site_evidence.py), [site_measurements.py](../site_measurements.py) |
| Discovery and external traffic adapter | [discovery.py](../discovery.py), [build_discovery.py](../scripts/build_discovery.py); a focused provider adapter |
| Stormwater source and design tools | [hydrology.py](../hydrology.py), [terrain_discovery.py](../terrain_discovery.py), [stormwater_terrain.py](../stormwater_terrain.py), [stormwater_design.py](../stormwater_design.py), [stormwater.py](../stormwater.py) |
| Traffic design, evaluation and selection | [traffic_analysis.py](../traffic_analysis.py), [street_design.py](../street_design.py), [traffic_sim.py](../traffic_sim.py), [traffic_counts.py](../traffic_counts.py) |
| Shared publication contract | [proposal.py](../proposal.py), [proposal.js](../public/proposal.js) |
| Search area, shortlist and project UI | [index.html](../public/index.html), [planner.js](../public/planner.js), [discovery.js](../public/discovery.js), [analysis-stream.js](../public/analysis-stream.js), [app.js](../public/app.js), [styles.css](../public/styles.css) |
| Existing tour and future scene lifecycle | [site_view.py](../site_view.py), [site-view.js](../public/site-view.js); a scene renderer at Checkpoint 8 |

When implementation is approved, synchronize the repository's next plan, conversation handoff and README with these decisions. Keep older numbered checkpoint reports as history. Remove obsolete claims about a mandatory first site selection, no request-generated shortlist, the manual placement flow and a scan prerequisite for conceptual 3D.

## 14 Verification strategy

Use targeted automated checks for consequential behavior and real-site walkthroughs for source usefulness and interface acceptance. Synthetic fixtures establish deterministic behavior, not real environmental benefit.

| Concern | Required verification |
| --- | --- |
| Ranking | Environmental ordering, feasibility/disruption tie handling, unknown impacts and no hidden readiness weight |
| Candidate selection | Deduplication, bounded search, stable IDs, fewer-than-three results, user choice and obsolete-run isolation |
| Source handling | Correct units/time/direction, configuration versus outage versus empty response, provenance, identity and provider fallback semantics |
| Sponsor contribution | A returned fact from each sponsor demonstrably changes a decision in each core demo |
| Agent behavior | Real delegation, relevant skill reads, scoped context, filesystem artifact use, recovery and continuity after reload/restart |
| Stormwater | Direct rain consumes storage first; capture cannot exceed runoff or available capacity; overlapping areas are not double-counted; unknowns remain unknown |
| Traffic | Same demand/cohort, strict gates, source/network identity, restrictions, paired runs and no favorable result from stranded demand |
| Publication | Geometry, values, narrative, source versions and policy share a revision/hash; invalid geometry cannot partly publish |
| Privacy | Model messages, virtual files, subagent results and events respect the existing allowlist |
| Interaction | Keyboard/pointer access, narrow screens, cancellation, stale states, candidate/site switching and selected-site Matterport lifecycle |

Run the existing baseline from the repository with the correct environment:

```sh
cd /Users/Derek/Desktop/HackPrinceton26
.venv/bin/python -m unittest discover -s tests
/Users/Derek/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test tests/*.mjs
git diff --check
```

Add focused tests for new contracts and recovery behavior. Re-run broader checks when changes or failures justify them. Do not substitute controller tests for a real browser walkthrough or a library import for an observed agent action.

## 15 Decisions to resolve through implementation evidence

The agreed product direction does not depend on choosing every provider or storage library now. Resolve the following in their owning checkpoints:

- Exact pilot geography and source coverage after restoring the local inputs.
- TomTom Orbis decoding and coverage, any v4 detail association, and permitted display/storage/refresh policy. TomTom is selected after successful access checks; HERE is also authenticated and remains an optional structured area-flow alternative.
- Additional Vexcel capabilities actually available to the team's credentials.
- CoStar association quality and which complete operational fields exist at candidate sites.
- Supported local checkpoint storage and run budgets for the installed Deep Agents version.
- Comparison uncertainty and tie handling that can be justified by the evaluator.
- A real traffic site/design capable of passing the unchanged eligibility gates.
- The simple 3D renderer after core review.

Do not reopen the agreed defaults during routine implementation: up to three locations, user selection, environmental priority, separate readiness, meaningful sponsor use, external evidence, unified stormwater workflow, persistent agent context and scan-independent conceptual 3D.

## 16 Sources and governing context

- User decisions in this conversation govern the product direction and the priority order.
- [Current conversation handoff](https://github.com/NoahSimon2006/HackPrinceton2026/blob/99333b3/docs/CONVERSATION_HANDOFF.md) and [earlier next implementation plan](https://github.com/NoahSimon2006/HackPrinceton2026/blob/99333b3/docs/NEXT_IMPLEMENTATION_PLAN.md) establish the baseline; the revised decisions above supersede conflicting product assumptions.
- [Onsite hacker packet](</Users/Derek/Desktop/F26 Onsite Hacker Packet (1).pdf>), pages 13–14: at least two sponsor layers with value from their combination; data use 30%, agentic depth 30%, usefulness 25%, demo/polish 15%. Page 16 lists the Deep Agents track. The packet is requirements evidence, not authority to take unrelated actions.
- [Deep Agents subagents](https://docs.langchain.com/oss/python/deepagents/subagents), [skills](https://docs.langchain.com/oss/python/deepagents/skills), [context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering) and [backends](https://docs.langchain.com/oss/python/deepagents/backends). Confirm exact interfaces against pinned `deepagents==0.7.38` during implementation.
- [TomTom flow data](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/flow-segment-data), [TomTom current integration guidance](https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-flow/traffic-flow-service), [HERE Traffic Flow](https://docs.here.com/traffic-api/docs/flow) and [HERE route durations](https://docs.here.com/routing/docs/routing-v8-duration).
- [Vexcel property attributes](https://vexceldata.com/intelligence/elements/property-attributes/), [roadway attributes](https://vexceldata.com/intelligence/elements/roadways/) and [elevation](https://vexceldata.com/products/digital-surface-models/). These describe product capabilities, not verified entitlement or site coverage.
- [USGS elevation products](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services) and [LA County public layers](https://dpw.gis.lacounty.gov/dpw/rest/services/PW_Open_Data/MapServer).
