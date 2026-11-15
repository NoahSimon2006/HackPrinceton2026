# Model reliability for the demo

Updated November 15, 2026. The existing xAI key successfully completed the previously failing traffic revision in **65.1 seconds**, with both specialists, a real local evaluation and a validated cited summary. No new account or key was required. These improvements are included in the Checkpoint 6 release.

## What was fixed

- Site and scouting agents share per-credential/model pacing, with at most two model requests in flight and a short interval between starts. Source investigations and delegation remain concurrent.
- A failed model request can receive two retries for transient rate limits, server errors or transport failures. Exponential backoff, jitter and provider Retry-After are respected. The app displays waiting/retry progress. Only the failed model request is retried; tools and simulations are not rerun by this mechanism.
- Capacity waiting is bounded to 60 seconds per model call and checks cancellation throughout. The existing overall run deadline remains in force.
- Authentication, permission and recognized credit/spending failures are not treated as temporary congestion. Messages distinguish these cases from temporary limits.
- Initial messages reference canonical files rather than embedding them again. Prior evaluations and specialist reports use compact fact indexes; full facts remain in local artifacts and citation validation. Specialists receive a current-source brief; the lead owns prior design context. Skill instructions match that division.
- Safe diagnostics retain usage counts, request-content size, classified failures and numeric rate-limit metadata. Prompts, keys, raw provider error text and general response headers are excluded. Raw response headers are removed before graph checkpoints.

The real project brief fell from **24,569 to 6,732 characters**, about **73% smaller**. Its specialist source brief is **1,795 characters**. Message-content character counts do not include tool schemas or every request field; actual token usage is also recorded separately.

## Observed live result

Project `02e9ba51a92b4920a8dec8a0dc3efedb` completed native revision **5**. The agent changed only south-long from **40 m to 60 m**, growing its footprint from **128 m² to 192 m²**. Baseline, south-short and east-short results were exactly unchanged. Geometry, metrics and input hashes matched. The final browser showed a fully cited review without an analysis error or incomplete-summary warning; both specialists completed and the lead consumed their reports.

The run used 16 model requests, 174,682 input tokens and 6,275 output tokens. It needed **zero retries** and reported no provider error. The earlier failed responses were not logged in enough detail to establish whether they reflected a burst, shared usage, or another provider restriction. This successful run proves the current key can handle the complete task; it does not prove the original 429 cause. Focused retry tests cover transient 429 recovery, Retry-After, shared cooldown, cancellation, fatal quota/auth handling and secret/header exclusion.

**31 focused tests passed in approximately 1.7 seconds.** No full-suite run was needed.

## Account and demo guidance

Keep the existing key. xAI documents limits by team and model, so another key on the same team does not create an independent allowance. A new account is not the recommended response to the observed app behavior. Current SDK response headers reported a 50-million-token limit and a 7,200-request budget; personalized account limits can be checked in the [xAI Console](https://console.x.ai) and interpreted using the [official rate-limit documentation](https://docs.x.ai/developers/rate-limits).

Before presenting, run one short normal workflow using the configured account. If the app reports a temporary capacity wait, let its bounded retry finish. A credit/spending message requires checking the existing account's billing or spending settings; retries cannot fund an account. No billing changes were made in this work.

Completed evaluations remain available if a later request fails. Live traffic remains transient and must be refreshed; saved historical simulations remain labeled as such. There is no automatic provider/account rotation and no disguised replay. The remaining absence of an eligible real traffic recommendation is a source/evaluation acceptance gap, separate from model availability.
