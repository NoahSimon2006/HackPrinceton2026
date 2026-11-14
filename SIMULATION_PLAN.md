# Crossing Lab: traffic, idling and emissions simulation

Status: plan only. No application code has been changed for this work.

## Goal

Model how traffic flows through Central Los Angeles, find the roads where vehicles idle most and emit most, and explain why each of those roads behaves that way so a planner can decide what to change. Results feed the existing Grok design chat, so a proposed redesign can be re-simulated and compared with today's layout.

## Decisions confirmed by the user

- **Engine:** SUMO microsimulation, using its built-in emissions model.
- **Traffic demand:** public LA traffic counts where they exist, with clearly labelled assumptions filling the gaps.
- **Area:** the Central LA network covered by the current map, not a single intersection.
- **Integration:** results become evidence for the Grok design chat; no separate emissions product.

## What this can and cannot claim

The simulation will be indicative, not calibrated. Three inputs are not available as measurements and will be approximated:

- **Signal timing.** Real LADOT signal plans are not public in a usable form. SUMO will generate timing from the network, so idling at a specific signal reflects a plausible plan, not the real one.
- **Demand.** Counts cover some streets on some dates. Everything else is scaled from street class.
- **Fleet.** SUMO's emission models (HBEFA, PHEMlight) describe European vehicle classes. California's fleet model (EMFAC) is not built in. Absolute grams will be off; relative ranking between roads is the usable output.

Every result shown in the app must therefore be labelled as simulated, with the basis of the demand on that road (counted or assumed). Rankings and before/after comparisons are the product. Absolute tonnes of CO2 are not.

## Architecture

```
OpenStreetMap extract ──► netconvert ──► central_la.net.xml
LADOT counts + class defaults ──► routeSampler ──► routes.rou.xml
                                         │
                         SUMO (headless, batch) ──► edge outputs (traffic + emissions)
                                         │
                      scripts/summarise_sim.py ──► public/data/sim.json
                                         │
        server.py ──► map layer (idling / emissions) + evidence for the Grok chat
```

The baseline run is a batch job done ahead of time, like the existing `import_la.py` and `import_ccrs.py` scripts. The server only reads the summarised result. Scenario runs (a redesign) are started on demand as background jobs.

## Build steps

### 1. Install and verify SUMO

- Add `eclipse-sumo`, `sumolib` and `traci` to `requirements.txt` (the PyPI wheels ship the SUMO binaries, so no system install is needed). Confirm this works on the demo machine first; if the wheel fails, fall back to a Homebrew install.
- Smoke test: run a tiny generated grid network headless and confirm emission output is written.

### 2. Build the road network

- New script `scripts/build_network.py`. Derive the bounding box from the extent of the sites in `public/data/la.json`, padded by a few blocks so boundary roads have somewhere to send traffic.
- Download the OpenStreetMap extract for that box and convert with `netconvert`, keeping drivable roads only, guessing signals at OSM-tagged signalised junctions, and joining complex junctions.
- Keep the original OSM way IDs and street names on edges so results can be matched back to the app's street-pair names.
- Check by eye in `sumo-gui` or `netedit` that the main arterials (Figueroa, 7th, Olympic, Main, Broadway) are connected, have plausible lane counts, and are signalised. Fix the worst errors by hand in a patch file that the script reapplies, so the build stays repeatable.
- Output goes to a Git-ignored `sim/` directory.

### 3. Build traffic demand

- New script `scripts/build_demand.py`.
- Fetch LADOT traffic counts from LA Open Data for locations inside the box. The exact dataset and its fields need to be confirmed before relying on it; record the dataset ID, count dates and retrieval time.
- Match each count location to a network edge by street name and nearest position. Keep unmatched counts in a report; do not force them.
- For edges with no count, assign a default hourly volume by road class (arterial, collector, local). Store which basis each edge used.
- Generate a large set of candidate routes with `randomTrips.py`, then use `routeSampler.py` to select routes that reproduce the edge volumes.
- Model two periods to start: weekday afternoon peak and midday. The crash data already shows the afternoon peak matters at the busiest sites.

### 4. Run the baseline simulation

- New script `scripts/run_sim.py` that runs SUMO headless for each period with a warm-up period that is discarded.
- Write two edge-level outputs per aggregation interval: traffic measures (mean speed, waiting time, time loss, vehicle counts) and emissions (CO2, NOx, PM, fuel).
- Run each period with at least three random seeds and keep the mean and spread, so one lucky or unlucky run does not decide a ranking.
- Record the SUMO version, emission class, seeds and input file hashes with the output.

### 5. Summarise into app data

- New script `scripts/summarise_sim.py` producing `public/data/sim.json`.
- Per road segment: idling seconds per vehicle, share of travel time spent stopped, emissions per kilometre and per vehicle, mean speed versus free-flow speed, volume, and whether demand was counted or assumed.
- Roll segments up to the app's existing street-pair sites, by approach, so each intersection has an idling and emissions profile.
- Compute deterministic cause indicators in Python, not by the model:
  - queue reaches back to the upstream junction (spillback)
  - stops per vehicle on an approach are high while volume is moderate (poor signal progression)
  - approach demand is near or above its simulated capacity (too little green or too few lanes)
  - a turning movement blocks a through lane
  - closely spaced signals forcing repeated stops
- Rank roads by idling and by emissions per vehicle-kilometre, each with its cause indicators.

### 6. Show it on the map

- Add an "Idling and emissions" layer to the existing Leaflet map: road segments coloured by the chosen measure, with a period selector and a measure selector (idling time, CO2 per km, NOx per km).
- A ranked list of the worst roads next to the existing crash ranking, clearly a separate list from a separate source.
- Clicking a segment shows its numbers, the cause indicators, and the demand basis.
- Keep it separate from the crash heat map so simulated values are never mixed with reported crash counts.

### 7. Feed the Grok design chat

- Extend `evidence.py` so `build_evidence` adds simulation sources for the selected site: one statistic per approach and measure, each with an ID, the period, and the counted-or-assumed label. Use a distinct kind (`simulation`) so the UI and prompts can tell it apart from crash evidence.
- Add a fourth specialist to `designer.py`, a traffic-flow analyst, with a tool that returns the site's simulation profile and cause indicators. It explains why the road is prone to idling.
- Update the lead prompt: it may now discuss idling and emissions, must label them as simulated, and should flag where a crash fix and an emissions fix pull in different directions (for example, a chicane slows drivers but may add stop-and-go).
- Extend the existing number check so simulated figures quoted in reports must come from cited simulation sources.

### 8. Re-simulate a proposed design

- Map the chat's design elements to network edits for the affected junction and approaches: lane count changes, a roundabout replacing a signal, protected turn phases, speed reductions. Elements with no flow effect in the model (lighting, crosswalk markings) are passed through and reported as "not simulated".
- Run baseline and scenario on a cut-out sub-network around the site rather than all of Central LA, so a comparison finishes in about a minute. Boundary flows come from the full baseline run.
- Run as a background job with progress, cancellation and a concurrency limit, following the pattern in `investigations.py`.
- Return a before/after table per approach (idling, emissions, mean speed) to the chat and show it beside the before/after layout diagram.
- State the limits each time: traffic that would reroute outside the cut-out is not captured.

### 9. Verify

- Compare simulated edge volumes with the counts they were fitted to, and report the fit.
- Sanity-check a few well-known locations against what a local would expect at peak.
- Check that rankings are stable across seeds; drop or flag roads whose rank depends on the seed.
- Exercise failure paths: SUMO missing, network not built, scenario edit that breaks the network, cancelled run.

## Suggested order and rough effort

| Step | What you get | Effort |
| --- | --- | --- |
| 1–2 | A working Central LA network in SUMO | Half a day, most of it fixing network errors |
| 3–4 | A baseline run with emissions output | Half a day |
| 5–6 | Idling and emissions on the map, with ranked roads and causes | Half a day |
| 7 | Grok explains why a road idles | A few hours |
| 8 | Before/after re-simulation of a design | A day; the riskiest part |
| 9 | Verification | A few hours, spread across the steps |

Steps 1 to 7 give a complete demo on their own. Step 8 is the most valuable for the design chat and the most likely to overrun, so it comes last.

## Risks

- **Network quality.** OSM-converted networks often have wrong lane counts, missing turn connections and odd junction shapes. Bad junctions produce gridlock that looks like a finding. Budget time for manual fixes.
- **Guessed signals dominate idling.** Since idling is mostly a signal effect and timing is generated, per-signal results need the strongest caveats.
- **Thin count coverage.** If few counts fall inside the box, most demand is assumed and the ranking mostly reflects road class.
- **Run time.** A full Central LA peak hour may take minutes per seed. The cut-out approach in step 8 depends on boundary flows behaving sensibly.
- **Design mapping.** Translating a free-form design into network edits is fiddly; start with lane changes and roundabouts only.

## Open questions

- Is there a demo deadline? It decides whether step 8 is in scope.
- Should emissions be reported as CO2 only, or also NOx and particulates?
- Do any sponsor kits include traffic volumes or signal timing? Either would replace the weakest assumptions.
- The earlier instruction was to focus only on crashes. This plan widens the Grok chat to idling and emissions; confirm that the chat should now cover both.

## References

- SUMO documentation: https://sumo.dlr.de/docs/
- Importing OpenStreetMap networks: https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html
- routeSampler (fitting routes to counts): https://sumo.dlr.de/docs/Tools/Turns.html#routesamplerpy
- Emission models: https://sumo.dlr.de/docs/Models/Emissions.html
- Edge-based outputs: https://sumo.dlr.de/docs/Simulation/Output/Lane-_or_Edge-based_Traffic_Measures.html
- LA Open Data: https://data.lacity.org/
