# Typed records, API and interface implementation plan

Goal: expose the existing research pipeline through a truthful, usable local web
application matching the seven supplied boards. The owner's November 14 request,
AGENTS.md and docs/DATA.md define behavior; docs/mockup defines visual design.

Keep SQLite and its JSON payloads. Use canonical Pydantic record models and
indexed projections, FastAPI under /api, and React/Vite/TypeScript with one API
module. Complete, test, report and commit each phase before progressing. Failed
acceptance checks keep work in the current phase until corrected.

## Phase 0 — Housekeeping

- Commit the owner's modified AGENTS.md alone; merge wo05-wo07 into main.
- Create wo09-wo08-api-interface and regenerate WO-08/09 from the blueprint.
- Read every mock-up image and preserve the supplied design references.
- Verify branch ancestry, document references and protected-file fingerprints.

## Phase 1 — Record schema

- Inventory actual database payloads, every JSONL line, writers and artifacts.
- Define Source, Run, Variant, EvalResult, HealAttempt, Critique, DataNeed and
  Event in one module, with versions, field descriptions and status enums.
- Test rejection of malformed writes, lossless/idempotent legacy migration,
  mirror reconciliation, indexed queries and default exclusion of void runs.
- Back up and migrate real records; report every mismatch and retained field.
- Route all writes through models; retain unknown historical facts as null.
- Report model coverage and each artifact's API/UI surface before Phase 2.

## Phase 2 — API

- Extend AGENTS.md's API contract before implementing additional response shapes.
- Implement typed runs, leaderboard, variants, structured graveyard, dataset
  previews/coverage, ingestion/audit, artifact inventory and read-only eval schema.
- Derive summaries and ordered steps deterministically from recorded evidence.
- Implement durable PDF intake and replayable SSE, including live completion,
  reconnect, failed extraction and explicit audit access for void records.
- Test documented endpoint shapes against isolated copies of all real records;
  test missing inputs, path traversal, secret redaction and background failure.

## Phase 3 — Interface

- Extract board tokens; build shared components and a single API access module.
- Build Run, Leaderboard, Tearsheet, Graveyard, New run, Evals and Data screens.
- Preserve failure detail, test type, n/5, visible limitations and unknown values.
- Keep unavailable controls disabled and labelled; make PDF submission real.
- Check frontend types/build, navigation, filtering, stream updates, error and
  empty states before committing.

## Phase 4 — Proof

- Start both services and inspect all screens using the eight existing runs.
- Save screenshots to report/; exercise the void audit view explicitly.
- Upload one approved local paper in the interface and observe real completion.
- Run the full test suite, reconcile UI results with records, and report measured
  time/cost and intentional deviations from the boards. Commit evidence/docs.

## Constraints and review points

- Do not modify factory/evals/config.py, eval logic or the strategy contract.
- Mock-up names, numbers, status examples and fixture counts are fictional.
- No model-authored text determines or substitutes for factual result summaries.
- Preserve legacy evidence and report conflicts; never silently drop fields.
- Void runs are retained but excluded by default in every query and projection.
- Expose artifacts through inventory identifiers, never arbitrary local paths.
- Do not expose secrets, raw HOLDOUT values to strategies/models, or private keys.
- No new market downloads, trades, deployment or unsupported future controls.
- Do not commit data, PDFs, keys or runtime databases. Use scoped subagents for
  independent audits/reviews when helpful; keep one working branch and folder.
