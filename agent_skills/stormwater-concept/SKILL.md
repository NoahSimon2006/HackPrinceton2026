---
name: stormwater-concept
description: Investigate rainfall, terrain and mapped site constraints; draft a rain garden with honest storage and runoff assumptions.
---

Call read_rainfall_and_watershed and query_neighborhood_discovery when available. Terrain contribution is a screening signal, not routed drainage. The domain specialist saves concise cited inputs and unresolved checks at /project/reports/domain-analysis.json.

The lead reads both specialist reports and the current canonical stormwater settings. Use previous concept metrics and settings to interpret revisions, while retaining prior user constraints. Call draft_rain_garden once to compare bounded local alternatives. Propose target_area_m2, compact or linear layout, and near_selection, landscape_first or away_from_previous placement as appropriate. Explicit planner controls override agent choices. A request for a smaller or longer concept should change its physical parameters; changing wording alone is not a revision.

The local tool uses Vexcel geometry, CoStar operating/frontage context and planner markings. Explain which source fact changed a siting rule or constraint. A nearby host is provisional and does not move the chosen opportunity or establish ownership. Preserve mapped parking and access constraints. Set protect_driveway when the planner asks to protect an entrance; do not guess its position if it is not mapped.

The tool keeps contributing runoff and capture unknown unless the planner explicitly enables the marked-connected what-if, supplies a coefficient and marks a contributing area. A roof, terrain signal or nearby paved surface alone is not connected drainage. Direct rain reserves storage before external runoff. Use returned values exactly, with the event name and assumptions. Never infer infiltration, flood protection, permanent retention or construction suitability.

Publish one selected spatial concept, concise source decisions, scenario calculations and the next useful field check. Internal alternatives and earlier revisions remain inspectable with their own geometry and metrics. Prefer a sourced provisional concept over generic refusal when local checks permit one. If the tool cannot place a concept, ask its one concrete question. Exact geometry remains local; only curated calculation and decision artifacts enter agent files.
