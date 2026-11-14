# Sustainability Map implementation plan

## 1. Product brief

Build a map-first planning tool for **urban planners and traffic engineers** who want to make Los Angeles more sustainable. The product answers two questions. **Where is an intervention worth investigating?** **What could we change there, and what would it achieve?**

Planners explore evidence on the map or go directly to a site they already know. They ask the agent for an outcome in plain language. The agent investigates the site, tests alternatives with local tools, and presents **one recommended physical design** the planner can inspect and revise. The product supports early feasibility and concept design. Its value is bringing the evidence, a visible proposal, and the comparison into the same workflow.

**Remove the Home Buyers tab.** Open directly into one planner workspace with two independent modes:

| Mode | Discovery | Site-level request |
|---|---|---|
| **Traffic & Emissions** | Browse modeled tailpipe CO₂ and delay by road segment or approach. Retain NOₓ as an optional layer. | Redesign a real intersection. Consider physical treatments such as moving lane dividers, changing turn lanes, adding pedestrian islands or pinch points, and using a jughandle or roundabout where supported. Signal timing can complement a physical change. A timing-only answer does not satisfy the request. |
| **Stormwater** | Browse design rainfall, drainage context, and likely surface runoff paths or collection areas in a pilot area. | After the planner chooses a site, investigate where water may collect or pass through it. Recommend one location for a rain garden, bioswale, or other vegetated treatment. |

A planner can use either workflow independently. If a street redesign includes a planted extension, they can explicitly carry that footprint into Stormwater. Discovery uses browsable map layers and direct site selection. The user previously dropped the ranked candidate feed.

### Required outputs

1. **One recommendation** that explains what changes, why the agent selected it, what the comparison shows, material tradeoffs, and what a field team or engineer should verify.
2. **One toggleable, geographically aligned 2D proposal** on the existing map. The explanation, overlay, and metrics must refer to the same design revision.
3. **Stretch: Existing / Proposed in 3D.** Use Matterport for the existing view where an exterior scan covers the site. Render simple proposed objects from the same design used in 2D. Begin only after both core workflows pass review and the user approves the stretch checkpoint.

The intended hackathon framing is **Sustainability** as the main track and CoStar's **Inside and Out: AI for the Built World** as the special track. The demo should show how the sponsor evidence changed a planning decision.

## 2. Baseline and implementation boundaries

Use the nested checkout at `/Users/arvinmefsha/Projects/hackprinceton-2026-test1/sustainability-map-v2`. At planning time, `main` was at `557c1ae`. Verify the current branch and working tree before changing code. The parent directory is the separate **Crossing Lab** checkout. It has intersection geometry and rendering code worth inspecting for reuse. The older local `CONTEXT_HANDOFF.md` predates the most recent merges.

- Reuse the existing Python server, Leaflet map, CoStar search, Vexcel imagery and evidence tools, county hydrology queries, structured fact citations, and geometry measurement code.
- The current bundled downtown emissions pilot covers 5,333 road segments and uses historical LADOT counts on 253 matched segments. It is an illustrative screening layer. It does not measure current traffic or predict what a redesign will do.
- The current agent can investigate and recommend options in text. The implementation needs to add validated physical designs, proposal overlays, comparisons, and revision handling.
- Keep the codebase navigable. Use one main request path, named source adapters and tools, an explicit design schema, and deterministic calculations. Prefer extending the existing modules over introducing another frontend or orchestration stack.
- Preserve local credentials, licensed imagery, raw CoStar records, and other private inputs outside Git. Follow the existing provider-sharing boundary. Model-visible context can contain approved scalar summaries and source IDs. Keep credentials, raw geometry, exact site coordinates, property names and addresses, vacancy, and full CoStar records out of automatically generated model messages. Verify separately that any proposed image or scan processing is permitted for the provider receiving it.

Baseline commands from the nested checkout:

```sh
python -m unittest discover -s tests
node --test tests/planner-hydrology.mjs
```

Use the environment that has the pinned dependencies installed. See [local setup and current methodology](README.md) and [Crossing Lab](../README.md).

## 3. Data sources and sponsor requirements

**CoStar and Vexcel are core dependencies.** Both must do substantive work in each live demo workflow. A basemap, logo, link, or generic property popup alone is insufficient. The proposal should point to specific findings from both sources that affected what was placed, preserved, or flagged.

| Source | Role in the product |
|---|---|
| **CoStar — required** | Resolve the selected property and nearby properties. Use available property use, parking, loading, street frontage, and parcel references to understand access or coordinate a proposal. In traffic, use this context when checking turn, driveway, and loading impacts. In stormwater, use it to interpret the use of paved areas and preservation of property access or operations. Use only fields actually available in the kit. |
| **Vexcel — required** | Provide the aerial map and site evidence. Use semantic search for candidate scenes when useful, feature detection for candidate objects, and parcel and building outlines for georeferenced checks. Use Vexcel elevation where its coverage and resolution support the task. Imagery detections and ranked search tiles serve different purposes. |
| **Matterport — optional** | Use a relevant exterior scan to verify a site detail such as an entrance, loading area, or sidewalk when coverage and access are confirmed. Use it as the existing 3D view for the stretch goal when the scan covers the proposed change. |
| **Additional APIs and public datasets** | Use sources that materially improve the analysis. Examples include LADOT traffic counts and signal plans, OpenStreetMap topology, CARB EMFAC rates, LA County rainfall and storm-drain data, USGS elevation, and authoritative parcel or right-of-way data. Document the source, vintage, coverage, and method. Check license and sharing rules before redistributing any source or derived artifact. |

CoStar parcel references can help associate a property with a boundary from Vexcel or an authoritative parcel dataset. Aerial building footprints describe structures. Use parcel boundaries for parcel overlap, and use a separate geometry check for buildings. Report ownership only when verified.

### Evidence and source failures

- Label inputs as observed, reported, user-provided, or modeled. A scenario may use explicit, inspectable assumptions. Missing observations remain missing.
- If a source is unavailable, surface the source and the affected finding or metric. Preserve the evidence that did load. Offer a straightforward retry for a transient failure. Use another source only when it is intentionally supported, is suitable for the same question, and is clearly attributed.
- If critical inputs are missing, provide a partial assessment, mark the metric unassessed, or ask for the specific input that would unblock it. Offer manual confirmation when it can resolve an ambiguous physical feature.
- Fixtures may be used for tests and labeled development demonstrations. They must never appear as live results or stand in for failed provider calls. Keep counts, parcel boundaries, flooding, and predicted benefits grounded in returned evidence or explicitly stated scenarios.

## 4. UI and sequence

1. **Explore.** Open into Traffic & Emissions. Use a small layer picker and legend on the map. Offer CO₂ and delay by period, with optional NOₓ. Stormwater offers design rainfall, county drainage context, and likely surface runoff collection where available. Clicking a mapped feature gives a short readout with units, period or storm, and source. Keep property search and direct map selection. Retain useful existing planner deep links.
2. **Ask.** The sidebar shows the site, a suggested question, and a free-text prompt. Examples include *“Redesign this intersection for lower PM CO₂ while preserving the loading entrance”* and *“Find a place for greenery to intercept runoff from this lot.”* Neither workflow requires the user to draw inputs before the agent investigates.
3. **Watch.** Display one useful status such as **Comparing physical layouts**. The **Agent activity** toggle opens a timeline with real specialist tasks and tool calls, their outcomes, and relevant source or overlay links. Keep the panel collapsed by default. Keep the map usable while the run proceeds.
4. **Review.** Show one recommendation, a short comparison, material tradeoffs, and a map-level **Show proposal** toggle. Use distinct map styles for evidence, the proposed design, and property impacts. Place detailed sources, assumptions, and manual adjustments in expandable sections.
5. **Revise.** Accept follow-up requests or corrections such as *“Move the island back and preserve both entrances.”* Keep the last published revision visible until the new result is ready. Mark metrics stale when a design input changes and publish new metrics only for the matching revision.

Support keyboard navigation, visible focus, named controls, and readable legends. At narrower widths, keep the primary prompt and proposal accessible alongside a usable map. Switching sites or modes must not display events or results from an unrelated run.

## 5. Agent harness and output contract

Use one lead Deep Agent. It creates a short plan and delegates **site evidence** and **domain analysis** to named specialists. Run independent work in parallel. The site specialist gathers Vexcel and CoStar evidence and uses Matterport where relevant. The domain specialist investigates traffic conditions or stormwater inputs. The lead synthesizes the findings, proposes a bounded set of alternatives, calls local checks or evaluators, and recommends one.

- **Context:** Build a compact site brief containing the requested outcome, period or storm, confirmed constraints, source dates, fact IDs, and prior revision. Give specialists the relevant portion and a small tool set. Keep the information they return tied to named sources and uncertainties.
- **Virtual files:** Give each project session a virtual filesystem for the work plan, evidence index, specialist summaries, assumptions, and drafts. Use checkpointed session state for follow-ups as needed. Keep raw provider payloads and restricted fields in local services, outside files readable by the model.
- **MCP:** Verify Vexcel MCP capabilities and entitlements with the actual integration setup. Use MCP where it provides a reliable capability the product needs. Use the existing Vexcel API wrapper for supported calls that already work there. Choose one integration per capability. Keep CoStar lookup, hydrology, geometry, and simulation as small local tools unless an external integration clearly improves them.
- **Deterministic tools:** The model supplies structured design parameters. Python validates and generates geometry, measures overlaps, and runs the calculations or simulations. Keep source and tool text as data. Bound the number of candidates, model calls, simulation jobs, and run time.
- **Streaming:** Emit sanitized events with run ID, specialist, tool or stage, status, summary, and optional source or feature reference. Include actual starts, results, and failures. Keep raw payloads, prompts, credentials, and private model reasoning out of the timeline.
- **Revision contract:** A published proposal contains site and workflow IDs, evidence references, the physical design specification, existing and proposed geometry references, baseline and proposed metrics, assumptions, overlap and access findings, and the recommendation. Compute in a suitable projected coordinate system and render WGS84 GeoJSON. Tie each evaluation to the exact design and inputs used, so a changed drawing cannot inherit outdated metrics.

[Deep Agents context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering) · [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents) · [Streaming](https://docs.langchain.com/oss/python/deepagents/streaming) · [Vexcel MCP](https://vexceldata.com/platform/vexcel-mcp/mcp-get-started/)

## 6. Execution protocol for Astra

**Work on exactly one checkpoint at a time. Stop after each checkpoint and wait for explicit user approval before beginning the next.** A passing test suite is evidence for review. It does not authorize the next phase. If a checkpoint cannot pass because a source or product decision is missing, stop at the review boundary and explain the gap.

At every stop, report:

- What changed and how the user can try it.
- Which acceptance checks passed and which were not verified.
- Which data sources were used, what assumptions remain, and what is blocked.
- The next checkpoint proposed for approval.

Keep the app runnable between checkpoints. Verify with targeted tests and a short manual walkthrough where relevant. Keep commits reviewable and separate from any unrequested push or merge.

### Checkpoint 0 · Verify baseline and pick two pilot sites

- Confirm the checkout, dependencies, current tests, sponsor access, and the Deep Agents version's parallel execution and streaming interfaces.
- Inspect **Olympic Boulevard and Wall Street** as the first traffic candidate because Crossing Lab has relevant geometry and rendering. Check lane topology, turning volumes, signal information, access, and enough surrounding network to evaluate displaced queues. Choose a better-supported site if available.
- Inspect **Kipling Apartments** as a stormwater candidate because property and rainfall lookups already worked there. Verify terrain resolution and a plausible contributing surface and treatment site. Select another parcel if the evidence is stronger elsewhere.
- Document realistic traffic baseline inputs, available stormwater inputs, and data limits. If the traffic comparison must use an illustrative scenario, make that visible in the demo and confirm the choice with the user.

**Acceptance:** Produce a two-site inventory with sponsor evidence, relevant supplementary sources, data gaps, and supportable metrics. Confirm which data can be used live. **Stop for review.**

### Checkpoint 1 · Planner-only UI and shared proposal contract

- Remove the Home Buyers tab, its obsolete markup and event wiring, and any dead navigation specific to it. Open into Traffic & Emissions. Preserve Stormwater as a direct entry point.
- Consolidate the sidebar around site selection, the prompt, and the recommendation. Add the proposal toggle and collapsed details controls.
- Wire the typed proposal contract to the existing map. Use a visibly labeled fixture to verify that a selected proposal renders, toggles, and updates as a unit.

**Acceptance:** In desktop and narrow layouts, select a site, change modes, and toggle a fixture proposal. Verify the shared map, existing discovery layers, search, keyboard navigation, and useful deep links still work. **Stop for review.**

### Checkpoint 2 · One agent run with parallel evidence and activity

- Extend the existing site-analysis flow with a lead agent, scoped specialist tools, virtual files, and a run event stream. Preserve the existing measurement and citation logic.
- Verify that CoStar context and Vexcel site evidence are used to guide a review. Test Vexcel MCP access and retain the simplest working path per operation. Add targeted Matterport evidence only where it answers a real question.
- Make the live timeline expandable and clickable. Keep prior evidence available if a later step fails. Preserve the correct run identity when a user switches sites or starts a new revision.

**Acceptance:** Observe two independent specialist tasks overlap. Open a tool result from the timeline and inspect its source or map feature. Use synthetic tests for cancellation or supersession, source failure, and restricted fields. Test sponsor evidence on a real pilot site. **Stop for review.**

### Checkpoint 3 · Discovery maps

- **Traffic:** Retain the existing CO₂ and NOₓ layers. Extend the SUMO build to export stopped time or time loss for both periods. Show a meaningful metric with a documented denominator and volume context. Keep count anchors and assumptions visible.
- **Stormwater:** Display rainfall and drainage context over one pilot area. Derive likely surface flow and collection areas from suitable elevation, then check against available inlets, drains, or mapped catchments. Keep rainfall depth, inferred flow, and flood depth distinct. Use a flood-depth layer only when a suitable source or hydraulic model supports it.
- Load discovery layers without an agent call. Selecting a feature should seed a site brief with the data the planner clicked.

**Acceptance:** Browse both mode-specific layers, click a feature, and see its value or category, source, and period or event. Spot-check one traffic approach and one terrain feature against their inputs. **Stop for review.**

### Checkpoint 4 · Traffic redesign and comparison

- Implement two or three materially different physical alternatives at the traffic pilot. Start with templates whose geometry and traffic behavior can be evaluated. Add support for jughandles and roundabouts once their footprints and approach connections can be represented correctly. Keep signal timing as a supporting variable.
- Use both sponsor sources in the decision. For example, locate crossing and driveway candidates from Vexcel, then use CoStar frontage, parking, or loading context to decide which access needs to stay available. Check connectivity, crossings, keep-clear areas, and likely turning needs. Quantify parcel overlaps and flag structure conflicts separately.
- Simulate existing conditions and alternatives under comparable demand, fleet mix, time period, study boundary, and emissions method. Use paired seeds where stochastic. Track throughput, unfinished trips, and adjacent queues so a design cannot win by stranding traffic outside the measured area.
- Rank feasible alternatives with **CO₂ as the highest-weight objective**, balanced against delays, queues, noise, access, and material property impacts. Parcel overlap remains eligible and must be shown on the map and described. Agree with the user on severe-regression thresholds before tuning the ranking. If an alternative improves CO₂ but worsens another measure, show the tradeoff. If the available comparison does not support a recommendation, explain why.
- Show before and after delay, queues, tailpipe CO₂, and modeled roadway noise. Label assumed inputs. Treat roadway noise as a source estimate. Building-level exposure requires separate propagation analysis.

**Acceptance:** At a real intersection, test at least two physical layouts and publish one recommendation with matching 2D geometry and reproducible metrics when the comparison supports it. Verify that parcel overlap is disclosed and a candidate that strands demand cannot win. Revise the design after the planner adds an access constraint. **Stop for review.**

### Checkpoint 5 · Stormwater placement and capture comparison

- Investigate the selected site using county rainfall, terrain, drainage context, Vexcel imagery and georeferenced outlines, and CoStar land use and access. Identify surfaces that could contribute runoff and explain why they may connect to each candidate location.
- Compare at least two plausible layouts or placements for a rain garden, bioswale, or comparable vegetated treatment. Use footprint, slope, plausible drainage connections, and access constraints. Flag field checks for grade, soils, utilities, setbacks, and the overflow path.
- Under one named storm, calculate estimated runoff, captured volume, and excess runoff using documented contributing areas and storage assumptions. Start with a storage-only model unless suitable infiltration and routing evidence is available. Keep the county estimate separate from planner-entered rainfall. Show the calculation in a small chart and label results as screening estimates.
- Return one recommended footprint and, where supported, show contributing surfaces, likely flow direction, and the overflow path. Offer an explicit handoff from a street proposal when relevant.

**Acceptance:** Starting from a parcel or site with no intersection project, produce a sourced explanation, toggleable treatment footprint, and checkable runoff/capture/overflow comparison. Changing rainfall or contributing area updates the estimate. Verify that estimated capture cannot exceed available runoff or modeled capacity. **Stop for review.**

### Checkpoint 6 · Core release and demo verification

Run discovery → prompt → activity → proposal → revision end to end in both modes. Check desktop and narrow layouts, keyboard access, source failures, parallel activity, site switching, stale results, and the privacy boundary. Compare the rendered metrics and geometry with the published revision. Document the actual real-site checks alongside automated fixtures.

**Acceptance:** Each live workflow demonstrates a planning decision that depends on **both CoStar and Vexcel**, produces one explained design with a 2D toggle, and shows truthful comparison metrics or an explicitly unassessed outcome. The agent revises the design when a relevant constraint changes. Traffic demonstrates a physical change and CO₂-first ranking. Stormwater works independently from a site the planner chooses. **Stop for core release review.**

### Checkpoint 7 · Optional 3D comparison

Start only after explicit approval following the core review. Confirm an exterior Matterport scan covers the demo intervention and has a usable viewpoint. Register the existing view to recognizable site features. Render basic proposed 3D objects from the published 2D proposal geometry and label the result as a concept. If the scan does not cover the site, report the gap and leave this checkpoint for review.

**Acceptance:** Existing / Proposed shows the same physical change as the map, aligned to the site from comparable viewpoints. Revisions update both views. **Stop for review.**

## Technical references

- [SUMO traffic measures](https://sumo.dlr.de/docs/Simulation/Output/Lane-_or_Edge-based_Traffic_Measures.html) · [SUMO roadway noise measures](https://sumo.dlr.de/docs/Simulation/Output/Lane-_or_Edge-based_Noise_Measures.html)
- [FHWA alternatives analysis](https://ops.fhwa.dot.gov/trafficanalysistools/tat_vol3/sect6.htm) · [LADOT traffic counts](https://ladot.lacity.gov/residents/traffic-counts)
- [LA County hydrology layers](https://dpw.gis.lacounty.gov/dpw/rest/services/hydrologygis/MapServer) · [LA County catchment areas](https://dpw.gis.lacounty.gov/dpw/rest/services/PW_Open_Data/MapServer/47) · [USGS elevation data](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services)
- [EPA bioretention guidance](https://www.epa.gov/system/files/documents/2021-11/bmp-bioretention-rain-gardens.pdf) · [EPA Storm Water Management Model](https://www.epa.gov/water-research/storm-water-management-model-swmm)
