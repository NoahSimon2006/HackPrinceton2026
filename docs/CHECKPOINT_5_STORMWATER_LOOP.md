# Checkpoint 5 — stormwater design and revision loop

Implemented November 15, 2026 and committed as `abf6ef3` (`Complete sourced stormwater design and revision loop`), then pushed to `origin/main`. Checkpoint 4 was committed as `26e3639` (`Add researched area opportunities and location selection`) and pushed to `origin/main` by a fast-forward. This report uses the revised implementation plan's numbering. Checkpoint 6 has not started.

## Delivered behavior

A researched stormwater opportunity now becomes a conditional, geographically aligned bioretention concept. The lead agent investigates the selected site with concurrent site-evidence and domain specialists, reads their saved reports, then requests bounded local geometry and up to three distinct internal alternatives. The interface recommends one footprint and exposes the others for inspection, including rejected geometry and its reason. Users do not need to draw competing placements.

A point just outside a parcel can consider a mapped host within 75 m, while preserving the selected opportunity and explicitly labeling the host provisional. Ambiguous parcels, missing building coverage, protected access without relevant host evidence, and insufficient usable space produce a targeted question. A neighboring parcel is never silently treated as owned or hydraulically connected.

Natural-language follow-ups can change target area, effective ponding depth, compact/linear form and placement preference. Canonical settings and keep-clear markings remain constraints; unspecified design choices carry forward. The UI provides explicit design controls and a separate runoff what-if opt-in, coefficient, contributing-area markings and named rainfall scenario. Rainfall and drainage assumptions are changed through these controls. The model cannot establish a drainage connection on its own.

The result pairs the exact footprint with storage, direct rainfall, contributing-area union, runoff, temporary external storage and excess runoff when those inputs support calculation. Unknown runoff is shown as unassessed, never zero. Source-dependent siting decisions and field checks are inspectable. Each saved revision retains its own geometry, settings, assumptions, input hash, metrics and alternatives; earlier versions are read-only, with a return-to-current action.

## How sponsor evidence changes the design

Vexcel parcel and building geometry bounds the usable host area and excludes mapped structures. Returned access, parking and frontage cues are conservative exclusions; absent detections do not prove an area clear. Nearly identical parcel outlines are conservatively intersected; distinct overlapping host ambiguity is retained.

CoStar use and reported operational fields influence screening choices only after local host association. Multifamily use proposes a 2 m circulation band around mapped buildings, versus a default 1 m screening band. These are explicit design assumptions, not surveyed paths, entrances, regulatory setbacks or ownership evidence. Reported parking/loading can strengthen exclusions around positively located cues, but cannot locate unknown parking or access. Multiple records do not silently become one property's unit/parking totals. Raw records, exact coordinates and full geometry stay local; the model receives allowlisted facts and decision summaries.

The real demonstration host contained one CoStar Multifamily record with 179 units and 204 reported parking spaces. Its Vexcel neighborhood provided 11 parcel and 16 building outlines; detection returned no usable features. A local same-evidence ablation with and without the CoStar operating context changed the resulting footprint by **11.906 m² symmetric difference**. This establishes a material geometry effect, not an environmental benefit claim.

## Real end-to-end verification

The existing live area search retained six researched locations across two batches. Its selected second-batch collection opportunity became a site project; the original terrain signal remained screening context, not a connected catchment. The usable provisional host lay 2.5 m from the selected point.

| Step | Observed result |
| --- | --- |
| Draft | Revision 3: 40 m² compact concept, 6 m³ ponding capacity, 1.046 m³ direct rain under the county 1.03-inch event. Capture unknown. Three internal alternatives. |
| Revise in chat | Revision 4: 20 m² linear concept, 3 m³ capacity, 0.523 m³ direct rain. Geometry changed while the selected opportunity and source-informed exclusions remained. Capture unknown. |
| Explicit what-if | User marked a hypothetical 64 m² roof subsection, opted into assumed connection, set coefficient 0.8 and named an illustrative 2-inch event. Treatment remained 20 m² with 0.15 m effective ponding. |
| Event balance | 3 m³ capacity − 1.016 m³ direct rain = 1.984 m³ available for external runoff. Assumed runoff is 2.601 m³; excess external runoff is 0.617 m³. Direct overflow is zero. Display values round to three decimals. |
| Native summary | Revision 6 completed with a validated, fully cited summary, no analysis error and no partial-summary warning. Lead and both specialists read their trusted skills; the lead read both evidence and specialist report files. |
| Persistence | A full server restart restored the chosen site, explicit scenario, source marking and revisions 3–6. All published metrics matched their proposal's revision and input hash. Browser inspection restored the earlier 40 m² unknown-capture concept and then returned to the current 20 m² what-if. |

The marked roof subsection is an explicitly hypothetical drainage input. No field connection, inlet, ownership, infiltration, permanent retention, flood protection or water-quality performance was established. The map and summary retain these distinctions.

## Agent reliability and validation

The native lead still delegates specialists, uses the bounded virtual filesystem, consumes source/report artifacts and calls local design tools. Curated design summaries are saved under `/project/designs/`; exact geometry is archived locally with the canonical project. Strict citation validation rejects unsupported numeric claims. Validation feedback now suggests matching existing fact IDs for repair without accepting or adding citations automatically.

One live run produced valid geometry and calculations but failed narrative citation validation. The UI retained the locally validated concept and explicitly labeled its summary incomplete. A subsequent native run produced a complete cited review. Cancellation/deadline handling clears pending design publication, and failed or stale revisions cannot enter successful history. A development-process stale-module mismatch was resolved by a full backend restart; restart Python after backend edits.

Validation completed:

- **213 Python tests pass** and **eight JavaScript test files pass**.
- Stormwater tests cover source-dependent exclusions, bounded host selection, ambiguous/duplicate outlines, narrow fragments, per-host access, explicit settings, constraint continuation, overlapping-source union, direct-rain reservation, zero coefficients, unknown capture, cancellation/deadlines, stale publication and persistent revision history.
- Browser controller tests cover canonical settings, partial-summary handling, alternative-specific decisions and historical inspection.
- Read-only final audit found no additional actionable bugs; `git diff --check` passes.
- Real desktop checks exercised scout → select → draft → inspect → revise → explicit what-if → restart/restore. Mobile and the complete traffic journey remain outside this checkpoint.

## Next boundary

Checkpoint 5 is committed and pushed. The next milestone is the traffic design/evaluation/revision loop; see its current report and the revised implementation plan. Its acceptance still requires source-verified demand, reproducible comparisons, inspectable failed alternatives and pursuit of an eligible real recommendation. Conceptual 3D and final core-release verification remain later work. The existing interior-tour exclusion and selected-property exterior association are preserved.
