# WO-12 checkpoint — November 14, 13:19 PT

Owner requested merge and push before unplugging the laptop. The implementation
is complete; experimental results and diagnostic backfill are still running.
Do not report the Congress experiments as finished.

## Implemented and checked

- Typed records, API and seven-screen interface, interactive/expanded charts.
- Owner-authorized Eval 4/5 correction and historical metrics-only rejudgment.
- Availability-gated event inputs, CSV upload, source/roster audits, frozen specs.
- Separate 0-bps sensitivity/decay diagnostics and deterministic labels on the
  leaderboard and tearsheet. No threshold or authoritative pass-rule changes.
- Gross writes defer until global idle and explicitly guarded legacy process exit.
- Fresh pre-push full backend check including all stored data: **515 passed**,
  265.51 seconds. Frontend: **36 passed**, production build and formatting passed.

## Live work — local files and processes are not in Git

Verify a PID's command before signaling it; PIDs can be reused after restart.

| Work | Identity | State at checkpoint |
|---|---|---|
| Normal All-Congress arena | `r_587be5f49c30`, PID `65120`, exec session `62818` | A finished evaluation; B in five-eval harness; C awaits validation. All lane records remain RUNNING until final judgment. |
| Congress gross replay | PID `70729`, exec session `33858` | Computing/staging; guards PID 65120 before publication. |
| Historical gross replay | PID `68120`, exec session `91225` | Intentionally SIGSTOP-paused during PCA C; restore staged results and resume after legacy arena exit. |
| API | exec session `31166`, port 8000 | Running with gross-aware schema; later artifact-inventory additions need restart. |
| Vite | exec session `61499`, port 5173 | Running. |

`report/wo12-runs.json` contains durable run IDs and completed control evidence.
The explicit SPY control `r_75d07564e86a_A` is FAILED_EVAL_5, 4/5, model cost $0.
VOID attempt `r_a0a8786ea3ff` exhausted repairs because the harness mistook ticker
NOW for a wall-clock request. No performance eval was reached; its exact candidates
were reused after the harness fix. Preserve its $3.0869281 model cost in totals.

No normal arena process was interrupted. No source/spec was revised from results.

## Compatibility staging and resumption

The live All-Congress process loaded the strict record model from `b3f6c97`.
It cannot read the new gross field. Fifteen already-computed historical results
were preserved in local `report/gross-diagnostics-staged.json`; only that new field
was removed from the database. `report/gross-schema-compatibility.json` proves
old-schema validation and exact restoration of the original historical payloads.
The current database remains readable by the running process.

1. Wait for `r_587be5f49c30` to be terminal **and PID 65120 to exit**. A terminal
   status alone precedes its final database reads. Preserve its outputs in
   `report/wo12-runs.json`; do not rerun, tune or rejudge the normal experiment.
2. With no active runs, restore the 15 staged gross fields. Read each current raw
   variant and its parent using `scripts.backfill_gross_diagnostics._raw`; require
   `without_diagnostics(current) == without_diagnostics(staged_variant)`. Then use
   `_apply_one(records, current, current_parent, staged_variant['gross_diagnostics'])`.
   This only restores diagnostic fields, including the matching nested snapshot.
   Keep the staging file and `runs/gross-staging-before.sqlite3` as local evidence.
3. Verify PID 68120 is still the historical replay before sending SIGCONT. Its
   in-flight computation and remaining candidates are preserved. If it is gone,
   restart the historical backfill, excluding the two Congress run IDs; existing
   completed fields are skipped. Do not retry known unavailable results blindly.
4. Let PID 70729 finish. It computes the three VOID retained candidates and reuses
   identical code/parameters/data evidence for the completed normal run, with fresh
   labels. Check all six report actions are `applied` (conflicts are explicit).
   The report is local `report/gross-diagnostics-congress.json`. An interrupted
   replay can be restarted with the same command below, after checking old PIDs.

```sh
python -m scripts.backfill_gross_diagnostics --apply --wait-running --wait-pid 65120 \
  --variant-id r_a0a8786ea3ff_A --variant-id r_a0a8786ea3ff_B --variant-id r_a0a8786ea3ff_C \
  --variant-id r_587be5f49c30_A --variant-id r_587be5f49c30_B --variant-id r_587be5f49c30_C \
  --report report/gross-diagnostics-congress.json
```

Do not create new datasets until this replay finishes: its conservative data
snapshot guard detects manifest or Parquet changes. No raw HOLDOUT observations
are read by that guard.

## Committee experiment — not started

The approved dated snapshots yield **zero qualifying purchases**, with no inferred
membership periods or publication dates. The frozen spec still runs, with
`short sample: not a verdict`, never eligible for VERIFIED. Source and roster
audits are committed; raw downloads stay local.

After both gross replays finish, create the genuine disclosure projection:

```python
from factory.congress import store_congress_events
store_congress_events(
    'data/source/congress/eligible_intermediate.json',
    committee_ids=[], name='congress_committee_trades',
)
```

It retains disclosed transactions with all-false `committee_match`, explicitly
documented in the manifest/UI; no qualifying purchase is fabricated. Then run:

```sh
python -u scripts/run_congress_acceptance.py congress_committee
```

Inspect generated code for the required committee flag and cash-if-empty behavior.
Do not add fallback trades or change the spec to escape INACTIVE. Normal bounded
self-heal remains unchanged. If pre-performance inactivity prevents the five
evals, report it honestly; do not invent Sharpe values.

After it finishes, run diagnostic-only backfill on its three IDs with
`--retry-unavailable` to measure valid zero targets if possible. Preserve all
authoritative statuses and eligibility flags.

## Final proof still needed

- `python -m scripts.report_congress_results` after both experiments and the control
  are terminal; it compares original evidence and reports all cost-grid Sharpes,
  gross diagnostics, wall time and total model cost including the void attempt.
- Re-audit typed records/JSONL, verify protected hashes and frozen spec hashes,
  inspect final real Run/Tearsheet views, and commit final reports/graveyard.
- Raw PDFs, data, database and credentials must remain uncommitted.

Frozen spec SHA256 values:

- All: `5c7ee2d1418ac7364981042433348eb04085c263a7b7d71cdbbe054349eb2c60`
- Committee: `d0d2c16764f8430e0bf55b6a1f6adf9829c5ec2d70f58dfa15b3418af0324bce`
