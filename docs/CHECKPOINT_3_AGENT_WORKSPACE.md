# Checkpoint 3 — persistent agent workspace

Implemented on `codex/checkpoint-3-agent-workspace`, following Checkpoint 2 commit `e8fed6a` (`Add current traffic and expanded stormwater discovery`). Checkpoint 3 is ready for review and remains uncommitted; nothing was pushed or merged.

## What changed

The desktop map now saves a project for a selected site and workflow. It retains the brief, user instruction history, map constraints, rainfall scenario, revision, source evidence, supported results and a stable agent thread. **Saved projects** reopens earlier work; **Continue project** uses the same project. **Project files** exposes the application-owned brief/constraints, investigation plan, specialist reports and design/evaluation artifacts. Live activity shows assignments, source calls, skill reads and file reads/writes without streaming private reasoning.

The dated automated-count and turning-movement-count layers, their legends and their introductory guidance are removed from discovery. Traffic discovery contains current speed/free-flow estimates and connected slow approaches. Verified historical turning sheets remain internal simulation inputs. A location can use a sheet only when exactly one verified counted intersection is within 25 m; source PDF/hash/network checks still apply. This never moves the chosen site or substitutes a distant intersection's demand. Current speeds do not become volumes or emissions.

## Native agent execution

The pinned Deep Agents 0.7.38 API now receives configured `CompiledSubAgent` runnables for `site-evidence` and `domain-analysis`. The lead delegates through the native **task** tool; two independent calls in one response overlap through the graph's tool execution. The old custom `investigate_site` / fixed Python thread-pool wrapper is gone. The general-purpose agent is disabled for xAI, and the task boundary permits only the two configured specialists once each per run.

Six trusted skills are registered through `skills=["/skills/"]`: opportunity scouting, property association, traffic evaluation, stormwater concepts, proposal publication and source recovery. Skill metadata is available initially; the full relevant procedure is read through **read_file**. A review cannot finish without the relevant skill read, required source attempts and validated citations/numbers. The lead must write a plan and read both current-run specialist reports before publication. This follows the installed implementation and the official [subagent](https://docs.langchain.com/oss/python/deepagents/subagents) and [skill](https://docs.langchain.com/oss/python/deepagents/skills) interfaces.

The backend is a bounded virtual `StateBackend`, not host filesystem access. Filesystem permissions and backend checks both protect skills, canonical user constraints, evidence and evaluation outputs. The model can write its own notes; only the lead can edit the plan. Specialists return only their own changed file namespace. This prevents an inherited old report from overwriting a sibling's new report on continuation.

Specialist handbacks are short artifact references. The lead retrieves saved reports for synthesis. Current brief context contains the goal and recent user instructions; the complete unmodified instruction history is available in the read-only constraints file. Previous long model exchanges are cleared from the active context between turns, with a bounded previous-review artifact retained where permitted. Current explicit user edits supersede conflicting earlier requests; model-authored notes cannot change user constraints.

## Persistence and recovery

`private/agent-workspace/` contains ignored local SQLite project records and native LangGraph checkpoints (`langgraph-checkpoint-sqlite==3.1.0`). Files are created with mode 0600 inside a private directory. Project identity, thread identity and run identity are separate. Optimistic versions reject stale browser saves; the server rejects an analysis whose body differs from the saved revision. Only the current run can publish results or replace artifacts. Concurrent runs on one project are blocked while an earlier run is stopping.

Browser reload restores the saved selection and its constraints. A server restart marks unfinished runs interrupted, preserving inputs, events and completed artifacts. Continuation starts a new bounded run on the saved project; it does not blindly replay an interrupted simulation. Completed source facts survive a specialist synthesis failure. If a specialist ends in plain prose instead of the required structured output, the application writes a clearly partial report from its actual retrieved facts so the lead can proceed.

Each agent has a 12-model-call ceiling. Source tools deduplicate per run; only transient transport failures receive one retry. Source recovery can inspect the supported imagery search or neighborhood query while retaining the chosen site. Simulation remains one comparison per run. Overall run budgets are 240 seconds, or 420 seconds for a matched traffic simulation; provider calls retain bounded timeouts. Cancellation and input changes prevent stale publication.

### Short-lived traffic stays out of the archive

Raw TomTom tiles and flow snapshots retain the existing in-memory, maximum-60-second cache policy. Live traffic facts and model prose derived from them are also excluded from durable project records and checkpoints. A traffic run that can query the feed uses an in-memory native graph, then saves a clean continuation checkpoint containing user inputs, independent source facts and local simulation artifacts. On reopening, the UI explains that live review content must be refreshed. This preserves continuity without building a historical traffic feed archive, consistent with the [TomTom live-service conditions used by the integration](https://download.tomtom.com/open/banners/third-party-product-terms-eula-2022-06.pdf).

Raw sponsor records, exact generated geometry, property names/addresses, restricted source fields and credentials remain outside agent context, reports and streamed events. Coordinates and geometry still exist in local application-owned records for map restoration. LangSmith tracing remains disabled. User-authored planner text is shared according to the existing interface disclosure.

## Verification

- **160 Python tests and seven JavaScript test files pass**, with zero Python skips. Dependency consistency passes.
- Native graph tests exercise overlapping specialists, actual skill tools, artifact publication/consumption, unknown citations, unsupported numbers, source outages versus empty results, transient retry bounds, unstructured-specialist recovery and traffic evaluation gates.
- A fresh Python subprocess reopens the SQLite thread, reads its previous review and continues with the original access constraint plus the new user request intact.
- Tests cover canonical-file and skill write denials, no host-file writes, conflicting browser saves, stale run rejection, cancellation/disconnect, interrupted-server recovery, and exclusion of live traffic from persistent artifacts/checkpoints.
- Desktop browser verification used the real Grok/Vexcel/CoStar/county/terrain workflow. The first run preserved a driveway-protection request and asked for a keep-clear marking when the source could not locate access. Its reports and brief survived an actual server restart and browser reload.
- After an explicit revision allowing a conceptual placement using mapped constraints, the continuation produced a **12.55 m²** rain-garden draft with **1.882 m³** proposed ponding storage and **0.319 m³** direct rain. Contributing runoff and capture remained unassessed. The successful continuation used **15 model calls across all agents**, completed in about **83 seconds**, and showed overlapping specialist work. One specialist returned a partial source report; the lead consumed it and completed the validated review.
- Desktop layer controls show current flow/slow approaches without the retired count layers. No expanded mobile QA was prioritized in this checkpoint.

The live continuation exposed two defects during verification: parallel inherited files could overwrite a fresh sibling report; and an unstructured specialist ending could leave the lead unable to proceed. Both have regression coverage and were fixed before completion.

## Scope and next checkpoint

This checkpoint provides persistent direct-site analysis and preserves the existing 2D draft/evaluation tools. It does **not** add researched location shortlists, new physical design templates, complete conversational geometry revision, conceptual 3D, or a newly verified eligible traffic winner. Existing traffic simulation source validity and eligibility gates remain in force.

Next is **Checkpoint 4: researched location selection** — goal plus bounded area, up to three sourced opportunities, environmental-first comparison, separate feasibility/disruption and readiness, then explicit selection. The direct-site shortcut remains available. Desktop remains the primary interface.
