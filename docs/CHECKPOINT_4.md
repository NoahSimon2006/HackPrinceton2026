# Checkpoint 4 — traffic redesign and comparison

Review boundary: **Checkpoint 4 only. Checkpoint 5 has not started.**

Work starts from Noah's `origin/noah/checkpoint-4` handoff at `5564d4f`, on local branch `codex/checkpoint-4`. The user explicitly approved real historical turning counts with labeled generated signal timing and the stricter recommendation rules below. This does not authorize the old citywide class-default emissions layer; that layer remains disabled.

## What is connected

Select **Traffic & Emissions → Map evidence → Turning-movement counts**, select an intersection, then **Analyze site**. The lead delegates sponsor evidence and traffic inputs concurrently, then can evaluate two or three materially distinct lane reallocations in one bounded comparison. Authored dimensions are design choices, not claimed site measurements. Unsupported bus-only operation, roundabouts and jughandles are excluded. Lead tools are restricted by phase: investigate, evaluate once, then produce the cited review. Model request status and sanitized design-validation retries are visible; model reasoning and arguments are not streamed.

The local adapter resolves a versioned discovery reference to the original official LADOT PDF, verifies its SHA-256, reparses it, and checks the result against the local parsed sheet. Sheet date and counted street names must match the source record. Counts are not extrapolated to current traffic. Four verified sheets are available locally: Main/1st (2011-11-08), Hill/1st (2016-02-03), Beaudry/1st (2015-02-03), and Beaudry/Temple (2014-07-10).

Each baseline and alternative uses the same offered movements, vehicle-class allocation, study boundary, paired seeds (11, 23, 37), emissions method and signal-generation settings. Signal links are rebuilt for changed topology; actual signal plans are not known. Partial lane changes now split the simulated edge at the displayed footprint length. The previous whole-edge change versus partial-footprint mismatch is fixed.

The source [CARB EMFAC export](https://emfac.arb.ca.gov/emissions-inventory/3b6469b056eb7e5a47b65c0c96415b33d5e20812) is required at `sim/sources/emfac2025-la-2026.csv`. Rates are recomputed from its 133 rows, VMT weighted, and hashed; missing data does not fall back to constants. It represents 2026 Los Angeles running exhaust, combined here with historical demand, not measured emissions on the count date. Baseline scaling is reused for alternatives. Default SUMO vehicle behavior and mapped OSM topology still require field calibration.

## Comparison and recommendation rules

- Total CO₂ for the offered demand cohort must decrease.
- Completed demand must be at least 98% of baseline completions.
- Entry failures may increase by at most two percentage points.
- Delay and queues may worsen by at most 10%; queues are checked on every approach so an adjacent queue cannot hide behind a larger baseline queue elsewhere.
- Noise may increase by at most 10% in sound energy (approximately 0.414 dB), checked on every approach. Percentages are not applied directly to decibels.
- Mapped building conflicts, planner keep-clear/crossing conflicts, and unresolved overlapping crosswalk/driveway candidates prevent recommendation. Missing parcel/building/access evidence also prevents recommendation.
- Parcel overlap is quantified separately from buildings and remains eligible with a disclosed ranking penalty. CO₂ has the largest ranking weight (50%), followed by delay (20%), queue and parcel effects (10% each), noise and access (5% each). No candidate is forced to win.

All offered peak-hour trips are explicitly scheduled. Warm-up is 600 seconds, followed by one hour of offered demand and 900 seconds of clearance. Unentered and unfinished trips stay in the completion denominator; teleports are disabled. Emissions include entered trips from that same offered cohort through clearance, including unfinished trips. **kg CO₂ / demand hour** means emissions attributable to one hour of offered traffic, not a wall-clock instantaneous emissions rate. Entry queues outside the modeled network have no modeled exhaust; completion/entry guards prevent claiming their absence as an improvement. Delay includes entry waiting and unfinished-trip lower bounds. Queue sums the longest lane queue on each edge of the same fixed approach chain at each timestamp, then takes the time/seed maximum; merely splitting an edge cannot manufacture a queue reduction. Roadway noise is the spatial maximum of hourly mean Harmonoise edge levels across paired seeds, not a temporal peak or building exposure.

The before/after table reports each tested layout, outcome, tradeoffs, source date and official PDF. A real recommendation publishes amber geometry with matching site, revision, input revision and canonical source/input/result hash. A completed comparison with no recommendation clears any old recommended overlay. Failed or pending runs preserve the prior result with its status/stale label. Markings participate in the next run's local geometry checks and input hash. The purple development fixture remains separate.

## Actual source limitations

Live checks at all four counted sites returned Vexcel detection candidates, but the point-based property extraction returned 404 and supplied no parcel/building outlines. The configured CoStar kit has 1,581 LA properties, but only 12 properties with 17 mapped frontages. No mapped frontage is within the 110 m lookup radius of these four intersections; the closest mapped frontage property is over 1.9 km away. Those are coverage gaps, not evidence of zero buildings, no driveways, or free land.

Consequently, no real design can currently satisfy the complete sponsor-evidence requirement. The implementation can calculate and disclose a traffic comparison while honestly withholding a recommendation. **The acceptance case of publishing a real recommended footprint remains unfulfilled until both source coverage and comparison results support one.**

## Real-site verification

A reproducible Main/1st PM comparison uses the official 2011-11-08 sheet, its 5–6 PM hour, and all 5,631 counted movements. Baseline and two physical alternatives each run three paired seeds. The alternatives remove one curb-side approach lane for an eastbound 60 m curb extension and a westbound 80 m pedestrian-space reallocation. Every run has zero teleports.

| Metric | Baseline | EB 60 m | WB 80 m |
|---|---:|---:|---:|
| CO₂, kg / demand hour | 467.1 | 392.3 | 450.0 |
| Demand completed | 67.19% | 61.18% | 60.63% |
| Unable to enter | 31.95% | 37.49% | 38.00% |
| Mean delay, s / offered vehicle | 1,233.5 | 1,379.7 | 1,439.7 |

Both alternatives are rejected despite lower total emissions: they strand demand and violate delay limits; the westbound alternative also increases its worst affected approach queue by 38.78%. The oversaturated baseline itself is a calibration warning, not validated present-day operations. Adding an access keep-clear polygon over the eastbound footprint in a second local run sets its keep-clear conflict to true and publishes a different revision/input hash; the westbound footprint remains outside that constraint. Ignored local artifact: `private/checkpoint4/smoke-main-comparison.json`.

Validation: **69 Python tests and all four JavaScript controller suites pass.** Automated regression coverage includes PDF/version tampering, request identity, source privacy, unassessed metrics, physical edge splits, same-cohort accounting, exact counted demand, anti-stranding and per-approach regression gates, missing sponsor evidence, parcel/building separation, crossing/keep-clear revisions, cancellation, comparison failures, and mixed/stale UI revisions. JavaScript controller tests cover unavailable results, previous-result preservation, site switching and no-recommendation replacement. Tests with synthetic source/results are explicitly development fixtures.

Final live API verification completed in **61 seconds** with both specialist summaries, a source-validated lead review, two physical alternatives, strict rejection reasons, and no analysis error. The published comparison uses `6-fixed-boundary-queues`, all 5,631 offered vehicles, and a verified canonical identity hash. The complete local response is `private/checkpoint4/api-review.json`. A prior browser run verified the comparison table, dated source, alternative rejection panels and no-proposal state. The browser window became unavailable during the last check; final backend verification therefore used the real localhost NDJSON endpoint directly.

## Reproduce locally

Install `requirements.txt`, `requirements-discovery.txt`, and `requirements-sim.txt`; retain the ignored `.env`, OSM network, CARB source CSV and official discovery PDFs. Rebuild discovery with `scripts/build_discovery.py` and restart `PORT=8001 .venv/bin/python server.py`. Analysis has a 420-second bound at counted sites, at most three layouts and one comparison per request; subprocesses are canceled when the request is canceled. Shared scenario writes are serialized and keyed to network, source, demand, geometry, simulation version and seeds.

Exact coordinates, geometry, full CoStar records, names/addresses, and sheet filenames remain local. xAI receives approved scalar measurements, historical movements, proposed dimensions, modeled results, source facts, eligibility conclusions and generic provider URLs. Model output cannot select an ineligible winner or invent numeric benefits; verified local comparison results remain usable if synthesis fails.

Technical references: [SUMO trip accounting](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html), [SUMO emissions](https://sumo.dlr.de/docs/Simulation/Output/EmissionOutput.html), [SUMO roadway noise](https://sumo.dlr.de/docs/Simulation/Output/Lane-_or_Edge-based_Noise_Measures.html).
