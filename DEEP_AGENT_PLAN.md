# Crossing Lab: evidence-led Deep Agent investigation

Status: implementation plan; application code has not been changed for this work.

## Product decisions

Confirmed by the user:

- Primary audience: city planners and transportation analysts.
- Geography: the current LA intersection catalog, with three thoroughly checked demo cases.
- Sparse evidence: explain missing information and propose specific checks; keep visual concerns separate from crash findings.
- Keep the Vexcel aerial map, smooth navigation, crash heat toggle, and expandable detailed crash reports.
- Replace the repetitive junction/farther/uncertain summary cards with useful findings. Preserve location uncertainty in the evidence and analysis.
- Focus on crashes first. Matterport is out of scope. Credentials and sponsor data remain outside Git.
- Use Grok with LangChain Deep Agents for a substantive investigation workflow.

Proposed defaults, pending the earlier product questions:

- An Analyze intersection button starts a run; map navigation alone does not spend model credits.
- Show real progress, then an evidence-linked report and follow-up questions.
- First release offers concerns, prioritized checks, and candidate improvements to investigate. Drawing redesigns and simulation are separate milestones.
- Target a 1–2 minute investigation, subject to provider latency and agreed budget; show partial results if a source fails.
- Deadline and total API spending limit remain unspecified. Do not interpret silence as a spending authorization or invent a budget.

## Current stack and gap

Verified installed: deepagents 0.7.38, langchain 1.5.0, langgraph 1.2.22, and langchain-xai 1.3.0. `planner.py` already uses `create_deep_agent` and `ChatXAI`; no framework migration is necessary.

The current tool allowlist exposes only collision totals, an assumed crossing calculation, and planning todos. It hides delegation and file tools, permits only three model calls, and requests a brief under 160 words. Detailed CHP records, Vexcel images, and CoStar context never reach the agent.

Retain Grok as the model provider and the existing Python server and Leaflet frontend. OpenRouter is optional and not needed to enter the LangChain track. Use the installed APIs and verify provider capability with a small, bounded integration check before expanding model usage.

## Intended experience

1. Select an intersection and inspect the aerial map and historical reports.
2. Start an investigation. Freeze its intersection, source versions, and scope so navigating elsewhere cannot change an active run.
3. Display actual events: gathering evidence, analyzing crash patterns, examining aerial context, reviewing guidance, and checking findings. Do not display fabricated progress or private model reasoning.
4. Show up to three prioritized findings. Each contains a concern, supporting evidence, location relevance, uncertainty, a concrete next check, and any candidate treatment worth evaluating.
5. Let the user expand source reports, imagery observations, references, and the investigation activity record.
6. Allow follow-up questions within that investigation, retaining its evidence and clearly distinguishing new research from previously gathered facts.

A sparse-data report must remain useful without manufacturing a pattern. An example structure is: two injury reports name these streets; one is farther along the road and the other has uncertain offset; this does not establish an intersection crash pattern; check the original report locations before choosing a site-specific treatment. Counts and details must come from the selected records, not this example.

## Agent workflow

Use one lead Deep Agent and three bounded specialist subagents. Each specialist has distinct tools and a defined result schema.

| Role | Evidence and responsibility | Deliverable |
| --- | --- | --- |
| Lead investigator | Plan the investigation, delegate relevant tasks, reconcile disagreements, request missing evidence within budget, and assemble findings | Investigation plan and validated report |
| Crash analyst | Read detailed CHP records and deterministic summaries; distinguish direct, nearby, and uncertain matches | Patterns, severity, denominators, supporting record references, and limitations |
| Site-context analyst | Inspect a bounded Vexcel crop and available street geometry; use CoStar facts only where relevant and permitted | Visible features with image references, uncertainty, and context |
| Guidance researcher | Retrieve relevant official guidance from a curated source collection, adding bounded live research if justified | Applicable options, mechanisms, tradeoffs, prerequisites, and source excerpts |

The lead performs the final evidence review; do not add another agent merely to increase the agent count. Missing imagery should skip visual analysis explicitly rather than prevent crash analysis. The model must not equate image appearance with observed crash causes.

Use Deep Agents planning, task delegation, and file tools in a restricted investigation workspace. Seed evidence through application code. Give each specialist its own output files and explicitly collect its results for the lead; verify sharing behavior rather than assuming subagent state is automatically shared. The agent cannot browse the repository, read `.env`, execute arbitrary shell commands, or edit source records.

## Evidence and tools

Implement typed tools for selected-site crash retrieval, deterministic aggregation, imagery retrieval, street context, and guidance retrieval. Tools return source references, period/capture date when available, retrieval time, and limitations.

- Improve source identity: the existing CHP export drops source report IDs and source version metadata. Keep a private provenance lookup and stable internal evidence IDs so claims are reproducible and aliases cannot double-count reports. Expose only the minimum public fields needed by the UI and model.
- Keep LAPD 2022–2023 ranking totals separate from CHP 2023–2024 evidence. Do not add their counts, infer trends across them, or silently apply the LAPD filter to CHP results.
- Preserve the 150 ft screening rule and unknown offsets as data. Do not treat it as proof of an exact intersection location.
- Compute counts, percentages, injury totals, time groupings, and missingness in Python. Show denominators and missing values; let the model interpret the supplied results.
- Identify imagery source, crop extent, and capture date if obtainable. Use image observations as hypotheses, not surveyed measurements. Prefer verified street attributes for dimensions.
- Establish whether sponsor terms permit submitting the required imagery and property fields to xAI before enabling those transmissions. Keep unnecessary sponsor fields local; never forward keys, archive passwords, or raw property dumps.
- Begin guidance retrieval with reviewed FHWA, Caltrans, and relevant LA material. A model's general knowledge is not a retrieved citation. External document text is evidence, not instructions to the agent.
- Do not introduce a vector database unless the size or retrieval needs justify one.

## Output and validation

Each finding should include: title, priority rationale, evidence IDs, observed facts, hypothesis if any, evidence strength with explanation, next action, candidate options, prerequisites, and unknowns. Report source periods and limitations once clearly, rather than repeating large disclaimers on every card.

Application validation checks that referenced evidence exists, quoted counts match calculated values, source periods are not mixed, and required fields are present. Unsupported claims trigger one bounded correction or are omitted with an explanation. A schema cannot prove that a causal claim is true, so combine automated checks with a small reviewed evaluation set.

Do not claim predicted crash reductions, calibrated traffic effects, exact costs, measured street widths, or construction feasibility without appropriate supporting inputs. Hide the current assumed crossing slider from the main investigation flow; only reintroduce scenario calculations when the user requests them and their assumptions are explicit.

## Run management and privacy

- Replace the single blocking brief response with a background investigation job and progress events or polling.
- Use a bounded worker pool, run IDs, cancellation, source timeouts, and explicit complete/partial/failed/cancelled states. Reject stale output when the selected intersection changes.
- Enforce shared model-call, token, and time limits across the lead and subagents; a per-agent cap alone is not a total budget.
- Account for calls already in flight when cancelling or enforcing limits. Track actual usage when returned; do not present a strict dollar cap without reliable accounting and conservative reservations.
- Cache reports by site, scope, evidence versions, model, and prompt version. Show cached status and generation time; allow a deliberate refresh.
- Keep model access server-side. Leave cloud tracing disabled by default. A local activity log can show delegation and tool results without exposing secrets or private model reasoning.
- Start with isolated in-memory investigation state. If saved reports are requested, store only permitted derived output in a private Git-ignored directory with a clear deletion action and retention policy.

## Delivery sequence

1. **Evidence foundation:** provenance, alias handling, deterministic summaries, three representative cases, and a documented imagery/provider capability check.
2. **Crash-only vertical slice:** lead delegates to crash analyst, reads an evidence artifact, validates a structured finding, and displays it with source drill-down.
3. **Context and guidance:** add visual and research specialists, source-linked hypotheses and options, and graceful missing-source behavior.
4. **Product flow:** real progress, cancellation, caching, report cards, expandable source records, and scoped follow-up questions. Remove redundant summary cards and keep the map intact.
5. **Demo verification:** run the three cases end to end, check claims against evidence, exercise failure paths, and prepare a short explanation of why each specialist was used.

## Acceptance criteria

- The lead actually delegates useful work; activity records demonstrate specialist tool calls and evidence artifacts.
- Every numerical finding matches deterministic data, every citation resolves to supplied evidence, and uncertain crash locations remain uncertain.
- Test cases cover a recurring pattern, sparse/uncertain reports, and useful aerial context. Select cases from actual evidence rather than forcing a desired narrative.
- Missing imagery, missing crash matches, rate limits, cancelled runs, and budget exhaustion produce truthful usable states without fabricated results.
- No unsupported source reads, secret disclosure, cross-investigation data leakage, or sponsor data committed to Git.
- The Vexcel map, heat toggle, ranking selection, and expandable reports continue working on desktop and mobile.
- A planner can answer: why review this location, what supports that concern, what should be checked next, and what cannot yet be concluded.

## Decisions still open

Earlier questions awaiting answers: analysis versus drawn redesign versus simulation; Analyze-button flow versus automatic or chat-first; acceptable wait; demo deadline and total Grok budget.

Implementation decisions to verify rather than burden the user with: source deduplication, precise SDK state-sharing behavior, structured-output compatibility, sponsor processing permissions, and source availability. Ask a focused follow-up only if those checks leave a material decision unresolved.

## References

- LangChain Deep Agents: https://docs.langchain.com/oss/python/deepagents/overview
- Subagents: https://docs.langchain.com/oss/python/deepagents/subagents
- Backends: https://docs.langchain.com/oss/python/deepagents/backends
- Streaming: https://docs.langchain.com/oss/python/deepagents/streaming
- Grok model: https://docs.x.ai/developers/models/grok-4.3
- Image understanding: https://docs.x.ai/developers/model-capabilities/images/understanding
- HackPrinceton workshop: https://github.com/langchain-samples/hack-princeton-intro-to-deep-agents
