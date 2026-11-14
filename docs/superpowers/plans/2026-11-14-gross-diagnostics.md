# Gross diagnostics implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans task by task.

**Goal:** Explain gross sensitivity/decay without altering authoritative verdicts.
**Architecture:** Observe existing strategy targets, score zero-bps returns with existing pure pass rules, persist a separate typed object and expose it through the normal API. Backfill retained variants without model calls or verdict mutation.
**Tech stack:** Python/Pydantic, pandas, FastAPI, React/TypeScript.
**Spec:** AGENTS.md, Owner-requested gross diagnostics.

## Constraints and review focus

- No eval thresholds or pass rules change; diagnostic results never join eval_results.
- A jitter crash fails sensitivity; undefined Sharpes/concentration remain null.
- Inactive/bug variants keep explicit unavailable evidence; no invented returns.
- Backfill preserves all original status/eval/trial evidence; running rows are skipped.
- UI labels cannot be mistaken for VERIFIED and must show pending/unavailable reasons.

## Tasks

- [x] Backend: tests first for 0-bps scoring, rule reuse, unchanged net verdicts and execution count; implement factory/gross_diagnostics.py plus typed record, evaluation and orchestrator integration.
- [x] API/UI: tests first for both labels and unavailable values; project the typed object on leaderboard and detail, build one shared diagnostic presentation using existing tokens.
- [x] Backfill implementation: test evidence preservation and replay with no LLM; persist only gross_diagnostics with per-variant availability and provenance.
- [ ] Verify full backend/frontend suites, build, real API/browser views, unchanged protected hashes and historical verdicts. Commit on the current branch.

Implementation checks: 499 Python tests passed, one stored-data scan opt-in skipped;
36 frontend tests, production build, formatting and lint passed. Real browser proof
has 18 checks and 14 screenshots across desktop/mobile and dark/light. Historical
replay is in progress; the active Congress run will be backfilled after completion.

The owner has already requested autonomous implementation and supplied the design; no additional design approval is required.
