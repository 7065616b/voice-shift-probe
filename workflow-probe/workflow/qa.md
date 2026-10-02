# QA — blueprint v1

Date: 2026-10-02. Actual browser: Chromium 151.0.7922.34. Local host: Windows, Node 24.19.0.

## Executed checks

| Acceptance | Result | Evidence |
|---|---|---|
| AC-01 Ordinary paths pass | PASS, 45/45 separate baseline runs | report/results.json baseline values |
| AC-02 Three independent relations detect defects | PASS, 3/3 seeded defects, 9 violations | report/evaluation.json; 32000→29000 KRW, 0→2 saved records, 1→0 visible records |
| AC-03 Negative controls avoid alarms | PASS, 0/18 control alarms; 0/18 off-target alarms | report/evaluation.json |
| AC-04 Reproducibility and evidence | PASS, each defect 3/3, zero execution errors, 90 nonempty screenshots, 9 nonempty traces | tools/verify.mjs; actual report artifacts |
| AC-05 Report and research preservation | PASS for local report: desktop 1280 px/mobile 390 px, filters, evidence images, empty/missing/error data states, no script errors | report/ui-qa.json; docs/preview.png, docs/preview-mobile.png |

Node tests: 10/10 pass. These include isolated fixture storage, duplicate-intent behavior, missing/duplicated cases, failed baseline exclusion, contradictory verdict rejection, negative-control alarms, evidence-path validation, and embedded-data escaping. They are separate from the actual 45-case browser experiment.

## Independent review and fixes

A separate reviewer required observation-based evaluation, actual sort completion, exactly two transmitted save requests, initial state validation, baseline failure exclusion from defect counts, safe artifact paths, and separate execution-error reporting. These checks are implemented. A demo CLI mismatch was corrected with tools/demo.mjs. Mobile heading layout was improved after visual inspection.

## Limits and status

No unresolved major implementation issue in this scope. The three fixture bugs are intentional experimental ground truth. The refresh bug hides saved records on the refreshed screen; it does not delete stored records. Results demonstrate this known fixture, not general accuracy, novelty of metamorphic testing, or learned AI capabilities. Each new application needs explicit invariants and actions. Full local artifacts are about 20 MB; the public snapshot includes source and numerical observations and CI regenerates the full run. Automatic approval review rejected public trace ZIP upload because archives can contain network/resource data. Public PNG upload was also rejected because the exact image payloads were not verified as free of personal information. Screenshots and ZIP files remain local and are excluded from the public repository and CI artifact upload. Source and numerical observations provide public evidence; screenshots and traces can be regenerated locally.

Public release: commit 399f0c42705df3c1e729da9fce714ba67e0f1260. Linux CI [run 36955561736](https://github.com/7065616b/voice-shift-probe/actions/runs/36955561736) passed: 10 Node tests, archived source/observation fingerprints, 45 actual browser checks, independent evaluation, and 6 report UI checks including the public text snapshot. The previous voice-research CI also passed after this release. Public runtime artifact 11205762195 contains five HTML/JSON files and excludes images/trace ZIPs. This confirms cross-environment repeatability on the controlled fixture.
