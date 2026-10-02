# Workflow Probe validation protocol

This release demonstrates three condition-change checks against a controlled local shop fixture. Its scores describe **these five known fixture profiles**, not performance on other sites or an AI classifier. The runner records observed values; an independent evaluator checks those values against the declared rules and compares the result with the fixture's seeded ground truth.

## Observation protocol

Run each of five profiles (`healthy`, `total-drift`, `duplicate-save`, `reload-loss`, `cosmetic-only`) through each of three relations (`SORT_TOTAL`, `SAVE_DUPLICATE`, `REFRESH_PERSIST`) three times. Every relation attempt uses a new browser context and a unique server session, including attempts on the same profile. Record the baseline in a separate fresh session so the baseline cannot create the relation's saved order.

The ordinary baseline must observe `app-ready=ready`, total **32000**, one successful single save, and saved count **1** for every profile. Failure to observe this is an execution or baseline error; it must not count as a discovered defect.

| Relation | Before | Change | After | Violation only when |
|---|---|---|---|---|
| `SORT_TOTAL` | Cart total and item order after ready | Sort the same items | Wait until the order visibly changes, then read total | Both reads are valid integers and totals differ |
| `SAVE_DUPLICATE` | Saved count 0 after ready | Activate save twice for one intent | Wait until all triggered saves settle, then read count | Both counts are valid integers and final count is not exactly 1 |
| `REFRESH_PERSIST` | One confirmed saved record | Reload | Wait for post-reload data hydration, then read count | Both counts are valid integers and final count differs from 1 |

For duplicate save, the fixture's business rule is **one saved record per intent**. This controlled fixture deliberately allows two quick activations to reach the server so it can test idempotent storage; the runner must observe exactly two POST requests and wait for both to finish. Another app could validly suppress the second activation in its UI, but that is outside this fixture's chosen probe. An action timeout, failed request, absent element, nonnumeric observation, uncompleted sort, or pending write is an `error`, not a `violation` or `pass`. Avoid fixed sleeps as the main completion signal. Use the fixture's observable order, ready state, and pending count or completed request signals. Capturing values immediately after `click()` risks missing the defect because asynchronous updates may not yet have happened.

## Independent acceptance checks

The evaluator should read `results.json` and fail on duplicate or missing `{profile, relation, repetition}` keys, unknown profile/relation/status, malformed evidence paths, missing before/after observations, nonfinite counts or totals, or anything except exactly **45** cases. Verify that each case's `status` agrees with its observed values using the relation definitions above. Do not accept a runner's `violation` label without a measured invariant breach. Keep the profile-to-defect mapping in evaluator or test code, not in the runner's verdict logic.

Expected ground truth: `total-drift × SORT_TOTAL`, `duplicate-save × SAVE_DUPLICATE`, and `reload-loss × REFRESH_PERSIST` violate. This yields **9/9** matching relation attempts, **36/36** other relation attempts passing, and **zero** execution errors. Each seeded profile should fail its matching relation in **3/3** attempts. The two clean profiles contribute **0/18** false alarms; the other relations on seeded profiles contribute **0/18** off-target alarms. All 45 ordinary baselines must pass. Distinguish these fixture counts from a statistical estimate of future bug detection or false alarm rates.

Useful negative tests for the evaluator are: change one observed after-value while leaving `status` unchanged; remove one case; duplicate one case; replace an integer with an empty string; point an evidence path outside the report directory; mark a baseline failure as a discovered violation. Each should fail evaluation. A mutation of a fixture profile should require a changed observation, not just a changed label.

Screenshots should show the fixture before and after each relation. At least one trace per detected defect should contain the action sequence and DOM snapshots needed to reproduce it. Store paths relative to the report directory and check that each referenced file exists. Dates, environment, and versions are provenance, not proof of detection by themselves.

## Interface QA

Check the Korean report on desktop and narrow mobile widths. The default report must give the counts, the specific changed values, how to reopen each fixture case, and a clear distinction between seeded defects and clean controls. Also load it with an empty case list and with invalid or missing result data: the page should state that no valid result is available, rather than show invented zero-error success. Long profile names and file paths should wrap without hiding controls. All links and buttons need keyboard focus and descriptive labels. The fixture itself should show a ready/loading state, save feedback, and the expected saved count after ordinary use.

## Release evidence

Keep the generated results and evaluator output with the source version used to create them. Rerun from a clean checkout in CI, with the browser installed there, and require the same matrix and zero errors. The public README should include the exact local reproduction command and explain that adapting the method to another app requires defining that app's own actions and invariants. The archived voice research remains identifiable but its prior scores should not be presented as evidence for this web fixture.
