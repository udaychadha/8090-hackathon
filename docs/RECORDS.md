# Typed research records — Phase 1 report

Accepted on November 14, 2026. SQLite and the JSONL mirror remain the store;
the change adds validation and indexed projections rather than replacing it.

## Models

The canonical definitions are in [factory/record_models.py](../factory/record_models.py),
schema version `1.0.0`. Every owned field has a description. Lifecycle, variant,
data-need and event statuses use separate enums. Nested evidence is typed too.
The existing StrategySpec is imported and validated strictly at the storage
boundary; its strategy contract was not changed.

| Record | Evidence retained |
|---|---|
| Source | Identity, title, source kind, exact spec snapshot, source and PDF/Markdown provenance |
| Run | Lifecycle, historical source/variant/need snapshots, usage, measured time, cost completeness, errors and void history |
| Variant | Lane, test type/frequency, deterministic results, code/params, evals, equity, activity, notes and narrative |
| EvalResult | Number/name, deterministic passed flag and typed sparse telemetry |
| HealAttempt | Bounded attempt number, triggering error, fixed flag and remaining error |
| Critique | Preserved narrative with run/lane identity; no verdict authority |
| DataNeed | Dataset kind, required symbols/frequency/bounds, resolution status and proposed sources |
| Event | Global sequence, UTC timestamp, stage/lane, event state, message and typed telemetry |

All records have schema/identity/creation-provenance/void metadata. Missing
historical evidence remains missing or null. An unrecorded creation time is
null with origin `unknown`; event creation uses the actual recorded timestamp.
Year-only paper versions remain year-only. Historical source snapshots remain
independent of the source table's latest extraction.

The November 14 owner extension adds optional typed `gross_diagnostics` on
Variant and its nested Run snapshot. It contains separate zero-bps sensitivity
and decay observations, availability state/reason, and a deterministic failed-
variant label. It never changes authoritative eval records or verdicts. Historical
backfill preserves every other field, checks for concurrent changes, backs up the
database, and records before/after evidence fingerprints. Old rows remain readable
without materializing missing fields. Audit reports and backup metadata are
available through the interface's explicit audit inventory.

Every write validates before and after credential redaction. Rejected inputs
are excluded from exception messages. Reads validate payloads and their indexed
projections. There are indexes for run_id, source_id, variant, status, created_at
and voided on all eight tables. Explicit audit access is required for void rows
and their children; normal lookups, lists, event replay and trial selection hide
them. Numeric strings, impossible activity totals, misaligned curves, duplicate
evals/lanes, inconsistent identities and unsupported statuses are rejected.

## Migration evidence

- Individually validated all **411 database rows and 269 JSONL lines**.
- Reported **3,297 mismatches**, all missing schema/envelope fields. Applied
  **3,092 additions**, with no changed or relocated original fields in this store.
- Independently compared **106,215 original scalar values** after migration;
  every value and every record identity remains preserved.
- Post-migration audit: **zero mismatches**. Repeating migration is a no-op.
- Original database and JSONL backup:
  `runs/record-backup-20261114T111256571016Z/`, with fingerprinted audit metadata.
- Full per-row/per-line diagnostics and migration actions are local artifacts:
  `report/wo09-record-audit-before.json`, `wo09-record-migration.json`,
  `wo09-record-proof.json` and `wo09-record-repeat.json`.

| Kind | Default view | Explicit audit |
|---|---:|---:|
| Sources | 5 | 5 |
| Runs | 7 | 8 |
| Variants | 15 | 18 |
| Eval results | 50 | 65 |
| Heals | 22 | 22 |
| Critiques | 15 | 18 |
| Data needs | 5 | 6 |
| Events | 230 | 269 |

The three void variants and their evidence remain stored. The invalidated run
contributes no eligible trials. No metric or strategy verdict was recalculated.

## Validation and inventory

`ARENA_TEST_STORED_DATA=1 .venv/bin/pytest -q`: **327 passed in 99.71 seconds**.
Ruff and whitespace checks pass. All ten protected strategy/eval source files
match their pre-implementation fingerprints. Existing NumPy/calendar and SWIG
deprecation warnings remain; no warning was suppressed to obtain this result.

The first full test run exposed six failures from a shared orchestration fixture
with missing equity boundaries. The fixture now supplies a complete chart object; its original
failure-scope and verdict assertions are unchanged. No eval result changed.

Migration tests cover malformed records, unknown-field preservation, mirror
conflicts/order, rollback, backups, interrupted mirror-write recovery and
idempotence. Store tests cover default void exclusion, indexed filtering/sorting,
identity validation, projection corruption and secret-safe validation errors.

[RECORD_INVENTORY.md](RECORD_INVENTORY.md) maps every retained log and artifact
to an API and one of the seven screens. It distinguishes missing evidence from
zero values, current results from superseded captures, and reserved raw data
from safe metadata. These proposed API additions are implemented only after
updating AGENTS.md in Phase 2.
