# Checkpoint 1 — one workflow and selected-site identity

**Later update:** Checkpoints 0/1 were committed as `07c57af`; see [Checkpoint 2](CHECKPOINT_2_DISCOVERY.md) for current work. The status below records the Checkpoint 1 review.

Checkpoint 1 is complete and ready for review. The working branch is `codex/checkpoint-1-site-identity`, preserving all uncommitted Checkpoint 0 changes from the verified `99333b3` baseline. Nothing was committed, pushed or merged. The updated local app runs at **http://127.0.0.1:8003/**. Checkpoint 2A has not started.

## What changed

**One stormwater analysis path.** Removed the standalone “Compare your own placements” form, its request branch, comparison renderer and obsolete calculation/publication code. `stormwater.py` retains the shared event-storage balance. Optional keep-clear, runoff and treatment markings and rainfall scenarios remain available. The agent drafts from source evidence with no required drawings; edits invalidate the previous revision.

**Local property matching.** Map/discovery selections preserve their coordinates. A unique CoStar location inside the same mapped Vexcel parcel can supply property context. Nearby points alone never establish a match. Multiple properties or overlapping parcels produce explicit choices; choosing one uses that property's location. An outage leaves the point unassigned and still available for investigation. Both the browser and analysis endpoint validate association, and late responses cannot assign an earlier site's property.

**Bounded Vexcel evidence.** Requests now include capture date, collection and ground sample distance. Water begins with a point query and makes one 75 m neighborhood request when no containing parcel is returned; street queries retain the 200 m scope. Responses remain bounded to 250 source records and 5 MB, with capped results treated as incomplete. Resolution and agent tools share a short local outline cache while receiving separate copies for measurement.

Live responses contained several capture years despite `latest=true`. The adapter now selects the most recent dated returned collection at the point, or in the nearby search, instead of mixing successive parcel versions. Same-day collection ties remain explicit; actual overlaps still require resolution. This is the newest returned dated collection, not a claim of complete current coverage. Parcel/building dates remain visible, and unavailable building coverage cannot support a draft.

**Optional exterior context for the selected site.** Matterport requires the selected property ID and agreement among the local catalog address/coordinates, CSV model join and attachment metadata. Cross-property model matches are excluded. There is no default warehouse or automatic project relocation. Relevant exterior, courtyard, loading-area or roof descriptions are required; interior-only and unspecified tours are excluded following the user's clarification. Multiple eligible tours can be chosen within the same property. Titles suggest coverage; they do not prove it.

The viewer now lives under **Site evidence & adjustments → Optional exterior view**. No scan is required to draft or evaluate a concept. Proposed 3D remains unavailable. Mobile proposal controls were moved clear of the zoom buttons.

## Verification

| Check | Result |
| --- | --- |
| Python regression suite | **138 passed, zero skips**. Includes property ambiguity, source versions, bounded failures, association/URL validation, storage accounting, source isolation and traffic rules. |
| JavaScript controllers | **All six test files passed**. Includes late responses, revision identity, rejected traffic overlays, exterior-only viewer behavior, and shared HTML elements needed for page startup. |
| Live source association | Normandie at **229 S Normandie Ave, property 4355436**, matches uniquely from a map point. Kipling has an ambiguous map/property association; no property is silently assigned. |
| Live street source | Main/1st returns **54** parcel/building outlines with no measurement warnings. Its traffic result rendering and rejection/identity checks remain covered by the controller suite. |
| Live agent draft | A real Grok/Deep Agents run, with fresh sponsor/county evidence and **no drawings**, completed in 50.9 s with a mapped draft. |
| Live constrained revision | A second real run completed in 56.7 s after the first footprint was marked keep-clear. Input revision changed from 0 to 1, the proposal hash changed, and overlap with the protected footprint was **0 m²**. |
| Browser workflow | A third live run from a resolved map point displayed the actual draft and measurements. Property details were retained; the manual comparison was absent. Normandie's interior tour was excluded without opening a substitute. |
| Responsive checks | The actual draft was inspected at 1280 × 900. A clearly labeled local fixture checked controls at 390 × 844 after the CSS adjustment: no horizontal page overflow or proposal/zoom overlap. Temporary viewport overrides were reset. |

The constrained draft measures **12.546 m²**, with **1.882 m³** gross ponding capacity at an explicitly assumed **0.15 m** depth and **0.319 m³** direct rainfall. Contributing runoff, capture and excess contributing runoff remain **unassessed**, not zero. These are screening calculations, not established drainage connections or field-verified performance.

Normandie's linked apartment-interior tour is deliberately excluded. Kipling has no eligible verified exterior association. The warehouse exterior association remains accessible only when that warehouse is explicitly selected; its presence does not supply another site's scan. Exterior playback and intervention coverage still depend on the actual selected tour.

No new SUMO simulation was needed for this checkpoint: the network, demand and simulation engine were unchanged. The nine real-count Checkpoint 0 runs remain the recorded simulation baseline; this checkpoint does not claim a newly eligible traffic winner.

Private receipts are under `private/checkpoint1/`: `live-draft-1.json`, `live-draft-2.json`, `live-draft-checks.json`, `source-check-final.json`, `main-street-source-check.json`, source snapshots and test logs. Raw sponsor records, geometry and credentials remain ignored by Git. Model input remains the existing curated scalar/fact boundary.

## HERE follow-up

The replacement **HERE API key** authenticated successfully on November 14, 2026 at 23:26 EST. One bounded Traffic v7 `/flow` request returned HTTP 200 and **60 flow records**, with speed, free-flow speed, jam factor, confidence and traversability. The provider supplied `sourceUpdated: 2026-11-15T04:25:30Z`.

Saved `HERE_API_KEY` in the ignored mode-`0600` `.env`, alongside the working TomTom key. The earlier rejected access token remains a separate historical check. The secret-free receipt is `private/checkpoint0/here-api-key-check.json`. Both providers now have bounded access evidence; neither is integrated into the map yet. Account-wide remaining quota and production use/storage policy remain part of Checkpoint 2A.

## Review walkthrough and next boundary

1. Open Stormwater and search **229 S Normandie**. Select **Normandie — 229 S Normandie Ave**. Using **Use map center as site** demonstrates the parcel-based property match without moving the point.
2. Choose **Analyze site** with no drawings. Inspect the green draft, ponding capacity and unassessed runoff/capture values.
3. Under **Site evidence & adjustments → Adjust or add map markings**, add a keep-clear area and request a revision. The next footprint must respect that constraint and carry the new revision.
4. Under **Optional exterior view**, check Normandie: no relevant exterior tour is linked. The app remains on Normandie and the draft remains usable.

Next is **Checkpoint 2A: useful traffic discovery**. TomTom remains the planned starting provider; HERE's now-verified structured area response can inform the adapter assessment. Expanded stormwater discovery, native persistent agent delegation/skills and researched candidate selection belong to later checkpoints. No work on those checkpoints is claimed here.
