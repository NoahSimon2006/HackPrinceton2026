# Desktop demonstration walkthrough

A 3–5 minute core presenter path using the verified Checkpoint 5 stormwater study and Checkpoint 6 Main/1st traffic study. Prepare both under **Saved projects**. Fresh runs can take longer; show actual progress or openly use the saved path. Fresh [Checkpoint 7 verification](CHECKPOINT_7_CORE_DEMO.md) also completed native scouting and a 40 → 20 m² revision. In the port-8010 review workspace, project `2f06f0bcd94744b3a5147961eefb9e07` is the fresh 20 m² concept (saved revision 5); project `1228bd6721644fada200c564d881d9f2` supplies the explicit 2-inch scenario below. Main/1st is project `a7e30e1ea73441b0a1953f1b4a18c90d`.

Opening line: “Describe an environmental goal, let the agent investigate locations, choose one, then inspect and revise a physical design with its evidence.”

## Presenter path

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:40 | **Stormwater → Find improvement opportunities**. Show the search boundary and researched shortlist, or use the first prompt below with **Find locations**. | The agent researches up to three choices. Environmental opportunity comes first; feasibility/disruption and readiness remain separate. Terrain is a screening signal. |
| 0:40–1:20 | Select a supported location, or explicitly open the prepared stormwater study through **Saved projects → Open**. Expand **Agent activity** and **Project files**. | Point to the lead's plan, both specialists, a skill read, and their saved reports. Identify any partial-report warning. |
| 1:20–2:10 | Show the stormwater footprint and **Sponsor evidence & siting decisions**. | Vexcel parcels/buildings bound usable space. CoStar's associated Multifamily context changes a proposed circulation exclusion. That margin is an assumption, not surveyed access. |
| 2:10–3:00 | Open **Earlier design revisions**: inspect revision 3, then revision 4. Use **Return to current concept** afterward. | The saved 40 m² compact concept became a 20 m² linear strip while retaining constraints. Say these are saved revisions. Use the prompt below for a fresh live revision. |
| 3:00–3:40 | Inspect the current stormwater scenario under **Stormwater design & what-if settings** and its calculation. | The hypothetical 2-inch event assumes a connected 64 m² roof section and coefficient 0.8: 3 m³ capacity, 1.016 m³ direct rain and 1.984 m³ temporary external storage. These are scenario calculations, not measured capture. |
| 3:40–4:40 | Switch to **Traffic & Emissions**, open the prepared Main/1st project, expand a rejected alternative and choose **Show footprint on map**. Use **Earlier traffic evaluations** to compare evaluations 2 and 3. | Current flow helped locate the site; simulation uses labeled 2011 demand. Two layouts shortened to 20 m without changing the baseline. Lower emissions cannot justify stranded trips; crossings and missing access evidence also block recommendation. |

Close: “The output is a mapped concept or evaluated alternative with its evidence, assumptions and revision history. The planner can change a constraint and see what changes.” The same selected footprint can be inspected in conceptual 3D; a Matterport tour is optional and separate.

## Conceptual 3D inspection

Add about 45 seconds after showing the current stormwater footprint, or use this in place of the detailed runoff scenario when time is short. In the port-8010 review workspace, open project `2f06f0bcd94744b3a5147961eefb9e07` and its current revision 5, then choose **Explore in 3D**.

1. Point to the **20 m²** footprint and **3 m³** saved storage. Say: “This is the same saved design rendered in meters; opening this view does not rerun the agent or calculation.”
2. Switch **Existing / Proposed** without moving the camera. Use **Top view** or drag to orbit, then **Reset view**. The footprint matches the map; Existing hides the intervention while retaining the viewpoint and available context.
3. Show **Scene basis**: Vexcel outlines support the building footprints; the 6 m building heights and neutral ground are illustrative. The treatment depth is the existing assumed ponding depth, not surveyed excavation or grading.
4. Close the dialog, inspect earlier revision 2 and open **Explore in 3D** again. It shows the earlier 40 m² footprint with its own saved identity. Unmatched surrounding geometry is omitted rather than borrowed from the current design.

Current and earlier stormwater scenes, a rejected traffic layout, unchanged comparison cameras and Escape/focus behavior have been checked in the browser. Input/race invalidation is covered by focused controller checks, as recorded in the [Checkpoint 8 report](CHECKPOINT_8_CONCEPTUAL_3D.md). Do not describe 3D appearance as additional evidence of environmental benefit, feasibility or Matterport alignment.

## Fresh-run prompts

Use a rehearsed stormwater search area with sponsor coverage. Fresh results may differ; do not promise the saved numbers for a new run.

**Find locations**

> Find promising locations for a stormwater treatment in this area. Prioritize environmental opportunity, then feasibility and disruption. Explain data readiness separately and use Vexcel and CoStar evidence to investigate the choices.

**After choosing a location — Analyze site**

> Draft a compact rain-garden concept of about 40 m² where the site evidence supports it. Keep buildings and identified access constraints clear. Explain how Vexcel and CoStar affected the placement. Leave runoff capture unassessed unless a contributing-area connection is explicitly supported.

**Continue project — meaningful revision**

> Make the concept a 20 m² linear planting strip. Preserve the selected location, effective ponding depth and existing source-informed constraints. Explain the geometry and storage changes without inventing a drainage connection.

Ensure explicit size/form controls do not contradict the prompt. History inspection is read-only: viewing an old revision does not make it the active design.

## When a provider is unavailable

Open the prepared project through **Saved projects** and say: “This is a saved evaluation from the displayed original save time; no fresh investigation is being presented.” Keep the saved-result notice visible. Original evaluation time, source observation date and latest project edit time are different.

Use the retained concepts/evaluations and exact footprints. Expired traffic maps, scout measurements and model prose are not archived or replayed as current evidence. Hide live traffic discovery for the saved case. Keep failure, stale-input and incomplete-summary labels visible.

The stormwater example demonstrates substantive use of both sponsors. The Main/1st traffic example demonstrates Vexcel-informed checks and an honest rejection; usable CoStar access evidence and an eligible traffic recommendation remain open gaps. Do not describe missing CoStar records as a positive property-access finding.

Evidence: [stormwater verification](CHECKPOINT_5_STORMWATER_LOOP.md), [traffic follow-up](CHECKPOINT_6_FOLLOWUP.md), and [model reliability](MODEL_DEMO_RELIABILITY.md).
