# Road network and traffic verification — November 14, 2026 (EST)

## Outcome

Re-fetched the nine OSM API tiles, rebuilt the downtown road network and refreshed the traffic discovery matches. Preserved the old files under ignored `private/network-rebuild-20261115T014958Z/`. No raw sources or generated simulation files were added to Git.

The fresh extract contains **13,576 highway ways, 39,678 nodes and 515 restriction relations**, versus zero relations in the legacy extract. Complete member references are retained. The source download is a current OSM snapshot, not a reconstruction of roads on the historical count dates.

The initial SUMO 1.28.0 conversion still allowed illegal connections for **52 static restrictions** at joined junctions. `scripts/build_road_network.py` now audits original OSM way/node IDs against the converted connections, patches **55 lane connections** with vehicle-class permissions, and verifies again before publishing the network. Exempt vehicle classes and existing permissions are preserved. Conditional or complex rules are never repaired by guessing.

Final audit of all 515 source relations:

| Classification | Relations |
|---|---:|
| Represented static rules pass for modeled cars/trucks/buses | 359 |
| Represented conditional rules require time-aware support | 42 |
| Represented via-way rules require a path-based verifier | 12 |
| Malformed member sets require source/topology review | 2 |
| Movement not represented in this network | 55 |
| Modeled vehicle classes not represented | 43 |
| Via junction not represented | 2 |
| Failed represented static rules | **0** |

There are 43 conditional and 13 via-way relations in the raw extract; the table classifies only represented movements as unresolved in the network. Unrepresented rules are not counted as passes. This is a bounded source-to-network check, not proof that OSM contains every real-world sign, that lane geometry is surveyed, or that current restrictions existed on the count date.

## Runtime behavior

`sim/network-build.json` binds the downloaded source and converted network hashes. Traffic discovery binds that network hash. Each study and modified layout checks its represented restrictions again, including cached layouts. Source changes invalidate the cache. A failed, conditional, complex or malformed represented rule stops comparison with an explicit unavailable explanation.

Vehicle movement selection respects connection and lane permissions. Positive historical demand for a prohibited class/movement raises an error rather than deleting the demand or inventing another turn.

| Counted discovery site | Preparation result |
|---|---|
| Main & 1st | Ready; 6 represented static rules pass |
| Beaudry & 1st | Ready; 1 represented static rule passes |
| Hill & 1st | Unavailable: unresolved conditional restrictions in the cutout |
| Beaudry & Temple | Unavailable: unresolved conditional restrictions in the cutout |

Discovery still contains **76 historical automated-count matches and four validated manual turning sheets**. Dated counts remain viewable even at sites where a simulation is unavailable. The Stormwater snapshot was not rebuilt or changed by this task.

## Actual simulation

Used the official **Main/1st November 8, 2011** manual sheet, its **5–6 PM** peak and **5,631 vehicles**, with approved generated actuated timing. Baseline, eastbound 60 m curb extension and westbound 80 m sidewalk reallocation each ran seeds **11, 23, 37**. No model call, invented demand or published design recommendation was used.

All **nine runs** completed successfully. Each reproduced every counted turning movement, offered exactly 5,631 measured vehicles, loaded 6,570 trips including warm-up, conserved the completed/unfinished/unentered cohort, produced positive emissions and had **zero teleports**. All six represented static restrictions in the Main/1st cutout passed again in both modified networks.

| Metric | Baseline | EB 60 m | WB 80 m |
|---|---:|---:|---:|
| CO₂, kg / demand hour | 466.44 | 392.03 | 449.16 |
| Demand completed | 67.09% | 61.42% | 60.16% |
| Unable to enter | 32.07% | 37.36% | 38.46% |
| Mean delay, s / offered vehicle | 1,237.47 | 1,378.75 | 1,450.67 |

**Neither design is eligible.** Both lose more than 2% of baseline completions, increase entry failures by over two percentage points and worsen delay by more than 10%. The westbound design also exceeds the queue gate. Sponsor/placement checks were deliberately left unassessed in this network test. Lower emissions alongside stranded demand are not accepted as a benefit. The oversaturated baseline remains a calibration limitation; this verification establishes execution and accounting, not present-day operational validity.

## Reproduction and artifacts

```sh
.venv/bin/python scripts/fetch_osm.py
.venv/bin/python scripts/build_road_network.py
.venv/bin/python scripts/build_discovery.py
.venv/bin/python scripts/verify_traffic_network.py --output-dir private/traffic-network-verification
.venv/bin/python -m unittest discover -s tests -q
```

For this run, only `build_traffic()` was invoked from the discovery builder so the unrelated Stormwater snapshot remained unchanged. The default CLI rebuilds both workflows.

- Source SHA-256: `a6d067836132d5ec46ce73124f0556091e10e0698f029450f13cb28bb480b80d`
- Network SHA-256: `6ff631895b1d2a2eb341c51a0dd06c17f8085b9113c72a37a3fa99e9a69476e2`
- Traffic discovery version: `57dc8ec534f4345b`
- Simulation version: `8-verified-restrictions`; cut version: `5-verified-restrictions`
- Conversion commands/logs and before/after checks: ignored `sim/network-build/20261115T015523042345Z/`
- Final restriction audit, actual comparison, per-seed accounting and site availability: ignored `private/network-rebuild-20261115T014958Z/final/`
- Original baseline/source/discovery backup and intermediate verification: ignored `private/network-rebuild-20261115T014958Z/`

**127 Python tests pass**, including seven new regression tests for joined-junction mappings, class exceptions, internal permissions, only-turn failures, conditional-rule blocking, U-turn versus through distinction, malformed relations and source/network identity. Frontend files were unchanged in this follow-up; no new browser visual acceptance is claimed.

Implementation references: [SUMO OSM import and connection generation](https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html#lane-to-lane-connections), [SUMO connection patches and permissions](https://sumo.dlr.de/docs/Networks/PlainXML.html#connection-descriptions).
