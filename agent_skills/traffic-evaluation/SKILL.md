---
name: traffic-evaluation
description: Inventory current traffic evidence and verified simulation inputs; evaluate bounded street alternatives without inventing demand or emissions.
---

Call read_traffic_inputs and query_neighborhood_discovery when available. Keep current estimated speed and free-flow ratio separate from verified historical turning demand. Speed snapshots cannot supply turning ratios, volume, annual emissions or recurring congestion. Report missing inputs explicitly. As the domain specialist, produce an input inventory with exact cited facts and no recommendations or invented layout dimensions; the application saves /project/reports/domain-analysis.json. As lead, use both saved specialist reports and planner constraints to select two or three distinct supported layouts. Call evaluate_designs only once. Respect the returned feasibility checks and ranking; failed or unassessed outcomes remain so. Never rerun a simulation to seek favorable random outcomes. Keep notes within your assigned notes directory.
