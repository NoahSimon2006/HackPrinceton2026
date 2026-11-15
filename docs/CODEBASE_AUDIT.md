# Codebase correctness audit — November 14, 2026

## Scope and result

Reviewed the first-party application, request/agent pipeline, proposal contracts, source adapters, geometry and hydrology calculations, traffic parsing/simulation/ranking, discovery builders, archived simulation scripts, browser controllers, requirements and handoff documentation. Existing uncommitted Checkpoint 5 work was preserved. Confirmed defects were fixed with regression tests. This pass did not redesign data presentation, advance another checkpoint, commit, push or merge.

This is a completed code review and repair pass, not a claim that every possible defect or real-world modeling limitation has been eliminated. Bundled Leaflet and installed dependencies were not independently source-audited. Raw sponsor datasets were not exhaustively field-verified. Current cache/source checks are described below.

## Confirmed defects fixed

| Area | Before | Corrected behavior |
|---|---|---|
| Source completeness | Building outlines and detections were silently truncated to 12; malformed declared footprints could disappear. Nearby CoStar frontages were also capped at 12. | All returned constraints are retained for checks; unusable declared source geometry fails closed. Missing evidence cannot masquerade as zero conflict. |
| Source failure propagation | Measurement filtered invalid outlines/frontages before downstream traffic checks saw them. | Both planning workflows preserve an unavailable status for incomplete source checks. |
| Traffic eligibility | Rounded completion, delay, CO₂ and queues could change strict pass/fail outcomes; rounding scores could suppress or change a winner. | Ranking uses full precision; rounding occurs only for display. Simulation cache version changed. |
| Missing simulation output | Missing emissions/queue output could become zero; a subset of noise seeds/approaches could be presented as a complete maximum. | Required output fails validation; incomplete maxima remain unassessed consistently in simulation facts, proposal metrics and browser tables. |
| Count sheets | Some printed approach totals, school columns, duplicate hours and automatic hourly row identities were unchecked. | Source sheets must pass the expanded consistency checks before creating demand. |
| Fleet data | Nonfinite/negative CARB inputs and missing vehicle classes could enter calculations or imply an all-car fleet. | Invalid fleet evidence is rejected; no replacement proportions are invented. |
| CoStar totals | Known category counts were summed even when another parking/loading category was unknown; booleans could become numeric counts. | A complete total is reported only when every category has a valid nonnegative integer count. Invalid scalar fields remain unknown. Duplicate/missing property IDs are rejected before use. |
| Network/source identity | OSM restriction relations were discarded; edited discovery snapshots or changed networks could reuse old matches. | Downloader preserves restriction members and writes atomically; snapshot contents/network hashes are verified. Simulation uses the canonical matched source center and fingerprints the converter binary. |
| Stormwater confirmations | A confirmed connection/access basis could remain checked after changing the geometry or design it applied to. | Relevant confirmations reset when physical inputs change; old results remain stale until a fresh confirmed analysis. |
| Small design inputs | A small nonzero depth/coefficient could be rounded to zero in agent facts while the calculator used the actual value. | Explicit water inputs retain their decimal precision in cited facts. |
| Hydrology/terrain | Malformed/nonfinite contours were not consistently rejected; D8 uncertainty ignored diagonal NoData neighbors. | County geometry/depth validation fails closed; boundary uncertainty follows all eight routing neighbors. |
| Browser request races | Late property/search/county requests could restore disabled or obsolete state; cached county success could conceal a newer source failure. | Request generations, cancellation and per-source identity prevent obsolete responses from repainting current state. Cached values disclose later failures. |
| Publication consistency | New comparison values/revision could be installed before Leaflet rejected malformed new geometry. | Geometry is prepared successfully before the new publication is installed. Invalid updates preserve the prior publication. |
| Streaming | Duplicate terminal results or later activity were accepted after a completed stream. | Terminal state is enforced; malformed streams cannot replace a completed result. |
| Map coverage | A hand-drawn northeast restriction and whole-viewport checks contradicted the approved center-only Vexcel coverage policy. | Pan/zoom/property selection enforce the exact sourced coverage for the map center. |
| Proposal contracts | Workflow, fixture classification and design kind could disagree; duplicate metric/evidence IDs or overlapping existing/proposed IDs were accepted. | Those inconsistencies are rejected by the shared proposal schema. |
| HTTP/source boundaries | GET source errors could expose local paths; disconnected tile requests attempted a second HTTP response. | Source errors return safe messages; disconnected requests stop without a second response. Invalid coverage polygons are rejected. |
| Existing-site association | Relative coordinate tolerance weakened the intended absolute property/scan association tolerance. | Coordinates use the specified absolute tolerance with relative tolerance disabled. |
| Archived execution | The random-demand runner invoked an unrelated extrapolation exporter and relied on old tool paths. | Archived random runs and volume extrapolation are separate explicit opt-ins; portable SUMO tooling and validated CARB rates are reused. |

The CoStar correction affects actual pilot records: Kipling's earlier 25 and Olympic's earlier 60 parking spaces were known-category values, while another category had no count. Current total-parking fields correctly remain unknown. Historical checkpoint reports are not retroactively treated as complete current totals.

## Duplication and maintenance

- Extracted the duplicated street-name normalizer into `street_names.py`. Traffic, discovery and archived export now share ordinal/abbreviation matching without importing the simulation engine into discovery.
- Reused `sumo_tools.py` in archived execution instead of maintaining platform-specific binary paths.
- Added direct pins for the agent libraries that the application imports, using the installed/tested versions; dependency consistency checks pass.
- Corrected the discovery dependency description: Rasterio/NumPy are also needed for optional runtime Stormwater terrain screening.
- Replaced the obsolete handoff, which described removed modes and missing features that now exist. Historical checkpoint documents remain review records; README/HANDOFF identify current status.
- The inactive legacy emissions renderer/artifact is still retained for reference. It is not re-enabled, and broader removal/modularization is deferred rather than mixed into this correctness pass.

## Verification

- **120 Python tests pass**, including regression tests for source truncation/completeness, numeric validation, threshold boundaries, parser identities, network/snapshot provenance, water input precision and publication contracts.
- **All six JavaScript suites pass:** app, discovery, planner/hydrology, analysis stream, proposal and site-view controllers. All six first-party browser scripts parse.
- Python compilation, dependency consistency and `git diff --check` pass.
- Static HTML has no duplicate IDs or missing literal JavaScript lookup targets.
- Offline checks of the actual local data succeeded: 1,581 CoStar properties loaded; both pilot total-parking fields are unknown; the exterior tour remains linked; both discovery snapshots pass content integrity with all their layers ready; the cached CARB source passes stricter validation.
- Browser visual acceptance was not rerun in this logic pass. No fresh live traffic comparison, model recommendation or refreshed public-source download is claimed.

## Remaining work and limits

1. **Road artifacts rebuilt in the follow-up.** The [network verification](ROAD_NETWORK_VERIFICATION.md) records 515 downloaded restrictions, 55 corrected lane connections, 359 passing represented static restrictions and nine fresh real-count runs. Old artifacts were backed up. Conditional/complex rules are not silently certified: affected studies are unavailable. Full real-world turn coverage remains unverified.
2. **Real-site acceptance remains open.** Traffic still needs a sufficiently supported site/design that passes the agreed rules. Stormwater still needs supported planner outlines and confirmations for a real placement/capture/revision demonstration. Proposed 3D still needs a published 2D design and verified scan alignment.
3. **Visual/keyboard acceptance remains open.** Desktop and narrow-screen checks should accompany the next presentation pass when reliable browser control is available.
4. **Model grounding has limits.** Citation IDs and supported numerical tokens are validated, but that does not prove that prose interprets every source correctly. Reviewed outputs are screening advice, not surveyed or engineering-approved designs.

The user asked to work on how data is portrayed after this review. The findings above are the factual starting point for that next discussion; appearance changes have not begun.
