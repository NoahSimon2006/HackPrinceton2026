# Sustainability Map next implementation plan

Read the [conversation handoff](CONVERSATION_HANDOFF.md) for the current feature and verification baseline. The [original plan](../plan.md) and checkpoint reports are historical. This plan records the work that remains after the Checkpoint 1 and 5 merge at `643e5ac` and the decision to retire the standalone stormwater comparison.

## How to work through this plan

- Implement only the checkpoint the user approves. Check the working tree and GitHub `main`, then branch from current `main`. Keep ownership of any existing local edits clear.
- Reuse the planner UI, scoped Deep Agents harness and local source and geometry tools. Keep the code understandable to the team. Add a provider integration or new abstraction only when it meets a specific need.
- CoStar and Vexcel must affect site decisions in both core workflows. Cite the actual source fact that shaped placement, access, conflicts or tradeoffs. Matterport is useful with a verified exterior view. Provider limits stay visible as unavailable or unassessed.
- Preserve a single question-to-evidence-to-proposal workflow per mode. A supported result has a cited explanation, a toggleable 2D footprint, and values and reasons tied to that geometry and revision. The agent can ask one focused question if it cannot proceed. Keep optional tool-call and progress visibility.
- At each checkpoint, run relevant automated checks and a real-site test where the source coverage supports it. Report the commit, the walkthrough, missing evidence and any part that was verified with a test fixture. **Stop for review before starting the next checkpoint.** Merge or push when the user requests it.

## Checkpoint A · Retire the standalone placement comparison

**Goal:** Make **Analyze site** the normal Stormwater route from a question to a mapped rain garden. This is the immediate next implementation task.

1. Remove the **Compare your own placements** disclosure and **Update comparison** action from `public/index.html`, `public/planner.js` and related styles. Preserve the agent question, rainfall context and site evidence. Place optional shape adjustments with the rest of the site constraints.
2. Remove the separate `waterDesign` request, confirmation form handling, comparison routing, standalone charts and conditional manual-comparison publication. Trace callers in `server.py`, `site_agent.py`, `stormwater.py`, `proposal.py` and `public/proposal.js`. Remove dead code and update tests that exercised the removed route. Keep reusable terrain and geometry code that still has a job.
3. Keep the shared `event_storage()` math in one local implementation. The draft can report gross ponding storage from its own geometry and a labeled design depth. Compute external runoff and its temporary storage only when an event depth, contributing area and explicitly supported or hypothetical runoff coefficient are available. Deduct direct rain from available storage first. Keep excess direct rain and excess contributing runoff distinguishable.
4. Keep the draft's optional keep-clear and contributing-area markings. A proposed treatment-area marking can serve as a siting constraint on the same draft. The agent should look for plausible mapped placement and access evidence before asking the planner to draw. An unresolved driveway location or inadequate site evidence should produce a specific question or gap.
5. Preserve traffic's tested alternatives, toggle, comparisons and strict ranking. Preserve both workflows' site identity, input hashes, stale state and cancellation logic. Update the current README to match the resulting UI while retaining checkpoint write-ups as development history.

**Review gate:** Select **Normandie** in Stormwater. Analyze the site with zero drawings and see a real draft, footprint area, ponding storage and explanatory evidence. Revise with a keep-clear constraint and verify the new footprint and revision agree. Confirm capture remains unassessed until the necessary scenario inputs exist. At **Main and 1st**, inspect a tested traffic footprint and rejection reasons. Confirm the old disclosure and second request path are gone.

## Checkpoint B · Expand sourced stormwater discovery

**Goal:** Help a planner identify areas worth investigating and move from a discovery feature to an independent stormwater draft. The current terrain layer is focused around Kipling. Expand it deliberately from that pilot.

1. Define a larger pilot area with verified elevation and county coverage that includes multiple independent test parcels. Start with a bounded area that can be built, versioned and verified using the existing discovery pipeline. Record which geography is covered, when sources were observed or published and the resolution of each layer.
2. Reuse the USGS bare-earth elevation build and source checks in `scripts/build_discovery.py`, `terrain_discovery.py` and the verified terrain sampler where useful. Retain real flow-path and collection candidates from terrain. Identify raster edges, gaps, flats, sinks and NoData. Report the terrain signal in its own units and retain the acquisition and metadata limits.
3. Keep county design rainfall, watershed or catchment context, and terrain-derived collection as distinct layers. Research county drainage, storm-drain inventory, observed flooding or gauge data where it can resolve a specific planning uncertainty. Link verified records at the appropriate scale. Keep observed incidents, terrain indications and a rainfall design event individually labeled.
4. Make the map self-explanatory. For a selected feature, show what it represents, the source and coverage, the period or event, the units, and the main uncertainty. Let the agent investigate the selected area or site on request. Use Vexcel surfaces and CoStar access and operations to turn area evidence into a site-specific draft. Leave the drainage connection or catchment unknown where grades, downspouts, inlets or overflow paths are missing.
5. Verify one plausible result outside the original Kipling window and a gap case. Publish the geographic extent and method with the discovery snapshot. Reproducible source builds belong in the repo. Keep bulky source files and licensed data in the local ignored cache.

**Review gate:** A planner can identify a sourced stormwater signal outside the original pilot, explain what it means, select a real property, and receive either a defensible draft or the specific evidence needed next. The map distinguishes event rainfall, terrain flow and verified flooding.

## Checkpoint C · Improve surface-street traffic discovery

**Goal:** Show where a planner should investigate backups or slow travel, then connect that context to a supported physical design comparison.

1. Clarify the existing LADOT UI first. Replace vague “vehicles reported” copy with a count interval and units, such as **5,631 turning movements in the counted PM peak hour**, with sheet date, location and time window. Keep summary counts, turning movements, current speed, estimated delay and modeled CO₂ distinct.
2. Run a small provider feasibility check for a known LA surface street. INRIX was discussed as useful if access is available. Check **TomTom Traffic Flow** first among the alternatives for segment-level current speed or delay against free-flow or typical speed, then consider **HERE Routing** if a route-level travel-time test fits better. Consider **Caltrans PeMS** for freeway or approach context where its sensor coverage helps. Verify current account access, quotas, cost, permitted display/storage and attribution, surface-street coverage, timestamps, and the actual returned fields from provider docs and a live request before choosing one. Keep the integration to a single working path.
3. Add one useful, clearly labeled delay/speed layer only if the selected source provides it. Preserve native timestamps and coverage and validate roadway/approach association. A user should be able to see where and when the measurement applies. Report whether the signal is current, historical, estimated or modeled. Expand only after the pilot is readable. A live map signal does not supply turning volumes or emissions factors.
4. Support an explicit area question such as “Where does this area back up?” by querying the sources for the user-selected map extent and disclosing the observed period and coverage. Let the planner select the result to investigate. Use the analogous pattern for a user-requested search for stormwater problem areas when Checkpoint B supplies credible evidence.
5. Validate a candidate project with the existing local comparison. Use verified counts and a documented timing assumption, and preserve the same offered demand and restrictions for baseline and alternatives. Require interpretable coverage, access and building checks. Search area-bounded Vexcel evidence and match CoStar frontage/properties locally. Parcel overlap is a reported impact. An actual building conflict or missing required access data can block a recommendation.
6. Keep CO₂ as the highest priority while protecting throughput, delay, queue, noise, pedestrian crossings and access. Test physical changes that the tools can represent and document the supported set. For a later design-type extension, add geometry and comparison support together for one meaningful change such as a designated turn-lane modification or pedestrian island. Roundabouts or jughandles need topology, turning and safety validation on a supported site. Timing changes can accompany a physical design.

**Review gate:** A planner can read what a real count or delay layer means and select an investigation site. The existing simulator publishes the exact tested physical footprints, values, assumptions and rejection reasons. Demonstrate one eligible real layout when sponsor evidence and simulation support it. If a live source or the ranking prevents an eligible result, record the reason and keep it open as an acceptance gap. A lower CO₂ value from stranded demand cannot qualify.

## Checkpoint D · Make Existing Matterport relevant to the selected site

**Goal:** Connect the existing exterior walkthrough to verified property/model associations, with evidence that the scan actually covers the intervention.

1. Audit the CoStar kit and approved Matterport associations. The current one-address walkthrough at **510 E Olympic Blvd** uses a verified CoStar-to-model link. Preserve that as a known case while finding out whether the team has other exterior scans with usable coverage. Validate selected property identity and model association in `site_view.py` before the browser initializes a view.
2. Let a selected site open Existing only when a relevant association is supported. Explain the coverage or available viewpoint so users can tell what the scan shows. Use it for an actual planning check where appropriate, such as sidewalk/loading or entrance context. Treat a missing or unverified association as unavailable for that site.
3. Keep the view on demand and preserve close, retry, focus restoration and cancellation on site change. Respect the way the team is authorized to use the scan. Verify actual exterior coverage and viewer capabilities before relying on street-level walkthroughs or Gaussian splats.

**Review gate:** Show the validated Existing tour at a supported property, close it and confirm a site change unloads it. Select an unsupported site and confirm the UI identifies the coverage gap. If the catalog has only the existing approved scan, document that limit.

## Checkpoint E · Core release and hackathon demo

**Goal:** Show repeatable evidence-to-proposal-to-revision loops and record the remaining gaps before considering 3D rendering.

- Verify a real stormwater draft using a supported CoStar property and Vexcel geometry. Show a constraint change, and state which assumptions make any storage scenario possible. Use credible evidence or an explicitly labeled what-if scenario when demonstrating capture. Explain site checks and where field verification is needed.
- Verify a real traffic comparison with a dated turning count, valid network, CO₂-first logic, Vexcel coverage and relevant CoStar context or an explicit gap. Show a physical alternative and why it passes or fails. Dynamic observations, historic counts and modeled outcomes should each be identifiable. The main demo can show a rejected design as a transparent decision while an eligible recommendation remains a release acceptance item.
- Exercise the activity toggle, cancellation, switching sites or workflows, map bounds, defaults, proposal overlay toggle, stale-result labeling, and exact agreement among geometry, values and narrative. Observe desktop and narrow-screen use with keyboard and pointer. Log the shortcuts or gaps that were actually verified.
- Verify that a follow-up retains the active goal, relevant constraints and previous revision within the selected site. If the current editable brief loses context the planner needs, pass a compact, allowlisted revision summary through the existing harness. Keep each new proposal bound to its current inputs.
- Check the story as a planner who starts with a site and a plain-language question. For each feature shown, identify the concrete CoStar and Vexcel evidence that changed a decision. Lead with sustainability outcomes and the limits of the evidence, then show the optional existing-site view when it contributes to that story.

**Review gate:** Present the walkthrough, test results and open acceptance gaps. Ask the user to review core readiness before starting the stretch checkpoint.

## Checkpoint F · Stretch Existing / Proposed 3D

Begin after core review and explicit user approval. Pick a site with a verified 2D intervention and an exterior Matterport scan that shows the same location. Confirm a common coordinate reference and camera or landmark alignment. Preserve legal/authorized use of any scan imagery or point data.

Build a basic conceptual proposed scene from the **same** published 2D geometry and revision, using simple editable objects for planting, lane changes or pedestrian elements. The planner should be able to switch from Existing to Proposed at a comparable viewpoint. Assess whether an existing provider splat is available and usable. A new trained splat is outside the core workflow. Consider reusable Crossing Lab prototypes after verifying that their geometry and coordinate references fit the selected site.

**Review gate:** Demonstrate a correctly aligned Existing / Proposed comparison or document the concrete coverage or registration gap. Stale 2D proposals and mismatched sites should make the proposed view unavailable.

## Verification commands

Run from the nested Sustainability Map checkout with the dependencies for the selected feature installed. See [local setup](../README.md#run-locally) and the [handoff setup notes](CONVERSATION_HANDOFF.md#checkout-setup-and-verification).

```sh
.venv/bin/python -m unittest discover -s tests
node --test tests/*.mjs
git diff --check
```
