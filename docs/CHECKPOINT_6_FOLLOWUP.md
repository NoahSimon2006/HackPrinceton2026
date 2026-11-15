# Checkpoint 6 follow-up — traffic acceptance gaps

November 15, 2026. Scope remains Checkpoint 6. Checkpoints 7 and 8 have not started; advancing requires the user's instruction. This follow-up is included in the Checkpoint 6 release, integrated with `main` through `53ed99e`.

## Supported scouting path

A fresh native area investigation around Main and 1st returned a live opportunity spatially linked to that intersection's verified manual turning sheet. The candidate was explicitly selected through the normal scout-selection API while its evidence was current. The resulting saved project is `a7e30e1ea73441b0a1953f1b4a18c90d`, from search `13e9281e5c644d40a580ccb1312da973`.

The first native site evaluation completed as revision 2 in 111.6 seconds, with no analysis error, no final-synthesis warning and no model retries. It used the actual linked November 8, 2011 PM 5–6 sheet and the existing checked network. Current flow identified the location; it was not used as historical turning demand. Three designs were evaluated: eastbound 40 m curb extension, westbound 80 m bicycle-space reallocation and northbound 60 m pedestrian-space reallocation. All were rejected. Both specialists were delegated and their artifacts consumed; the domain specialist's structured summary was incomplete, and its retrieved facts were retained through the existing partial-report recovery. The lead still completed a validated cited review. This does not claim both specialist summaries succeeded in that first pass.

Live traffic measurements and geometry were not archived. The independent historical comparison and selected project are retained normally.

## Native revision and map inspection

The same selected project completed a native named-change revision as revision 3 in 109.1 seconds, again with no provider error or retry. The requested westbound 80 m → 20 m and northbound 60 m → 20 m changes produced two 64 m² footprints. Names, approaches, uses, lane allocation and all omitted parameters were preserved. The baseline and untouched eastbound design's result objects were exactly unchanged, and the saved history contains revisions 2 and 3. The comparison hash begins `bcbebcea`.

All alternatives still failed the operational/access/crossing gates. Shortening did not establish an eligible design, and the application did not promote lower total emissions caused by fewer completed trips. The browser restored revision 3 after reload and displayed the revised westbound footprint with its 20 m description, 64 m² area and tested/rejected label. This is a focused Checkpoint 6 inspection, not full Checkpoint 7 acceptance.

The domain specialist again returned partial evidence without a structured report; the lead completed the cited final review. A bounded specialist-only repair now gives one corrective graph turn when mandatory sources and the required skill have been read but the model ends in plain text. That turn exposes only the cited SiteReview schema, retains the original validators and call limit, and blocks source/filesystem calls. Invalid correction falls back to partial evidence. The final live verification completed as revision 4 in 95.1 seconds: both specialist reports and the cited lead review succeeded, with no provider errors, provider retries, analysis error or incomplete-summary warning. This run did not need a format correction; the corrective branch itself is covered by focused tests. All simulation result and layout objects exactly matched revision 3, so no design or favorable outcome was substituted. History now contains revisions 2, 3 and 4. The browser restored revision 4 and displayed the same 64 m² tested/rejected footprint (hash prefix `c7cd6a64`). Its saved screenshot hides the live-traffic layer; no live-feed geometry or measurements are retained in that proof.

## Access evidence audit

The local CoStar catalog contains 1,581 properties and 36 frontage entries. Only five entries across five properties have both valid frontage geometry and nonnegative integer curb-cut counts. Both populated frontage schema paths are already read by the adapter; no additional usable access field was found.

None of the four verified counted sites has usable frontage/access records within 200 m; none has valid frontage geometry within 500 m. Main/1st, Beaudry/1st and Hill/1st have no CoStar properties within 200 m. Beaudry/Temple has one nearby Multifamily property but no frontage record. A lack of records is not zero access conflict.

Only one usable frontage is inside the downtown pilot, on East Olympic Boulevard. No locally inventoried manual-count intersection is within the existing 200 m association radius. The nearest candidate is Main/Pico, over 600 m away, with cached unavailable sheets; Hill/14th is over 900 m away. Those records cannot be borrowed for the frontage location.

A bounded external-source check found the City of Los Angeles [Sidewalks Mapped Areas inventory](https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/Sidewalks_Mapped_Areas/FeatureServer), including driveway and drive-sidewalk layers near the studied intersections. Its source description ties the inventory to 2014 aerial imagery and a 2017 digitization effort, says it is not actively maintained, and notes that obscured features may be omitted. Service edit timestamps do not establish a current complete field survey. This is useful supplementary historical context, but absence cannot certify present access clearance. It was investigated, not added as a gate-passing substitute or represented as CoStar evidence.

## Focused corrections

- Nearby traffic features now group only when their road name and checked direction agree. A stronger signal on another road or in the opposite direction can no longer suppress a distinct supported counted-site opportunity solely through proximity. Environmental ordering, exact representative geometry, the 25 m count-link threshold, expiry and water grouping are unchanged.
- When malformed frontage geometry is omitted from map output, valid remaining frontage entries retain `coverageComplete=False`. Downstream access checks preserve an unknown result. The native site-agent path already guarded its unavailable-source case; this closes a gap in direct reuse of the measurement output.

The corrections passed 14 focused scouting tests, 24 measurement/ranking tests and 12 site-agent tests (50 total). The agent regressions cover successful report correction, bounded failure, unsupported numbers, hidden source calls, cancellation and the existing model-call ceiling. No full-suite run was needed.

## Remaining boundary

An eligible real traffic recommendation is not established. Current source coverage cannot support the required access clearance, and the tested alternatives also fail operational or crossing checks. Lower simulated emissions accompanied by stranded trips are not accepted as an environmental improvement. No gate, demand, source-association radius or expiry rule was relaxed.

Checkpoint 7 and conceptual 3D remain outside this work. Separate property-tour/address edits in the shared checkout were preserved.
