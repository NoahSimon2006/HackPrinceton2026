---
name: traffic-concept
description: Turn researched road geometry and design guidance into a revisable proposed layout over the selected map, independently of traffic performance readiness.
---

Use when the lead has create_or_revise_road_concept. The main deliverable is a physical 2D road/intersection overlay for this site. Work only in Traffic; do not introduce stormwater concepts.

Read the canonical brief and constraints, and both current specialist reports. The domain report supplies anonymous road anchors, their dimensions, supported component kinds, placement descriptions, and reviewed FHWA guidance facts. The site report supplies mapped buildings, access/frontage evidence and detection candidates. Explain which site facts motivate the chosen treatment. Guidance describes design considerations, not evidence that this location has a problem or will achieve a numerical improvement.

If road anchors are ready, call create_or_revise_road_concept even when turning counts or emissions inputs are unavailable. Select a coherent combination of crossing, curb_extension, pedestrian_island, bike_lane, pedestrian_space or lane_marking components supported by those anchors. Do not make every treatment by default. For a first design use stable component IDs and components with kind and anchor_id; select dimensions/side/offset using the returned ranges. Cite at least one current road fact and one relevant road-guidance fact in evidence_fact_ids. The local compiler determines actual map geometry and checks current constraints. No model-generated coordinates, arbitrary GeoJSON, shell, remote code or host-file writes are allowed.

Road-anchor lengths follow the road; widths run across it. For a crossing on a road anchor, length is the crossing-band thickness and width spans the road. A user-marked crossing anchor already follows the desired across-road path. Respect the anchor's placement description. Do not confuse road width, crossing span and crossing-band thickness. Do not create unrelated crossings merely to produce more visible geometry.

For a revision, use changes against previous_road_concept: update or remove by exact component ID, or add a new stable ID. Omitted objects and fields remain unchanged. Translate instructions such as keeping a turn lane, shortening an extension, moving a crossing or changing one side into bounded changes; retain all unrelated choices and map markings. If a previous anchor is no longer available, explicitly re-anchor the affected component or ask the returned question; never silently shift it to another street.

Use a compiler rejection to correct the actual placement or dimensions; at most two corrections are allowed. If usable geometry is unavailable or constraints prevent placement, give the specific placement question. Do not fabricate a successful concept. After a valid compile, use its facts for dimensions and describe the proposed changes as conceptual. Do not call the design tool again to produce unrelated alternatives in the same run.

Traffic simulation is separate and optional. Only evaluate if the planner explicitly asks for quantitative comparison and the traffic tool is ready. Create the map concept first. An evaluated lane-reallocation alternative may differ from this component-based concept; never transfer its benefits or verdict to the concept. Missing counts do not block a spatially supported overlay. Emissions, delay, crash reduction, operating capacity and physical feasibility remain unassessed unless independently established for the exact design.

Finish with a concise cited review: the visible physical changes, the site facts and guidance that motivated them, and the next material check. Internal files are supporting evidence; the published overlay is the result.
