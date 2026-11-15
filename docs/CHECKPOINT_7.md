# Checkpoint 7 — existing-site walkthrough

Review date: November 14, 2026. Branch: `codex/checkpoint-7`.

**The user-approved existing-site viewer is implemented. Full Checkpoint 7 comparison acceptance is not met. Stop for review.** The user selected 510 E Olympic Boulevard and explicitly chose to build the existing-site viewer first, keeping Proposed unavailable until a supported 2D proposal exists. This scope does not complete Checkpoint 5 or resolve the [Checkpoint 6 core release blockers](CHECKPOINT_6.md).

## Try it locally

Run the current Python server on port 8001 and reload <http://127.0.0.1:8001>. In either planning mode, find the **Exterior walkthrough** card below property search and choose **Open existing view**. This selects 510 E Olympic Blvd on the map and opens its linked exterior/loading-docks tour. Press the embedded Play control to explore. **Existing** is selected and **Proposed** is disabled, with the missing design/alignment explained in the dialog.

The dialog provides Close, Retry viewer, an external Matterport link and source details. Closing unloads the iframe and restores focus to the opener. Site/workflow changes cancel pending requests and unload an open viewer. The provider loads only after an explicit open action. An iframe load event is not treated as proof that the tour rendered or that it covers an intervention.

## Source association and limits

The local CoStar kit associates property `6067080`, Wall Street Garment Center at 510 E Olympic Blvd, with Matterport model `35LT5s1GSfA`. The backend requires agreement between:

- The unique property/model row in `commercial-properties.csv`, including address, Los Angeles and California.
- The matching property record in `data/commercial-property.jsonl`, its address/coordinates, and the existing allowlisted property catalog.
- The attachment caption **3D Tour of the Building Exterior & Loading Docks**, model key and supported external reference type.

The API constructs the fixed [Matterport tour URL](https://my.matterport.com/show/?m=35LT5s1GSfA) itself and ignores attachment URLs. It returns only the selected property summary, model, source association and limitations. Missing, duplicate, corrupt or inconsistent inputs produce a generic unavailable response rather than another tour or raw source details. The attachment date, December 5, 2024, is listing metadata; it is not a verified acquisition date or a current survey.

The public tour page returned HTTP 200 with the matching exterior address/title and an active, public model. Visual inspection confirmed an exterior gate, loading/garage entrance and nearby paved access area. This establishes a usable existing-site view. It does **not** establish coverage of an as-yet unspecified intervention, metric registration, surveyed dimensions or a comparable proposed viewpoint.

No Matterport SDK, SDK key or proposed 3D geometry is introduced. The viewer does not consume development-fixture geometry or raw agent results. The local association remains checked each time the viewer is opened; current provider availability still depends on the external service.

## Privacy and lifecycle

Opening the viewer makes ordinary browser requests for the approved public Matterport model. The iframe uses `no-referrer` and requests only fullscreen capability. It sends no raw CoStar records, local file paths, credentials or planner geometry. This feature makes no Grok call and does not expand the existing model-sharing boundary.

Both backend and frontend enforce the selected property/model pair. The frontend accepts only the fixed HTTPS Matterport destination and its single model parameter. Every retry creates a fresh iframe, and stale request/iframe callbacks cannot reopen or repaint a closed viewer. Unsupported property selection inside the Vexcel coverage guard prevents opening the view.

## Verification

- **81 Python tests passed**, including seven new source-association and failure-boundary tests.
- **All five JavaScript suites passed**, covering discovery, hydrology, analysis streaming, proposals and the new viewer controller. Viewer coverage includes explicit initiation, destination validation, selection guards, cancellation, retry, focus restoration and permanently disabled Proposed. The viewer suite was rerun after formatting the attachment date for display.
- The real local `/api/site-view` and `/site-view.js` returned HTTP 200; the root page contains the new entry control. The API resolved the expected model from the configured kit.
- Desktop Chrome: opened the integrated modal, loaded the actual exterior tour with Play, switched to Dollhouse, closed the modal and verified focus returned to Open existing view. Keyboard activation of that opener was also checked.
- Responsive CSS is implemented, but a narrow-screen visual check remains pending because native browser control became unreliable. No mobile visual pass is claimed.
- Escape is handled when focus is in the host dialog. The cross-origin Matterport viewer may consume Escape while it has focus; the visible Close button remains available.

Local verification artifacts are ignored by Git: `private/checkpoint7/public-tour-check.json`, `private/checkpoint7/site-view-descriptor.json` and `private/checkpoint7/exterior-tour.png`. The saved image shows the public tour, not the integrated app modal. Source records and credentials are not committed.

## Remaining work before full 3D comparison

1. Produce a supported, published 2D proposal at this property, with reproducible metrics or an explicit unassessed outcome.
2. Confirm the scan covers that specific intervention and identify a usable comparable viewpoint.
3. Establish a defensible alignment using recognizable site features and suitable dimensional evidence.
4. Render concept objects from the validated published geometry and revision, and verify that revisions update both 2D and 3D views consistently.

The existing uncommitted Checkpoint 6 changes were preserved on this branch. This pass leaves implementation local and stops for the user's review.
