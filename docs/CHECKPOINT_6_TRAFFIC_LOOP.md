# Checkpoint 6 — traffic design, evaluation and revision

Implemented November 15, 2026 on `codex/checkpoint-6-traffic-loop`; integrated for release with the latest `main` map and source fixes. Checkpoint 5 was committed as `abf6ef3` (`Complete sourced stormwater design and revision loop`) and pushed to `origin/main` by a fast-forward.

**Implementation is complete; some live acceptance remains open.** A real native agent run produced three inspectable rejected layouts, and the previously rate-limited conversational revision now completes with the existing key. See [model reliability verification](MODEL_DEMO_RELIABILITY.md): the full revision took 65.1 seconds with a cited summary and no provider errors. The [Checkpoint 6 follow-up](CHECKPOINT_6_FOLLOWUP.md) now verifies a live Main/1st scout → select → evaluate → revise journey. An eligible real traffic recommendation remains open. Checkpoint 7 has not started.

## Delivered behavior

The traffic workspace retains the existing bounded lane-reallocation evaluator and adds persistent revision context, named changes, complete evaluation history and environmental-first selection. It keeps the direct-site path and connects scouting to verified demand only where spatial source evidence supports the connection.

A new scout choice may explicitly target a counted intersection when exactly one verified intersection lies within 25 m of the actual displayed flow geometry and inside the search bounds. The source geometry and environmental ordering remain unchanged. Its label and readiness explain the historical demand association; readiness never earns priority points. Ambiguous or unsupported matches remain ordinary flow opportunities. Existing selected projects never move, and changed/expired source links cannot silently relocate them.

The lead reads curated previous layout parameters, primary metrics and verdicts in its project brief, alongside canonical constraints. `evaluate_designs` accepts either complete alternatives or named changes. Named changes preserve omitted parameters and alternatives, then validate the entire set. One bounded comparison is allowed per request. The lead still delegates site-evidence and domain specialists, reads their reports and trusted skills, and uses its scoped virtual filesystem. Exact geometry and raw source records remain local.

Successful historical simulations are saved even when every alternative is rejected. Each revision stores its comparison, input hash, policy, exact tested geometry, metrics, alternative verdicts and deterministic source decisions. Restoration validates the comparison fingerprint and reconstructs every proposal from that comparison. Historical inspection is read-only. A failed follow-up restores the newest valid evaluation as a stale saved reference while preserving the failure message; it never promotes the failed revision. Source-inspection controls do not attach old evidence IDs to a newer failed ledger.

A completed local comparison remains inspectable if narrative synthesis fails, with an explicit incomplete-summary notice. Cancellation clears pending traffic publication. Provider rate limits receive a specific explanation. Live flow and model prose derived from it remain outside durable traffic history; independent historical simulation artifacts can persist.

## Environmental-priority policy

New runs use `environmental-priority-v1`; existing `strict-v1` history retains its recorded weighted policy.

1. Apply validity, evidence, access, crossing and operational gates. Retain the same offered-trip cohort, no teleports, sufficient completion, limited entry failures, modeled CO₂ improvement, and delay/queue/noise limits. Positive reported access conflicts block the new policy. Missing required checks remain unassessed.
2. Among eligible layouts, prioritize total modeled tailpipe CO₂ for the same demand hour.
3. Compare feasibility and disruption only inside a disclosed environmental tie screen: one standard error of paired-seed CO₂ differences. This is descriptive simulation variability, not a confidence interval or a complete uncertainty estimate. With missing paired detail, only exact means tie. Then compare common assessed access/parcel/footprint impacts and operational tradeoffs.
4. Display readiness separately. It cannot improve environmental ranking or turn missing evidence into zero impact.

Paired seed results, network hashes, demand-source hash and simulation assumptions are retained for reproduction. Every seed must account for exactly the counted offered cohort through completed, unfinished and not-inserted trips. The interface distinguishes worst individual approach queue change from the overall maximum queue in the comparison table, so the rejection gate is understandable.

## Real verification and limits

### Scouting and source association

A real current-flow search near Beaudry returned one South Beaudry corridor opportunity. Its geometry did not support a unique counted-intersection link, so the selected location was not shifted and historical counts were not borrowed. Its subsequent selection correctly rejected expired live evidence. The new intersection-link behavior passed focused source-geometry tests; an anchored live scout → quantitative design journey was not demonstrated in this pass.

### Native historical-demand study

A separate, explicitly selected Beaudry/1st study used the verified February 3, 2015 PM 5–6 turning sheet: **3,967 offered movements**. Mapped approach geometry and restrictions passed preparation. This is historical demand with generated timing, not today's traffic or a forecast.

The native agent evaluated the predeclared alternatives together, retaining one traffic lane:

| Layout | Length / footprint | Total modeled CO₂, kg per demand hour | Outcome |
| --- | --- | --- | --- |
| Baseline | Existing network | 429.770 | Reference |
| south-short | 20 m / 64 m² | 428.647 | Rejected: worst-approach queue increase exceeds the gate; access unassessed. |
| south-long | 40 m / 128 m² | 430.150 | Rejected: CO₂ does not improve; excessive queue increase; access unassessed. |
| east-short | 20 m / 64 m² | 432.725 | Rejected: CO₂ does not improve; access unassessed. |

Vexcel outlines/detections were available, with no mapped building or candidate crossing/driveway conflict returned for these footprints. The east option touched about 0.21 m² of mapped parcel geometry. CoStar returned no usable nearby property/access context for this study, so access stayed unassessed and could not pass the recommendation gate. This site does not demonstrate a complete CoStar-supported traffic recommendation; the earlier stormwater demonstration remains the successful material two-sponsor design example.

Both native specialists completed. The lead read traffic-evaluation and proposal-publication skills and consumed the specialist reports. A rate limit interrupted final narrative synthesis; the validated evaluation remained visible with an incomplete-summary label. Its saved project is `02e9ba51a92b4920a8dec8a0dc3efedb`, with successful evaluation revision 2.

### Revision verification

The requested follow-up changed only south-long from 40 m to 60 m to examine added pedestrian space against disruption, keeping south-short, east-short and the baseline fixed. Initial live follow-up attempts were rate-limited by xAI. The subsequent [model reliability fix](MODEL_DEMO_RELIABILITY.md) added shared pacing, bounded transient retries, compact role-specific context and safe diagnostics. A fresh native run then completed the exact requested follow-up as revision 5 in 65.1 seconds, with both specialists and a validated cited summary, using the same key and no retries.

The same named-change operation was verified through the local native-agent harness, including preservation of unspecified parameters and deadline cleanup. Separately, the real local engine evaluated that exact change using refreshed sponsor evidence and the same historical inputs. The changed footprint became **192 m²**, with **429.934 kg CO₂ per demand hour**. It remained rejected for access, CO₂ and queue reasons. Baseline and both unchanged alternatives had exactly identical results to the earlier evaluation. That standalone local check was initially saved only as an ignored verification artifact. The later successful native revision independently published the same requested parameter change into normal project history, with exact geometry/metric agreement.

### Focused checks

**61 focused Python checks** covering traffic calculation/publication/workspace, ranking and scouting passed, along with **four browser controller files**. The final focused Python run took under a second. The full 200-plus-test suite was not rerun. The checks cover historical-policy preservation, environmental ordering/ties, exact cohort accounting, geometry/hash agreement, rejected history, named parameter preservation, provider-failure restoration, foreign/stale publication, cancellation and unknown source checks. A read-only integration review found no additional substantive blockers. `git diff --check` passes. A full server restart and browser reload restored the earlier successful evaluation after the rate-limited continuation, with the latest failure and stale-input label intact. The saved rejected footprint remained inspectable on the map.

Release integration on top of `main` through `fb1b5eb` passed **83 focused Python checks** and **four JavaScript controller files**. The existing map/source fixes were preserved; unrelated property-tour/address edits remain outside this release. No full-suite run or additional live-provider run was needed.

## Remaining acceptance gaps

- The live count-linked scouting/evaluation/revision path is verified at Main/1st in the follow-up; its tested alternatives remain rejected.
- Obtain supported property access evidence and demonstrate an eligible real design. The small modeled CO₂ reduction at this site is insufficient to override a queue or access failure.
- Arbitrary intersection families, current turning-demand inference, conceptual 3D and core-release acceptance remain outside this checkpoint.

The local project retains valid rejected evaluations for inspection. Do not force a winner, weaken the policy, substitute distant demand, or imply that the unverified live acceptance steps succeeded.
