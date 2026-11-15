# Checkpoint 2 review · November 14, 2026

Historical checkpoint snapshot. See [Checkpoint 3](CHECKPOINT_3.md) for the current implementation and review boundary.

Checkpoint 2 is implemented locally on `codex/checkpoints-0-1`. Checkpoint 3 has not started. This work builds on the uncommitted Checkpoint 0–1 changes; nothing has been pushed or merged.

## What changed

The existing **Analyze site** request now runs one lead Deep Agent. Its `investigate_site` tool takes a short investigation plan and delegates a bounded pair of named Deep Agent jobs concurrently:

- **site-evidence** reads Vexcel parcel/building outlines, feature candidates and CoStar fields/frontages. Imagery search remains available when needed, distinctly labeled as search tiles rather than measured features.
- **domain-analysis** reads county rainfall/watershed in Stormwater. In Traffic, it checks the explicit traffic-input availability inventory: no verified demand, signal plan or queue observations are connected, and the archived assumed-demand artifact is excluded. It does not pretend to have fetched a new traffic dataset.

Each specialist has scoped tools and its own model context. Mandatory source reads happen inside each job before synthesis, so model failure does not erase retrieved evidence. The lead receives source facts and validated specialist summaries, then produces the existing cited screening review. These are actual separately invoked Deep Agents, scheduled by a fixed two-job executor inside the lead tool; unconstrained recursive delegation is not enabled.

The source collector now uses per-source locks. Network calls to different providers no longer share a lock. A brief ledger lock protects publication of measurements. Repeated reads of a source reuse that run's results.

### Virtual files and limits

Each run uses a StateBackend virtual project containing the compact brief, lead-authored plan, evidence index, specialist summaries, data-limit notes and final review. The specialists receive only their relevant evidence file. Host filesystem tools, arbitrary network tools, shell execution, unrestricted file writes and general-purpose delegation are not exposed. Files are ephemeral run state; durable multi-turn project memory is **not** claimed in this checkpoint.

The lead is limited to four model calls and each specialist to six. There are two concurrent site requests maximum, two specialist jobs per request, a cooperative 180-second run deadline, 35-second model HTTP timeouts and existing bounded source timeouts. A provider call already in progress may finish before cancellation takes effect; the job cannot start new work after its cancellation check. Request capacity remains held until active specialist jobs exit, preventing repeated cancellation from creating unbounded workers.

## Live activity and cancellation

`POST /api/site-analysis` is still the single analysis path. The UI requests newline-delimited JSON and receives server-authored activity events as work happens, followed by one terminal result. Existing JSON callers remain supported.

Events carry an opaque run ID, increasing sequence number, UTC timestamp, specialist, stage, status and a short operational summary. Source-result events include approved scalar facts and fact IDs. The timeline never serializes graph messages, model reasoning, prompts, credentials or raw provider payloads. Raw local geometry remains in the local final evidence response for map rendering; it is not sent to the model or emitted as timeline text.

**Agent activity** is collapsed by default. Expanding it shows starts, source results, validated summaries, failures and citation-validation retries. Source buttons open the corresponding fact with units, method, provider, observation/retrieval dates and map reference IDs. Existing evidence overlays continue to render after completion.

**Cancel analysis** aborts the browser reader and sends a run-specific cancellation signal to the local server. Changing the selected site or workflow does the same. Frontend run tokens and stream identities reject late events/results. Editing inputs during a run marks its eventual review stale. Retrieved facts remain available when a later synthesis or transport step fails; no source failure becomes a zero value or a fixture.

The previous proposal fixture remains an independently labeled UI test. Agent reviews do not claim to publish a physical design, traffic simulation or stormwater benefit calculation.

## Provider verification

- **Vexcel MCP:** completed authenticated `initialize`, `notifications/initialized` and `tools/list` against the official endpoint. Server reported `api-platform-mcp` 1.0.0, protocol 2025-03-26. The list advertised imagery, property, feature detection, DSM/DTM and other tools. Response framing required parsing SSE `data:` lines. This resolves the incomplete Checkpoint 0 handshake. Listing tools does not establish site-specific elevation coverage or entitlement.
- **Integration choice:** retained the working Vexcel API wrapper for imagery, outlines, detections and search. No duplicate MCP path was added for those capabilities. [Official Vexcel MCP setup](https://vexceldata.com/platform/vexcel-mcp/mcp-get-started/).
- **CoStar:** live local kit lookups supplied use, units where present, gross floor area, reported parking and frontage lengths. Raw records, property names/addresses, vacancy and coordinates remain outside automatic model context.
- **County:** live rainfall and subbasin calls succeeded at Kipling. The model receives the sourced rainfall estimate and watershed scalar facts, not boundary geometry.
- **Matterport:** no connected tool or verified relevant exterior scan was available. It was not added speculatively and is not required to complete this checkpoint.
- Reviewed [Deep Agents specialist documentation](https://docs.langchain.com/oss/python/deepagents/subagents) and [streaming interfaces](https://docs.langchain.com/oss/python/deepagents/streaming). The public stream deliberately projects only curated operational events rather than forwarding the raw graph stream.

## Acceptance evidence

### Real sites

**Kipling, Stormwater:** a live streamed run returned twelve facts and a cited review. The browser walkthrough subsequently showed both site-evidence and domain-analysis completing, followed by the completed lead review. Source evidence included Vexcel parcel 1,391.22 m² and footprint 1,024.16 m², CoStar 194 units and 25 reported spaces, and county rainfall 1.01 in / Ballona watershed. The review used both sponsor sources to explain why the unbuilt remainder is not automatically available treatment land and why parking/drainage must be checked.

In the browser, opened Agent activity during the run and activated **Selected parcel area** using the keyboard. It opened the measured fact, Vexcel source, observation date 2026-07-03, retrieval date and `outline-1` map reference. The source overlays rendered on completion. Screenshot saved locally at `/private/tmp/checkpoint-2-activity.png`.

**Olympic/Wall adjacent frontage, Traffic:** the final verification completed in approximately 55.5 seconds with both specialist summaries and a lead review. Both specialist jobs started at approximately 3.1 seconds; domain synthesis finished at 13.3 seconds and site synthesis at 35.5 seconds, demonstrating overlap. The review used Vexcel 98.24% footprint coverage and CoStar's 60 reported parking spaces / 154.05 m frontage to identify access questions and parcel constraints. Missing traffic inputs and benefits remained explicitly unassessed.

Earlier live runs hit the initial specialist call budget but preserved all source measurements and produced a lead review. Scope instructions were tightened and the specialist budget raised from four to six. The final traffic run completed both specialists. Numeric citation validation rejected unsupported numbers and required correction before publishing; the timeline reports that retry without exposing generated drafts.

Live JSON artifacts are under ignored `private/checkpoint2/`; they are not repository deliverables and contain local evidence geometry.

### Automated checks

- **18 Python tests pass.** Coverage includes actual Deep Agent graphs with scripted models; a barrier proves source jobs overlap; restricted fields/geometry do not enter model messages or activity; source/model failure preserves evidence; unknown citations and unsupported numbers are rejected; disconnect and deadline cancellation; matching NDJSON result identity; explicit run cancellation; and previous proposal/API/measurement checks.
- **Hydrology/planner controller checks pass:** partial source errors, retry, scenario separation, input staleness, site races, caching and canceled/superseded activity isolation.
- **Stream transport checks pass:** split UTF-8 chunks, identity mismatch, sequence mismatch, early termination and error events.
- **Proposal controller regression checks pass:** toggle, atomic revisions, stale inputs, site/workflow isolation and mixed-revision rejection.
- Python compilation, JavaScript syntax and `git diff --check` pass.

Desktop activity/source interaction was verified in Chrome. Narrow-screen visual acceptance remains the open Checkpoint 1 item; it was not claimed as completed here. Cancellation is covered by backend and frontend tests; instantaneous interruption of an already-running third-party HTTP request is not claimed.

## Try it and review boundary

Reload http://127.0.0.1:8001/#stormwater, search **Kipling**, select it, and choose **Analyze site**. Expand **Agent activity** while it runs. Select a source button to inspect its measurement. Use **Cancel analysis**, or change site/workflow, to stop following that run.

The next proposed checkpoint is **3: discovery maps**, subject to review. The real-data requirement still blocks a credible traffic comparison until verified demand, signals and queue inputs are obtained. Terrain routing and physical design/benefit evaluation remain outside this checkpoint.
