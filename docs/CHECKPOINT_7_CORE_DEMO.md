# Checkpoint 7 — core product and demonstration

**November 15, 2026 — implemented locally, with acceptance gaps.** Checkpoint 6 and its follow-up are pushed to `main` through `abb548a`. This report describes the local Checkpoint 7 work on that base. Fresh stormwater drafting/revision, cancellation recovery and saved traffic inspection are verified below. The final native stormwater run passed with both specialists after the report-completion fix; the final native scout check also passed with both specialists. This is not a blanket release signoff. Desktop is the primary demonstration surface; Checkpoint 8 and conceptual 3D have not started.

## Implemented in this checkpoint

- **Preserve useful stormwater work after a failed continuation.** The last valid concept for the same site can be restored from project history after a failed, canceled or incomplete follow-up. It remains a stale reference, with the failure visible, rather than appearing to be a successful new evaluation.
- **Identify saved evaluations by their original archive time.** Saved results and history use the design's original `savedAt`, not the latest project edit time. A visible saved/historical notice distinguishes retained output from a fresh investigation. Source observation dates remain separate.
- **Keep historical evidence attached to its own evaluation.** Historical concepts and comparisons do not create links into the current fact ledger. A retained study becomes historical before its facts change; action guards also cover same-input stale studies. A prior footprint must not acquire a newer run's evidence by sharing a citation identifier.
- **Repair premature specialist completion without weakening evidence checks.** A mixed `write_file` and invalid `SiteReview` response could terminate a specialist graph before a valid structured report was produced. Both site and scout agents now allow one schema-only correction after the graph returns, retaining source/citation validation and run caps. The final native stormwater run exercised the domain correction and completed both specialists. Scout recovery also permits a bounded missing-read correction; its role in the observed live failure remains a hypothesis. The second live scout batch had both specialists partial without a repair event before this fix; the final scout run completed both specialists without needing a corrective retry. Persistent incompleteness remains explicit.
- **Provide a concise presenter path.** The [desktop demo walkthrough](DEMO_WALKTHROUGH.md) supplies exact prompts and a 3–5 minute route through opportunities, agent investigation, a physical concept, a meaningful revision and an honest traffic rejection.

Environmental impact remains the first ranking priority, followed by feasibility and disruption. Data readiness is shown separately: it explains what the available evidence supports and what remains unresolved, rather than lowering an opportunity's environmental value merely because its data is incomplete.

## Verification

| Evidence | Observed result | Scope |
| --- | --- | --- |
| Fresh native stormwater search `f99260403f3b47d6b44487b5f31588f9` | The desktop UI displayed the first three researched choices; reload restored the completed search and its choices. | Fresh Checkpoint 7 browser/native-agent check. |
| Native **Show more** and explicit selection | A second batch returned three distinct choices while preserving the first search. The user-facing selection of `water-363366448c1245c3`, the first choice in batch two, created project `2f06f0bcd94744b3a5147961eefb9e07`. | Fresh Checkpoint 7 browser/native-agent check. Both scout specialists remained partial; no repair event was observed. |
| Selected-site stormwater concept | Native revision 2 produced a 40 m² compact concept, hash prefix `33dd6d75`, with 6 m³ storage and 1.046 m³ direct rain under the county 1.03-inch event. Runoff capture remains unknown. | Fresh Checkpoint 7 concept, saved November 15 at 09:46:25 UTC. |
| Native stormwater revision | Revision 3 produced a 20 m² linear concept, hash prefix `12efd9b9`, with 3 m³ storage and 0.523 m³ direct rain. Runoff capture remains unknown. | Fresh native continuation in the same project, saved November 15 at 09:48:08 UTC. |
| Final native scout check after the fix | The third batch completed in 68.4 seconds with three new choices, both specialist reports complete and a cited lead review. All three agents read the scouting skill. | Nine distinct choices remained visible; the selected project/design stayed unchanged. No correction was needed in this live scout run; correction branches are covered by native-graph fixtures. |
| Final native stormwater check after the fix | Revision 5 completed in 69.9 seconds, with a domain structured-review correction observed, both specialists completed and a cited lead review. There was no `analysisError` or `synthesisWarning`. | Hash prefix `9f834e0f`, saved November 15 at 09:53:46 UTC; the same 20 m² / 3 m³ design was retained, with exact geometry equality to revision 3. |
| Sponsor influence on the fresh concept | Vexcel returned 11 parcels and 16 buildings. The associated CoStar Multifamily record reports 179 units and 204 parking spaces, informing a 2 m screening margin. | The host is provisional, 2.5 m from the selected point; neither the association nor the margin establishes ownership, surveyed access or drainage. |
| Original saved time after reload | Reload restored the fresh concept with its original 09:46:25 UTC archive timestamp. | Fresh Checkpoint 7 browser persistence check. |
| Real cancellation and recovery | A revision 4 follow-up was started and canceled through the UI; the server recorded cancellation. Reload restored exact revision 3 with its original 09:48:08 UTC timestamp, visible failure/stale labels and blocked historical citation links. | Fresh Checkpoint 7 browser/server check; canceled work did not replace the saved concept. |
| Keyboard and pointer history inspection | Enter/Tab opened the 40 m² revision 2; pointer interaction returned to the current 20 m² concept. | Fresh desktop interaction check. |
| Narrow viewport | At 390 × 844, document and viewport widths were all 390 with no horizontal overflow; the browser was restored to 1280 × 720. | Minimal responsive check, not a complete narrow-screen journey. |
| Saved Main/1st traffic study | Inspected revision 4, comparison hash prefix `c7cd6a64`, including rejected `wb-bike` at 64 m² with its original 09:23:23 UTC notice. Keyboard history inspection opened revision 2 with its original 09:10:48 UTC notice. | Fresh Checkpoint 7 UI inspection of historical evaluations; no new traffic simulation was run. |
| Traffic source boundary | Live flow was hidden and the notice that it is not archived was verified. | Fresh saved-study UI check; no live TomTom replay. |
| Focused Python verification | Fourteen scout, thirteen site-agent and three persistence tests passed. | Thirty focused tests covering report recovery, validation and archive provenance. |
| Focused browser-controller verification | `planner-hydrology.mjs`, `proposal-controller.mjs`, `scouting.mjs`, `analysis-stream.mjs` and `app-controller.mjs` passed. | Five focused controller files, including bounded coverage and stale-search checks; the full test suite was not rerun. |

These checks supplement the earlier journey evidence below. Source-expiry, tool-failure and publication-race coverage comes from focused harness checks; the corresponding full live fault matrix was not repeated. The minimal narrow check does not establish a complete mobile workflow.

## Historical evidence used in the demonstration

The [Checkpoint 5 stormwater report](CHECKPOINT_5_STORMWATER_LOOP.md) records project `1228bd6721644fada200c564d881d9f2`: a 40 m² compact concept revised to a 20 m² linear strip, followed by an explicit 2-inch runoff scenario. Vexcel parcel/building geometry and CoStar Multifamily operating context materially affected siting. The circulation margin is a design assumption, and the source connection is hypothetical. Storage and scenario runoff are not measured capture. This study also verified saved revisions after restart. Those are historical Checkpoint 5 results unless explicitly repeated in this report.

The [Checkpoint 6 follow-up](CHECKPOINT_6_FOLLOWUP.md) records Main/1st project `a7e30e1ea73441b0a1953f1b4a18c90d`, revisions 2–4: live count-linked scouting, explicit selection, native comparison and named revision. The final unchanged-design verification completed in **95.1 seconds**, with both specialists and a cited lead review. This is historical Checkpoint 6 verification, not a fresh Checkpoint 7 timing measurement.

The Main/1st alternatives were **tested and rejected**. Vexcel supports physical conflict checks, but no usable CoStar access record or eligible traffic winner was established there. Lower total modeled CO₂ cannot justify fewer completed trips, failed operational gates or unresolved access/crossing constraints. Missing CoStar evidence must not be described as a positive access finding. A demonstration can show this rejection honestly; it does not close the eligible-design or both-sponsors traffic acceptance gaps.

## Remaining acceptance gaps

An eligible real traffic winner and material positive CoStar traffic-access evidence remain unestablished. Main/1st is an honest rejection demonstration, with historical source inputs and no fresh Checkpoint 7 engine rerun. Stormwater does demonstrate substantive contributions from both sponsors. A full narrow-screen journey and the full live failure/race/source-expiry matrix were not exercised; harness coverage and the limited visual check are identified above. These limits remain part of acceptance rather than being treated as completed work.

## Saved fallback and release boundaries

For an outage, use **Saved projects** and the retained concepts/evaluations with their original archive time visibly labeled. Distinguish that time from source observation dates and later project edits. Earlier revisions are read-only inspection; returning to the current concept does not run a new evaluation.

There is **no live TomTom replay**. Expired flow, transient scouting measurements and derived model prose are not archived as a current traffic result. Saved traffic simulations remain tied to their historical demand and network inputs. Hide live traffic discovery when presenting the saved case, and retain stale-input, failure and incomplete-summary labels.

The demonstration's primary artifact is the 2D concept or tested layout, its evidence, its assumptions and its revision history. Matterport context is optional. Do not start Checkpoint 8 without the user's next instruction.

## Review checkout

Checkpoint 7 is uncommitted on `codex/checkpoint-7-core-demo` in `/Users/Derek/Documents/Codex/2026-11-14/https-github-com-noahsimon2006-hackprinceton2026-https-2/work/checkpoint-7-core-demo`. The review server runs at <http://127.0.0.1:8010/#stormwater>. Its project database is an independent local copy; fresh Checkpoint 7 projects are stored there. Concurrent interface/guide changes in `/Users/Derek/Desktop/HackPrinceton26` were preserved. Checkpoint 6 alone was committed and pushed during this task.
