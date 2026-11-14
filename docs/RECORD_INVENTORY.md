# Pipeline record and artifact inventory

Observed on 2026-11-14 from the local repository. This is a Phase 1 inventory
and proposed read API mapping, not an implementation or a change to the fixed
API contract. The proposed additions below require the corresponding AGENTS.md
contract update before implementation. Only this document was written during
the inventory. SQLite was opened with `mode=ro`; no pipeline, model, provider,
ingest, repair, migration, or evaluation was run. Secret files were not opened.

## Evidence and scope

Read AGENTS.md, docs/DATA.md and factory/data_contract/contract.yaml in full;
inspected production writers under factory/, existing database payloads,
JSONL logs, paper sidecars, generated strategy files, report structures, data
metadata and manifests. File counts exclude `.gitkeep`, Python bytecode and
secret files. Data row counts below are the sums of stored manifest facts,
not a new full-file validation. No raw HOLDOUT bars were loaded. All five PDF
and Markdown fingerprints were freshly checked against their sidecars and
matched. All 18 strategy files matched the code retained in their variant row.

No factory/api/ implementation or built web application was present at this
inspection; docs/mockup/ is a design reference, not a results source. Therefore
every endpoint below describes the intended future surface, not an existing one.

## Authoritative research records

`runs/factory.db` contains seven payload tables with `(id, run_id, payload)` and
an eighth `events` table with `(seq, payload)`. There are no foreign-key-backed
joins or typed payload columns. SQLite is authoritative; JSON exports and the
JSONL event file are derived evidence.

| Table | Exact count | Retained information | Future API and screen |
|---|---:|---|---|
| sources | 5 | Source identity/title/kind, complete StrategySpec, paper provenance | `GET /api/sources` and `/api/sources/{id}`; source selection in New run, source drawer in Run and Tearsheet |
| runs | 8 | Status, embedded variants/source/needs, wall time, per-call usage, cost completeness, errors; void audit on one run | `GET /api/runs` plus existing `/api/runs/{id}`; Run history and selected run |
| variants | 18 | Code, params, evals, charts, narrative, notes, activity when measured, original result and eligibility when void | Existing leaderboard and variant endpoints; Leaderboard and Tearsheet, including explicit audit navigation |
| eval_results | 65 | Variant, `number`, name, passed, complete metrics object | Existing `/api/variants/{id}` must join these, mapping `number` to `n`; Tearsheet eval table/drilldown and Run lanes |
| heal_attempts | 22 | Variant, attempt, triggering error, fixed, optional result_error | Existing `/api/variants/{id}` must join these; Run repair timeline and Tearsheet history |
| critiques | 18 | Variant and narrative text | Existing variant endpoint and graveyard, plus structured graveyard entries; Tearsheet and Graveyard |
| data_needs | 6 | IDs, local price requirement, symbols/frequency, bounds, status, provider/candidates | Existing run detail, joined by run_id; Run needs cards and links to Data |
| events | 269 | Global sequence, timestamp, run, stage, variant, event status, message and arbitrary structured data | Existing run SSE plus paginated read/export; Run event console and evidence links |

There are 18 unsuccessful repair records and 4 successful repair records
(22 total: `fixed=false` 18, `fixed=true` 4). No attempt code snapshots are
stored: `worker.validate_and_heal` overwrites the same strategy file on each
attempt. The UI can show exact recorded errors and final code, but cannot
truthfully show historical code diffs.

The current database has 5 COMPLETED runs, 2 FAILED extraction attempts, and
1 VOID run. The variants comprise 10 FAILED_EVAL_2, 4 INACTIVE,
1 BUG_UNRESOLVED and 3 VOID; there are zero VERIFIED variants. The normal
leaderboard should contain 15 rows. Ten nonvoid variants reached all five
performance eval records (50 rows); the void run retains its 15 historical
eval records. Four INACTIVE variants have IS activity only; the unresolved
variant has no activity record. Thirteen variant payloads have equity arrays:
eight intraday arrays of 604 dates including the three void variants, and five
daily arrays of 2,185 dates. Missing charts/activity are unavailable, not zero.

| Run | Current state | Variants | Role |
|---|---|---:|---|
| r_449ef7fd3ae6 | VOID | 3 | Original Gao debug run, invalidated for session-time inactivity |
| r_e7094212a558 | COMPLETED | 3 | Beat the Market |
| r_17ac8caf8a59 | COMPLETED | 3 | Gao rerun |
| r_b8116b8c72ef | COMPLETED | 3 | Miao |
| r_654a63b4217c | FAILED | 0 | Initial daily extraction failure |
| r_275efbdfa468 | FAILED | 0 | Initial daily extraction failure |
| r_d1b6cda53684 | COMPLETED | 3 | Avellaneda–Lee retry |
| r_ffbba23dbcff | COMPLETED | 3 | de Groot–Huij–Zhou retry |

The failed extraction runs lack a retained source in their run payload and
have empty usage arrays, `cost_complete=false`, and null cost estimates. Their
paper associations are retained in WO-17 report reconciliation. They must stay
reachable in Run history even though they have no leaderboard rows.

Sources use INSERT OR REPLACE by source_id, so the source table contains the
latest extraction for a repeated paper. Preserve each run's embedded source
snapshot when presenting its historical spec. A mutable current sidecar is not
proof of the spec used by an earlier run.

## Event streams and void audit

`runs/events.jsonl` contains exactly 269 valid JSON objects, sequence 1–269,
and freshly compared equal to the ordered SQLite events with seq inserted.
Stage counts are extract 14, data 12, worker 36, eval 118, critic 36,
heal 44 and done 9. Event status counts are started 85, passed 84, failed 99
and info 1. These status values describe events, not strategy verdicts.

Serve SSE from committed SQLite rows, filter by run_id, replay from seq=0 and
preserve global sequence IDs (per-run gaps are valid). Read paths must not
instantiate Records merely to query: its constructor creates tables, commits
and repairs the JSONL mirror. Provide `GET /api/runs/{id}/events/history`
with `after_seq` and `limit` for paginated inspection and a sanitized JSONL
artifact export. A completed run may later receive a void audit event, so the
latest run state must also be fetched when opening historical evidence.

The voided run records `void_reason`, `voided_at`, `original_result`,
`leaderboard_eligible=false`, and `eval_eligible=false`; all three child
variants retain corresponding audit fields. Void rewrites headline status,
passed count and selected metrics, but preserves eval rows, code, charts,
critique and original headline values. `original_result` is not a complete
copy of the original payload.

Proposed explicit audit navigation: voided runs and their child records are
excluded by default everywhere. Run history lists seven nonvoid runs; an
explicit `include_voided=true` audit toggle makes all eight reachable. The
Leaderboard offers an “Invalidated runs” link to a separate audit view, not
ranked rows. Direct run, variant, event and graveyard reads also hide voided
evidence unless `include_voided=true` is explicitly supplied. Audit responses
retain original_result and reason. Tearsheet and Graveyard show a VOID banner
when opened in audit mode and exclude this evidence from current performance
claims and trial counts.

## Data inventory and operational records

There are 560 physical Parquet files, 560 adjacent `*.manifest.json` files,
560 ingest metadata JSON files, and 3 tier `manifest.json` files. No
`data/catalog.json` or event datasets exist. No completed staging chunks remain.

| Group | Files | Manifest row total | Stored Parquet bytes | Role |
|---|---:|---:|---:|---|
| data/1min | 50 | 14,620,048 | 265,092,847 | Main minute tier |
| data/1day | 507 | 1,334,248 | 41,846,187 | Main daily tier |
| data/smoke/1day | 3 | 30 | 16,012 | SPY, NVDA, BRK.B smoke fixtures; separate namespace |
| Total | 560 | 15,954,326 | 306,955,046 | Do not merge smoke with production |

Both main tier manifests say complete=true with no failed_symbols. Minute
requested coverage is 2023-11-12 through 2026-11-12; daily is 2016-01-01
through 2026-11-12. Actual bounds vary by symbol and remain in file manifests.
All three tier manifests retain shared IS/OOS/HOLDOUT bounds. Show split
boundaries, schema version, counts and sealed-holdout status; never offer raw
full-file Parquet downloads or arbitrary bar browsing through these endpoints.

| Artifact family | Count/content | Proposed read API | Screen |
|---|---|---|---|
| Per-file manifests | 560; hash, schema/calendar versions, provider/feed/adjustment, actual/requested bounds, rows/fill rate, write time | `/api/data/catalog` summary and `/api/data/datasets/{id}` detail | Data, with Tearsheet dataset links |
| Ingest metadata | 560; request_id/normalizer version, source/off-session/observed/filled/missing/expected counts and bounds | Same dataset detail, separate provenance section | Data |
| Tier manifests | 3; universe, completeness, failed symbols and split boundaries | `/api/data/tiers/{frequency}`; smoke distinguished by namespace | Data |
| data/ingest.jsonl | 2,916 records: 2,357 chunk_written, 557 symbol_complete, 2 wide_load_benchmark | `/api/data/ingest-events?scope=main&after=...&limit=...` | Data ingest history |
| data/smoke/ingest.jsonl | 6 records: 3 chunk_written, 3 symbol_complete | Same endpoint with scope=smoke | Data audit/fixtures section |
| data/audit.json | Historical passed=true, 557 symbols, 0 errors, 2 split checks; 50-symbol wide-load timing 0.9004766 s | `/api/data/audits` and `/api/artifacts/{id}` | Data validation history |
| data/audit.txt | Human-readable earlier audit output, 58,999 bytes | Sanitized text artifact with timestamp and historical label | Data |
| data/sp500.csv and sp500.source.json | Membership snapshot and its source/timestamp, 1 each | `/api/data/universe` and sanitized artifact detail | Data, daily survivorship note on Tearsheet |
| data/wo02-smoke.json | Cash-only SPY/QQQ IS plumbing check: 175,446 timestamps, 453 daily observations, passed=true | Diagnostic artifact, never a strategy verdict | Data audit section |

The ingest log is a different schema from run events (`time`, `event`, plus
event-specific fields); do not coerce it into fake run stages or assign run IDs.
The canonical loader currently validates whole files before slicing; that is
trusted storage validation, not authorization for the UI or workers to read
HOLDOUT observations. The metadata API can work from manifests without loading
bar values. Existing audits are historical evidence, not fresh checks.

## Paper and strategy artifacts

`papers/` holds five supplied PDFs, five extracted Markdown files and five
`.spec.json` sidecars. Each sidecar has source provenance, strategy_spec and
extraction_status=extracted. Provenance includes source URL, title/authors,
version/date, PDF/Markdown hashes, extraction method/page count and verification
notes; field names vary between the Zarattini sidecar and the other four.
The Markdown is extracted full text, not a summary. Five hash pairs match.

| Paper/source ID | Current extracted type | Version caveat to show |
|---|---|---|
| Zarattini / p_2a866756fd687af9 | replication | Working paper dated 2025-09-22; owner verified title/authors on page 2 |
| Gao / p_9eb3b8cfaadaf4ea | transfer | Published 2018 source; current extractor's transfer decision and ambiguities must be retained |
| Miao / p_fade5394af7796cd | transfer | Published 2014 source; original universe/frequency differs |
| Avellaneda–Lee / p_8b43c1557289c64f | transfer | June 2009 working-paper version, not final cited 2010 article |
| de Groot / p_4d2abb8be9065ecb | transfer | July 2011 accepted manuscript, not final typeset publication |

`GET /api/sources/{id}` should return normalized provenance, spec/ambiguities,
claimed metrics and typed artifact links. New run shows available supplied
papers and their extraction state; Run and Tearsheet show the exact run spec
and provenance. Sanitized Markdown and spec JSON can use the artifact viewer.
PDFs are local source documents, never automatically re-fetched; serve only
registered local source IDs with a safe PDF response, never arbitrary paths.

`strategies/` contains 18 Python files under five source directories and six
run directories, three lanes each. Existing `/api/variants/{id}` code and
params cover them; add a sanitized plain-text artifact download. Code is
displayed/escaped, never executed by the browser. No original proposals or
intermediate repair code archives exist.

## Report, export and backup artifacts

`report/` contains 20 non-placeholder files: 17 JSON, 1 Markdown, 1 HTML and
1 JPG. `runs/` has the live database/mirror, one SQLite backup, two JSON exports
and one empty lock file. The following registry covers every retained report
and export; links use opaque allowlisted artifact IDs.

| Artifacts | Count and meaning | Surface |
|---|---|---|
| report/wo17-r_{run_id}.json | 7 per-attempt exports, including the two extraction failures | Run evidence via `/api/runs/{id}/artifacts` |
| report/wo17-results.json, report/wo17-results.md | 2 reconciliations of 5 final papers and 7 attempts | Run history batch summary; links from Leaderboard |
| report/wo17-paper-reruns.json, report/wo17-daily-retries.json | 2 intermediate batch/retry summaries | Run batch history; retain attempt-to-paper association |
| report/wo17-void.json | 1 audit summary: VOID, zero eligible trials, retained eval evidence | Run void audit and Tearsheet |
| report/wo17-audit-step1.json | 1 pre-migration audit: 560 files, 3 groups, 0 recorded issues, schemas/checks, calendar examples, fingerprints, smoke comparisons and cross-tier examples | Data audit history; sanitize value-bearing samples before raw export |
| report/wo17-migration.json | 1 list of 560 validated paths, row counts and hashes | Data migration history |
| report/wo17-load-validation-probes.json | 1 list of 4 historical probes; three were accepted by the old loader, negative volume rejected | Data audit history, prominently pre-fix evidence |
| report/wo17-canary.json | 1 deterministic calendar-only canary: 753 traded dates, no overnight exposure | Data and Rules evidence; distinguish full-grid diagnostic from strategy evaluation |
| report/wo17-fixture-before.json, report/wo17-fixture-after.json | 2 regression snapshots, each clean/intraday_momentum status, evals and returns | Rules evidence and Data validation history; compare without re-running |
| report/wo07-real-paper.html, report/wo07-real-paper.jpg | 2 historical backup presentation artifacts for now-VOID run | Run audit attachments, with current VOID banner before viewing |
| runs/wo05-second-extraction.json | 1 extraction-only result with spec, time and token/cost usage | New run source extraction history and Run artifact registry |
| runs/wo07-real-paper.json | 1 export updated to VOID with original result and reason | Run void audit |
| runs/wo17-before-void.sqlite3 | 1 historical DB backup: 1 run, 1 source, 3 variants, 15 evals, 3 critiques, 1 need, 0 heals, 38 events | Run audit inventory with metadata and sanitized structured evidence; never expose DB bytes |

WO-17 recorded execution wall time is 3,249.613457 s for seven attempts;
recorded estimated model cost is $3.8120628, explicitly incomplete because
two extraction failures lost usage. Show that as a partial estimate, not a
complete batch price. The original VOID run is separate ($0.6193235,
162.894193 s). Per-call usage records retain model, input/output/cache token
counts, wall_seconds and cost_usd, but no response text and no explicit role.
Do not invent exact role-by-role costs from ordering assumptions.

The old HTML still says Completed and FAILED_EVAL_2 rather than VOID. Its JPG
is a historical capture, not a current dashboard. The API wrapper must identify
both as superseded before download/preview; never scrape them for current
leaderboard values. HTML is active content: provide escaped source or a
sandboxed preview, not same-origin untrusted execution.

## Graveyard and Rules evidence

`wiki/graveyard.md` has 18 actual run/variant entry headings (26 level-two
headings total because narratives contain their own headings), matching the
18 critique records. Its first three entries explicitly mark the old run VOID.
The database critique text alone does not supply that current audit banner.
The existing `/api/graveyard` can return sanitized Markdown; add
`GET /api/graveyard/entries` with run/variant IDs, current and original status,
eval count, test_type, narrative and notes so every entry links to its
Tearsheet. Render Markdown without raw HTML execution. Do not infer records
solely by splitting on every `##` heading.

Rules should link to `GET /api/data/contract` for the canonical contract and
generated docs, alongside planned eval schema/profile APIs. The contract is
version 1.0.0; generated docs/agent reference identify source fingerprint
710a14aeaab18348bfe3e864502dfdfc3072cabd7c7758715546ff75f45a4b91.
`factory/data_contract/generate.py` produces docs/DATA.md,
factory/data_contract/agent_data.md and generated.py from contract.yaml.
These are three representations of one contract, not separate policies.
Present rules from their owning source, not ad-hoc duplicate prompt text.
No saved custom profiles or eval schema endpoint exist yet.

## Existing writer map

| Existing writer | Writes / retention behavior |
|---|---|
| factory/agents/records.py: Records.put/event/_mirror | All seven payload tables, events table, atomic events.jsonl mirror and events.lock; payloads redacted |
| Records.void_run | Atomic parent/child invalidation and one audit event; preserves original evidence, repairs mirror on idempotent retry |
| factory/orchestrator.py: run_paper/_finish | Source/need/run/variant/eval/critique records through Records, state events, append-only graveyard narrative; stdout final JSON |
| factory/agents/worker.py: validate_and_heal | Final/current strategy file, replacing code at every attempt; bounded heal rows/events through Records |
| factory/agents/extractor.py: paper_text/_save_metadata/extract | Verified Markdown cache and atomic spec/provenance sidecar; CLI extraction JSON to stdout |
| factory/ingest_alpaca.py: event/atomic_json/ingest_symbol/ingest_tier/daily_universe | Ingest JSONL, chunk/final Parquet via validated storage, ingest metadata, tier manifests, sp500 snapshot/source; completed chunks deleted; lock file |
| factory/audit_data.py: audit | audit.json and wide_load_benchmark ingest event; human-readable audit output to stdout |
| factory/data_contract/storage.py: write_dataset/attach_manifest/_atomic_json | Validated Parquet + adjacent manifests and atomic temporary files; attach_manifest preserves existing file bytes |
| factory/data_contract/migrate.py | Adds manifests via storage and optional JSON migration/check report |
| factory/data_contract/generate.py | Generated documentation, agent data reference and Python validators |
| factory/evaluation.py | Returns exact captured equity/activity/boundaries to orchestrator; no independent file writer |
| factory/evals/runner.py CLI | Evaluation result JSON to stdout; no persistent eval artifact writer |
| factory/sandbox.py and _sandbox_child.py | Temporary strategy/request/per-symbol input Parquet, stderr.log, weights.parquet, result.json in temporary execution directory; these are ephemeral execution transport, not retained records |

No checked-in production writer was found for the WO-17 batch/reconciliation
reports, SQLite backup, WO-05/07 JSON exports, WO-07 HTML/JPG, audit.txt or
WO-02 smoke JSON. They are existing acceptance/debug artifacts produced by
prior invocations or session scripts; provenance comes from their contents
and work-orders/WO-01, WO-02, WO-05, WO-07 and WO-17. Do not pretend these
have an automated refresh job. Tests also write isolated fixtures, not product
records. Empty .gitkeep and lock files are operational markers, not UI content.

## Concrete API additions and containment

Keep the existing summary contracts useful, with joined records rather than
requiring the browser to know SQLite/filesystem layout. Proposed additive
read routes are `/api/runs` (all attempts), `/api/sources`,
`/api/sources/{id}`, `/api/runs/{id}/events/history`,
`/api/runs/{id}/artifacts`, `/api/artifacts`, `/api/artifacts/{id}`,
`/api/data/datasets/{id}`, `/api/data/tiers/{frequency}`,
`/api/data/ingest-events`, `/api/data/audits`, `/api/data/universe`,
`/api/data/contract` and `/api/graveyard/entries`.

An artifact descriptor should carry id, kind, title, owning run/source/dataset
when known, media type, byte size, observed timestamp, historical/current
label, sanitization policy and detail/download links. IDs must resolve through
an allowlist; no path parameter, directory listing, symlink escape or arbitrary
file read. Metadata makes excluded raw files visible as retained evidence
without making unsafe bytes downloadable.

Apply recursive credential redaction at read/export boundaries as well as at
write time. Additionally remove URL userinfo and capability/auth query values:
one existing paper source URL contains a Dropbox `rlkey` parameter. The current
environment-value redactor alone does not guarantee safe historical URLs.
Never expose secret files, environment dumps, API request headers, raw database
bytes, prompts, sandbox input files or raw HOLDOUT bars. Audit JSON containing
value-bearing price examples needs field-level allowlisting before export;
hashes, counts, schema, validation outcomes and calendar boundaries can remain.

Every record/artifact family above has a home in one of the seven screens:
New run owns source preparation, Run owns attempts/events/accounting/audit,
Leaderboard owns eligible comparison and audit links, Tearsheet owns variant
evidence, Data owns ingestion/storage/validation, Graveyard owns narrative,
and Rules owns the deterministic contract and profile evidence. There is no
need for an eighth primary screen or a raw filesystem browser.

## Contract and evidence gaps to resolve before implementation

1. AGENTS.md's LeaderboardRow status union omits current INACTIVE and VOID,
   despite prose defining them. Add these explicitly and distinguish run
   status from variant verdict and event status.
2. Stored variants omit profile/default_status/default_evals_passed. A read
   adapter can explicitly identify current records as the default profile
   and mirror their current deterministic verdict, including VOID, while
   preserving original_result. It must not rejudge or fabricate custom data.
3. Eval storage uses `number`, API specifies `n`; heal records and eval records
   are not embedded consistently in variant payloads. Join all canonical rows.
4. Run summaries omit accounting, extraction error/diagnostics, activity,
   equity timestamp boundaries and void audit from the fixed API shape.
   Extend the contract so UI access is intentional and tested.
5. DataNeed start may be a timestamp string and end is null in actual records;
   both differ from the documented unconditional date fields. Preserve unknown
   ends and define nullable/normalized fields, rather than invent coverage.
6. Source provenance fields vary; the current sidecar may be newer than the
   historical run source. Retain both and name their scope. Current extracted
   test_type is not always the candidate table's initial expectation.
7. Missing catalog.json does not mean missing data. Build the read catalog
   from existing manifest/metadata evidence with explicit smoke separation;
   do not label prices unverified merely because future catalog work is absent.
8. Historical reports and captures can conflict with current VOID state.
   Current database status wins; original evidence remains reachable as audit.
9. A future uninterrupted live run may have events before final variant rows
   exist, because _finish writes final variants at the end. Run lanes must use
   live events plus the latest summary without inventing completed records.
10. Some outputs never existed: repair code history, saved prompts, authoritative
    invoice cost, event datasets, provider connection records and custom eval
    profiles. Show unavailable states, not synthetic history or zeros.
