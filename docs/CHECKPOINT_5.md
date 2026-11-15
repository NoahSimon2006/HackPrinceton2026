# Checkpoint 5 — stormwater storage screening

Review date: November 14, 2026. Branch: `codex/checkpoint-5` from merged main `5cc4a13`.

After integration with Checkpoint 1, **Analyze site** screens an agent draft with no required markings. The **Compare your own placements** disclosure contains the planner-confirmed workflow documented here.

**Implementation is ready for review; full real-site acceptance remains open.** The user approved Kipling Apartments as the pilot and explicitly allowed planner-confirmed design inputs and labeled screening estimates. No actual site drainage connection, treatment outline, storage depth or overflow route has been confirmed in this review. The live source check therefore correctly publishes no proposal. Stop here; no later checkpoint is authorized by this work.

## What is implemented

Stormwater has a visible **Compare treatment placements** card with marking actions, proposed storage depth, runoff coefficient, an input-basis note and four unchecked confirmations. There are no numeric defaults. The planner supplies at least one contributing polygon and two or three distinct treatment polygons, confirms the surface/connection/access/overflow basis, and can add keep-clear areas.

**Update comparison** runs the existing parallel site analysis, then a deterministic local calculator before the lead agent writes its cited review. The model cannot invent design coordinates or substitute its own arithmetic. The results include a comparison table, accessible stored/excess volume bars, source and terrain details, and a conditional preferred footprint when supported. The source surface and treatment have distinct map styles and the same publication identity. Rainfall, marking and design-input edits cancel active runs and mark prior results stale; explicit Update comparison recalculates them. Recalculation is not automatic while typing and currently includes a fresh agent analysis.

The source checks require a unique containing Vexcel parcel with building coverage and a selected CoStar property. Treatments must be on-parcel, outside mapped buildings, external contributing surfaces and keep-clear markings. Direct intersection with a mapped CoStar frontage having reported curb cuts blocks the candidate. Missing frontages are unassessed, not zero conflict; the conditional result then relies on the explicit planner access confirmation. Malformed supplied frontages or outlines fail closed. No parking count is converted into pavement area.

Terrain samples come from the cached USGS 1 m bare-earth raster around Kipling. Source metadata, raster hash, coverage and valid neighboring pixels are checked before computing elevation range and gradient slope. Missing terrain blocks preference publication while preserving otherwise calculable conditional storage volumes. No arbitrary slope threshold, roof drainage, inlet route or overflow line is invented.

## Event accounting

Under one selected rainfall depth, overlapping contributing polygons are unioned and measured locally in UTM 11N. All alternatives use the same external contributing boundary and coefficient. With rainfall depth P, contributing area A, coefficient C, treatment area At and proposed depth d:

- External runoff: `P × A × C`.
- Direct rainfall onto treatment: `P × At`.
- Gross surface storage: `At × d`.
- External runoff temporarily stored: `min(external runoff, max(gross storage − direct rain, 0))`.
- Excess external runoff: `external runoff − external stored`.
- Excess direct rain: `max(direct rain − gross storage, 0)`.

Direct rainfall reserves capacity first in this conservative event-volume balance. The table distinguishes direct rain and external runoff. “No added treatment” is a zero-added-storage reference, not measured existing retention. The model assumes initially available, uniform surface storage over a flat treatment bottom; grading and available depth must be checked. It does not credit media void storage, infiltration or drain-out and makes no permanent retention, peak-flow, pollutant-removal or flood-protection claim.

Conditional ranking maximizes external runoff stored, breaking ties with the smaller treatment area. It never labels a failing geometry/access/terrain candidate recommended. This is a screening preference among proposed choices, not a construction feasibility decision. The simplified volume method is informed by the [EPA Bioretention Design Handbook](https://www.epa.gov/system/files/documents/2023-11/bioretentiondesignhandbook_plainnov2023.pdf); coefficient, dimensions and connections remain explicit planner inputs rather than implied EPA site prescriptions.

## Real evidence and live check

The actual Kipling source analysis completed with no analysis error and all four source groups ready:

- Vexcel: parcel 1,391.22 m²; mapped building footprint 1,024.16 m²; outside-footprint area 367.06 m². Outside-footprint area is not assumed available treatment land.
- CoStar: Multifamily, 194 units, 25 reported parking spaces and 60,087.66 sq ft gross floor area. No mapped frontage is available at this property.
- LA County: 1.01 in, interpolated between 1.0 and 1.1 in contours for the 85th-percentile 24-hour event; Ballona subbasin context.
- USGS: cached 1 m product published August 11, 2025. Acquisition date unverified; bare-earth gradients do not establish a roof or drain connection.

The live request deliberately supplied no invented design inputs. The response identified missing depth/coefficient/confirmations and missing contributing/treatment drawings, with `comparison.status = unavailable`, null volumes and no proposal. The cited review used both sponsors and distinguished county context from parcel drainage. Ignored artifacts: `private/checkpoint5/live-request.json` and `live-review.json`.

## Verification and limits

**95 Python tests and all five JavaScript suites pass.** Tests exercise conservation, direct rainfall, overlapping contributing area, invalid/coerced input, missing confirmations, geometry/access conflicts, unavailable terrain, source changes, publication hash binding, rainfall revisions, cancellation, per-site input persistence, rendered water metrics/chart values and exact map geometry. The tests use explicitly synthetic development inputs; they are not a real-site capture demonstration. A real cached raster sample also passes. Whitespace checks pass.

Only approved scalar facts and selected CoStar fields enter model messages. Geometry, exact coordinates, source records and confirmation-note text remain local. Activity and lead-agent tests enforce this separation. The lead must cite the selected treatment verdict for any requested design recommendation.

Browser automation remains disabled in Work settings. Native browser control was interrupted by a user window change, so the new desktop/narrow visual walkthrough is not claimed. No capture result or confirmed geometry was entered on the user's behalf.

## Review route and remaining acceptance

1. Reload localhost port 8001, choose Stormwater, search **Kipling**, and select the actual property result.
2. Analyze the evidence first. Inspect outlines and the sourced rainfall; the no-input comparison explains what is missing.
3. Mark the supported contributing surface and two or three treatment placements, preserving necessary access. Enter depth/coefficient and document their basis. Confirm only supported connections and overflow destinations.
4. Choose **Update comparison**. Review the table, direct-rain accounting, candidate checks and conditional proposal toggle. Green denotes treatment, cyan contributing surface.
5. Edit rainfall or contributing geometry; confirm the old result becomes stale, update, and check the revised geometry and values together. Add a keep-clear constraint and verify that an intersecting treatment cannot be preferred.

Real-site acceptance still requires these confirmed inputs and a full visual demonstration of a conditional design/revision. Overflow direction is not mapped without supporting route evidence. The earlier Checkpoint 6 report is historical; the implementation is no longer absent, but core release acceptance, successful traffic design demonstration and proposed 3D alignment remain unresolved.
