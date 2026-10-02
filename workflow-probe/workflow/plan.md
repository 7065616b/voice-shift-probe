# Workflow Probe — blueprint v1

Status: complete for prototype v0.1. Date: 2026-10-02.

## Confirmed scope

Pivot the condition-change principle from Voice Shift Probe into a local web-app verification system. Preserve the original voice research in the same public repository. This first release proves the method on a controlled fixture, not on unseen production applications. No paid service, account system, or deployed service is needed. UI assumption: a simple Korean dashboard showing actions and before/after evidence.

## Requirements and acceptance

| Requirement | Task | Acceptance |
|---|---|---|
| REQ-01 Observe ordinary behavior before a perturbation | TASK-01 Fixture; TASK-02 runner | AC-01 All five fixture profiles pass their ordinary path |
| REQ-02 Detect violations of business invariants | TASK-02 runner | AC-02 Detect sorting-total, duplicate-save, and refresh-persistence violations independently |
| REQ-03 Avoid alarms for healthy and cosmetic changes | TASK-03 evaluation | AC-03 No violation on either negative control, over three repetitions |
| REQ-04 Produce repeatable evidence | TASK-02 runner; TASK-03 evaluation | AC-04 45 relation checks, zero execution errors; each seeded defect repeats 3/3; before/after values, screenshots and traces saved |
| REQ-05 Explain findings and retain research lineage | TASK-04 report/docs/release | AC-05 Korean report works on desktop/mobile, empty/error states checked; archive voice README and keep voice files; public source and CI available |

## Frozen interfaces

Fixture module `fixture/server.mjs` exports async `startFixture({port=0, host='127.0.0.1', reportDir})` returning `{url, close}`. CLI `node fixture/server.mjs` serves on port 8787 by default. Static app at `/?profile=healthy&session=<unique>`. Profiles: `healthy`, `total-drift`, `duplicate-save`, `reload-loss`, `cosmetic-only`.

Canonical cart total: 32000 KRW. The DOM exposes `data-testid` values: `cart-total` (integer text), `sort-items` (button), `save-order` (button), `order-count` (integer text), `pending-count` (integer text), `app-ready` (text `ready`). Optional visible status uses `role=status`. Server keeps state by session; POST saving the same intent is idempotent except the intentional duplicate bug. All single-save ordinary paths show exactly one saved record. Sorting preserves price and item identity. Saving then refreshing preserves the saved record. A double click for the same intent should create exactly one record (application-specific requirement, not a universal rule). Cosmetic-only changes layout/style, never semantic values. Each relation uses a fresh session/context.

Runner `src/run.mjs` exports `runSuite({baseUrl, outputDir, repetitions=3, playwrightPackage})` and CLI `node src/run.mjs [--output <path>] [--repetitions 3] [--base-url <url>]`. Without base URL it starts/closes the fixture itself. Playwright import supports `PLAYWRIGHT_PACKAGE` env override, otherwise normal package resolution. Runner does not use the seeded defect mapping to decide violations. Result JSON at `<outputDir>/results.json`: `{schemaVersion:1, generatedAt, environment, cases:[{id,profile,relation,repetition,baselinePassed,before,after,status:'pass'|'violation'|'error',message,artifacts:{before,after,trace}}]}`. Relations: `SORT_TOTAL`, `SAVE_DUPLICATE`, `REFRESH_PERSIST`. Screenshot/trace paths are relative to outputDir. Traces may be saved only for violations/errors; screenshots for every case. Ordinary baseline is initial total 32000 and single-save record count 1, then a fresh session for the relation. Runner exceptions must become errors, never detected defects. Report rendering/evaluation owned by root.

## Ground truth and experiment

The independent evaluator knows: total-drift only fails SORT_TOTAL; duplicate-save only fails SAVE_DUPLICATE; reload-loss only fails REFRESH_PERSIST. The runner sees observations, not expected outcomes. Five profiles × three relations × three repetitions = 45 checks, 9 expected violations. Report both seeded-defect recall (3/3) and negative-control false alarms (0/18); do not present them as general real-world accuracy. Ordinary-path success is separately shown across cases.

## Assignments

Root: plan, integration, report, package/CI, evidence, public release. Fixture agent: fixture only. Runner agent: src/run.mjs and helpers only. Protocol reviewer: independent review and docs/validation-plan.md only. No overlapping ownership.
