# Per-evaluation live results

The owner rejected the label-only progress change: a completed evaluation must
show its result and numbers while other evaluations or variants continue.

## Behavior

- Each variant has five clickable evaluation rows, with available outcomes,
  key measurements and a link into that evaluation's full detail and log.
- Results available and checks passed are separate counts. A known failure is
  visible immediately, even while remaining checks are executing.
- New executions persist Evals 1–4 independently at their completion boundary.
  Each write atomically retains the exact result, count and replayable event.
  A later exception does not erase completed evaluations.
- Eval 5 waits for the shared trial cohort and names the unfinished variants.
  Only an actual per-eval start event enables an active-check elapsed timer.
- The callback does not add strategy executions or alter any pass rule.
  An equivalence regression compares all results and the full execution sequence.

## Existing Congress process

The existing process `65120` was not stopped, paused, restarted or instrumented.
It loaded the older runner before this change. Its original Eval 1 cut details
and Eval 3 jitter reports remain in process memory until its final publication.
No process-memory access or additional backtest was used to retrieve them.

The read-only API exposes recoverable evidence now and labels its provenance:

| Variant | Available evidence during the run | Still unpublished |
|---|---|---|
| A | Lookahead passage established by entry into Eval 2; friction failure from saved cost grid; decay failure from complete saved daily equity | Sensitivity jitter report; shared-cohort Eval 5 |
| B | Same, plus sensitivity failure established by the unchanged positive-base guard | Jitter measurements; shared-cohort Eval 5 |
| C | Lookahead passage established by entry into Eval 2 | Later outcomes as the older runner publishes them |

At this snapshot, A's IS Sharpe at 5 bps is 0.0488256332 and B's is
-0.0365118759, below the unchanged 0.5 friction threshold. Their OOS Sharpes
are -0.4939844321 and -0.7209413937. These are saved measurements, not forecasts.

Decay recovery accepts only complete daily equity with matching counts,
boundaries and independently saved IS/OOS Sharpes. It rejects incomplete,
downsampled, intraday, inconsistent or numerically borderline evidence.
No cut or jitter measurement is invented. Original eval records supersede
recovery automatically; terminal verdicts and trial accounting are untouched.

The Run page and tearsheet use the same available evidence. Recovered tearsheet
metrics carry API-only provenance; the persisted record schema is unchanged.

## Evidence

- Final backend verification: **541 passed**, including the opt-in stored-data
  tests. Frontend: **46 passed**, including a mounted-page streamed-result
  transition and missing-result tearsheet states. Production build, formatting
  and lint passed.
- Browser evidence: `report/live-evals-ui/proof.json` and adjacent screenshots,
  using the actual local API without request substitution or write requests.
  Twenty desktop/mobile screenshots cover both themes, result selection and
  matching tearsheets. `read-only-proof.json` verifies A/B payloads remained
  byte-for-byte unchanged across Run, Tearsheet and Leaderboard GET requests.
- Regression tests: `tests/test_live_eval_publication.py`,
  `tests/test_live_eval_evidence.py`, `tests/test_run_progress.py`, and
  `web/tests/granular-progress.test.tsx`.
- Protected-file revision: `2026-11-14-live-eval-publication-v1`. Only runner
  observation hooks changed; config and all eval implementations retain their
  hashes from the preceding revision.

This report establishes the progress fix. The Congress experiments and their
diagnostic backfills are not yet reported complete.
