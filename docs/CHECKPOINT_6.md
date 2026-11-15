# Checkpoint 6 — core release verification

Review date: November 14, 2026. Branch: `codex/checkpoint-6`, based on Checkpoint 4 at `7684230`.

**Release decision: not ready for core-release acceptance.** The current build has been checked and the defects found below have been fixed. The user explicitly chose to verify the current build and record missing Checkpoint 5 as a blocker. Stormwater design/capture implementation and Checkpoint 7 are outside this pass. Stop here for review.

## Release blockers and pending checks

1. **Stormwater has no published design or capture comparison.** It supports independent property/site selection, sourced review, measured outlines, county hydrology, and planner markings. It does not compare treatment layouts, calculate runoff/capture/overflow, publish a real treatment footprint, or revise a treatment design. Rainfall changes mark evidence stale; they do not update capture estimates. The development fixture is not acceptance evidence for those capabilities.
2. **Traffic has no supported recommended footprint at the tested sites.** Main/1st's alternatives fail the approved throughput/delay rules. All four verified count sites also lack usable Vexcel parcel/building extraction and nearby mapped CoStar frontages. The correct output is a rejected comparison with no proposed overlay. A complete demonstration still needs a real site with both sponsors' relevant coverage and a physical alternative that passes the rules.
3. **Final narrow-screen visual and keyboard walkthrough remains pending.** Desktop discovery, keyboard feature selection, parallel activity and the live traffic result were observed through Chrome's accessibility interface. Browser automation was disabled; native Chrome intermittently lost its window and returned stale screenshots. A separate native-browser attempt did not provide usable page control. Consequently, this report does not claim a final narrow-screen visual pass or visual verification of the newly added coordinate editor. Controller tests and CSS review are complete; a reliable browser/manual check is still needed.

Property selection matters: choosing a CoStar search result supplies its selected property fields. A map/discovery point at the same coordinate does not automatically become that property. At Kipling, direct point selection has no selected CoStar detail and no nearby mapped frontage. Select the property explicitly for a review using both sponsors.

## Fixes made during verification

- Unavailable or malformed crossing/driveway detections no longer become zero overlaps. The local comparison records an unavailable detection status and null overlap counts; the agent gets an availability fact, the UI says “Not assessed,” and the ranking blocks recommendation. Successful empty responses remain distinct, with an explicit warning that no returned candidates does not prove absence. Invalid candidate boxes cannot be silently dropped into a successful-empty result.
- Re-selecting the current workspace preserves the current analysis and proposal. This previously cleared results when the page was opened without a fragment and the already-active Traffic button first added `#urban-planners`.
- Keyboard users can select the map center as a site, add vertices at the map center, and edit labeled latitude/longitude fields. Blank, nonfinite, out-of-bounds, uncovered, and more-than-990-m-away marking points cannot be saved. The browser's 990 m limit leaves a small margin inside the server's projected 1 km buffer so different distance methods cannot silently save an invalid boundary point. Existing click/drag editing remains available. These coordinates remain local and do not expand the model payload.
- A privacy test now inspects public event summaries/facts rather than searching timestamps for a forbidden numeric token. A legitimate timestamp ending in `.999` caused the old assertion to fail intermittently.

## Actual site checks

### Traffic — Main Street / 1st Street

Selected **Turning-movement counts** and Main/1st using the keyboard, confirmed the dated 2011-11-08 sheet and 5,631 PM movements, and submitted two physical alternatives: an eastbound 60 m curb extension and a westbound 80 m pedestrian-space reallocation. The activity feed showed both specialist investigations, source failures, nine paired simulation runs, citation-validation retries and a completed cited review. The displayed table reported:

| Metric | Baseline | EB 60 m | WB 80 m |
|---|---:|---:|---:|
| CO₂, kg / demand hour | 467.1 | 392.3 | 450.0 |
| NOₓ, g / demand hour | 157.8 | 131.2 | 152.2 |
| Mean delay, s / offered vehicle | 1,233.5 | 1,379.7 | 1,439.7 |
| Completion, rounded display | 67.2% | 61.2% | 60.6% |

The completed result correctly showed **No layout recommended**, both alternatives as ineligible, and a disabled proposal toggle. Lower emissions did not override stranded demand or missing source checks. These are simulations of historical counted demand with approved generated timing and 2026 fleet rates, not observed current traffic or ambient pollution.

After the source-state fix, a local replay revalidated the official count reference and reused the paired SUMO cache and retained sponsor responses. A second revision added a planner keep-clear area over the EB footprint. The EB conflict changed from false to true, WB stayed false, and the canonical identity hash changed (`7c8096c9` → `3fc65b24`). The unchanged physical alternatives retained their same emissions results; the constraint changed eligibility, not traffic demand. Neither revision published a proposal. This is a local replay of real source inputs, not a new provider fetch or a demonstration of an accepted design being revised.

Local review artifacts: `private/checkpoint6/traffic-revision-1.json` and `traffic-revision-2.json`. Earlier source responses and the complete live traffic response remain under `private/checkpoint4/`.

### Stormwater — Kipling Apartments

Queried local property search, selected CoStar property `4483806`, and ran the updated localhost NDJSON endpoint in Stormwater mode without an intersection project. The live review completed in **49 seconds**, with both specialists, valid citations, no analysis error, and all four source groups ready. Source values included:

- Vexcel parcel: **1,391.22 m²**; mapped building footprint: **1,024.16 m²**; parcel outside returned footprints: **367.06 m²**.
- CoStar: **194 units**, **25 reported parking spaces**, and **60,087.66 sq ft gross floor area**. The review explicitly distinguished floor area from roof footprint.
- LA County: **1.01 inches**, 85th-percentile 24-hour contour estimate, and **Ballona** subbasin context.

The review used both sponsors to explain why mapped roof-like area, unconfirmed parking detections, and reported parking counts cannot establish drainage connections or available treatment land. Capture and designs remained unassessed. Both `proposal` and `comparison` were null, confirming the Checkpoint 5 blocker rather than hiding it behind a UI fixture.

Local review artifacts: `private/checkpoint6/water-review.json` and `water-events.json`. Raw sponsor data, geometry and these artifacts remain ignored by Git.

## Automated verification

**74 Python tests and all four JavaScript controller suites pass.** `git diff --check` passes. Fixtures in these suites are development test inputs, not real-site performance claims.

| Check | Evidence and result |
|---|---|
| Source failures | Unavailable providers preserve retrieved facts; missing counts reject analysis; failed/malformed detections block eligibility rather than becoming zero. County sources fail/retry independently. |
| Parallel activity and cancellation | Concurrent specialist events observed live in both modes. Tests cover sanitized activity, event ordering, canceled/superseded streams, subprocess cancellation, and retained partial results. |
| Site/workflow switching | Old runs and discovery responses cannot repaint another site or mode. Actual mode switches still clear unrelated geometry; repeated active-mode events preserve it. |
| Stale inputs and revisions | Marking/rainfall edits mark results stale. Tests reject old, mixed-site, mixed-workflow and mixed-hash publications. Unavailable updates preserve the previous labeled result; completed no-recommendation results remove old overlays. |
| Rendered metrics and geometry | Tests compare all eight baseline display values, unit/share conversion and rounding; compare exact published geometry with Leaflet's input; and check the same revision/hash on metric and proposal cards. A retained real traffic response was also checked against all 24 displayed table values. No actual eligible real proposal exists to visually compare. |
| Keyboard interaction | Native keyboard discovery selection passed. Controller tests cover map-center selection, coordinate editing, invalid-input rejection, saving a keep-clear constraint and revision advancement. Final browser focus/visual check is pending. |
| Narrow layout | Existing narrow-screen discovery-collapse tests pass. Coordinate fields use bounded columns inside the scrollable sidebar. Actual narrow-screen visual verification remains pending. |
| Privacy boundary | Graph tests inspect model requests and activity for exact coordinates, geometry, names/addresses, private keys and disallowed property fields. Only approved scalar facts and planner text are sent; tracing remains disabled. No new model-facing fields were added. |

Commands:

```sh
.venv/bin/python -m unittest discover -s tests -q
node tests/discovery-controller.mjs
node tests/planner-hydrology.mjs
node tests/analysis-stream.mjs
node tests/proposal-controller.mjs
git diff --check
```

The JavaScript suites were run using the provided Node runtime because `node` was not on this shell's PATH. The app was restarted on port 8001 with the fixes; reload the page to receive the new assets.

## Manual review route

1. At `http://127.0.0.1:8001`, select Traffic → Turning-movement counts → Main/1st → Analyze. Inspect the date, assumptions, rejection reasons and absence of a recommended overlay.
2. Select Stormwater, search for Kipling Apartments, select the result, and Analyze. Inspect the cited Vexcel measurements, CoStar facts and county hydrology. Confirm no capture benefit or real design is presented.
3. Use **Use map center as site** and **Site evidence & adjustments → Adjust or add map markings**. Add center points, edit coordinates with the keyboard, save, and verify the previous review becomes stale. Try a blank/outside point and confirm it cannot be saved.
4. Repeat at a narrow viewport; check sidebar scrolling, focus visibility, discovery collapse, map access, marking controls and proposal toggle. This is the remaining visual check.

Do not advance to optional 3D or describe this as core-release accepted until the blockers are resolved and the user reviews the result.
