# AGENTS.md — Financial Models In the Arena

A software factory for quantitative research. A trading idea goes in, either as
a research paper or as a plain-English description. Three candidate
implementations come out. A deterministic verification harness decides which,
if any, survive. The product is a web app, not a CLI. Built for the 8090 EVOLVE
hackathon.

**Hard deadline: code freeze Saturday Nov 14, 3:30pm PT. Feature freeze 1:00pm.**

## License

Original project code, documentation, tests and project-owned design assets are
MIT-licensed under [LICENSE](LICENSE). Keep the Python and frontend package
license metadata consistent. Preserve third-party notices and source terms;
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) records the scope and the
PyMuPDF dependency's AGPL/commercial licensing. Do not relicense third-party
papers, datasets or dependency code as project-owned MIT material.

## Status (Fri Nov 13, 10:15pm PT)

**Plan change, Fri 10:40pm:** parallel tracks are dropped. One session, one
folder, one ordered queue (see "Order of work"). WO-16 added.

Done and merged on `main`: WO-01 data, WO-02 contract/engine/sandbox, WO-03
Evals 1–2, WO-04 Evals 3–5. Records are in `work-orders/WO-01..04.md`; the
choices recorded there stand.

Measured so far:
- One full five-eval pass on an intraday strategy: 12.3 s.
- `tests/fixtures/clean.py` (daily vol-scaled trend): passes Evals 1 and 4,
  fails Eval 2 at Sharpe 0.47 against the 0.5 threshold, fails Eval 5.
  Expect few or zero `VERIFIED` results. That is acceptable; do not tune.

## The one idea to protect

LLM agents write strategy code. **Only deterministic, non-LLM code judges it.**
The analogy we are demoing: idea = ticket, strategy = pull request, strategy
evals = CI, eval failure fed back to the worker = the factory loop.

Rules that follow from this:

- Never weaken, skip or special-case a strategy eval to get a pass. Agents may
  not change the default values in `factory/evals/config.py`. Users may adjust
  thresholds only through eval profiles, inside fixed bounds (WO-16); the
  default verdict is always computed and shown.
- Workers never see out-of-sample or holdout data. Only the harness touches it.
- Self-healing is for **bugs only** (runtime error, contract violation,
  lookahead leak). A strategy that fails Evals 2–5 is dead. Re-prompting until
  it passes is overfitting to the evals.
- No LLM call may influence a pass/fail decision.
- Every dataset that is not price bars carries an `available_at` timestamp
  (when the world could have known it). Strategies only ever see rows whose
  `available_at` is in the past. No exceptions for user uploads.
- Secrets (API keys) live in a server-side secrets file or the environment.
  They never appear in the database, `events.jsonl`, logs, API responses, or
  any model prompt.
- Data found online is never downloaded or used until the owner approves that
  specific source in the interface.
- This product backtests. It never places orders.

## How an idea flows

```
 paper PDF ──> Extractor ─┐
                          ├─> StrategySpec ─> Data needs check ─> 3 Workers
 English ───> Intake chat ┘                    (fetch / ask / stop)     │
                                                                         v
        Leaderboard + tearsheet <─ Critic <─ Strategy evals <─ bug-only self-heal
```

Everything after `StrategySpec` is the same path for both front doors.

## Configuration

- Python 3.11+, runs on a laptop, single user, no auth.
- Model per role, each as `provider:model-id`, read from the environment:
  `EXTRACTOR_MODEL`, `INTAKE_MODEL`, `WORKER_MODEL`, `CRITIC_MODEL`,
  `FINDER_MODEL`. Supported providers: `anthropic`, `openai`. Keys:
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. One thin wrapper, `factory/llm.py`,
  is the only place SDKs are imported. Never hardcode a model id.
- Alpaca keys: `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`, free plan.
- Never commit keys, `data/`, or PDFs.

## Scope

In:
- Two-tier Parquet market data (done), data catalog, event datasets
- Strategy contract, backtest engine, five strategy evals (done)
- Paper front door: extractor
- English front door: intake chat with follow-up questions
- Data needs check: on disk / fetch / ask for a provider key / upload / stop
- 3 workers, bug-only self-heal, critic
- SQLite records, JSONL events, HTTP API with live event stream
- Web interface

Out:
- Order placement or live trading of any kind
- Auth, multi-user, deployment
- arXiv batch harvester (papers are hand-supplied PDFs)
- HydraDB or any vector/graph store
- Reconciled multi-section wiki (`wiki/graveyard.md` is enough)
- Strategy synthesis (dropped in favour of the English front door)

## Order of work

One session at a time, in this folder, in this order. Finish and commit each
before starting the next.

| # | Work order | What it delivers |
|---|------------|------------------|
| 1 | WO-05, WO-06, WO-07 | One paper through the whole pipeline |
| 2 | WO-09 | HTTP API over the results |
| 3 | WO-08 | Web interface, built directly on the live API |
| 4 | WO-15 | 3–5 papers on the leaderboard |
| 5 | WO-10 | Describe a strategy in English |
| 6 | WO-16 | Rules screen: bounded, explained eval thresholds |
| 7 | WO-11, WO-12, WO-13, WO-14 | Data needs: fetch, upload, providers, finder |

Rows 1–4 are the demo. Rows 5–7 are extras in priority order; start one only
when everything above it is merged. Unfinished work stays on its branch.

## Repo layout

```
data/            # parquet, gitignored
  1min/ 1day/    # price tiers (done)
  events/        # non-price datasets, each with available_at
  catalog.json   # what is on disk
papers/          # PDFs + extracted spec JSON
strategies/      # generated: {source_id}/{variant}.py
runs/            # factory.db (SQLite), events.jsonl, secrets.env
wiki/graveyard.md
factory/
  data.py ingest_alpaca.py audit_data.py     # done
  contract.py engine.py sandbox.py           # done
  evals/                                     # done; do not edit config.py
  llm.py           # provider wrapper
  agents/          # extractor.py worker.py critic.py
  orchestrator.py
  intake.py        # English front door
  data_needs.py    # catalog + resolver
  providers/       # base.py alpaca.py databento.py
  api/             # FastAPI app
web/               # interface, talks to /api only
tests/
work-orders/       # one .md per work order
```

## Data

The canonical data contract is `factory/data_contract/contract.yaml`. Its generated
reference is [docs/DATA.md](docs/DATA.md); use it for fields, units, timestamp
meaning, session offsets, fill provenance and dataset validation rules.

Built and audited; see `work-orders/WO-01.md`. Summary of what exists:

- **Intraday tier** — 1-minute SIP bars, split/dividend adjusted, 3 years,
  regular hours, 50 symbols:
  - ETFs: SPY QQQ IWM DIA TLT GLD XLF XLE XLK XLV XLY XLP XLI XLU
  - Pairs: KO PEP, XOM CVX, NVDA AMD, JPM BAC, V MA, HD LOW, GS MS, UPS FDX,
    WMT TGT, MRK PFE
  - Singles: AAPL MSFT AMZN GOOGL META TSLA NFLX AVGO COST UNH JNJ PG DIS
    CSCO INTC BA
- **Daily tier** — 1-day bars, 2016 to present, current S&P 500 constituents
  (`data/sp500.csv`) plus `DAILY_ETFS` (SPY QQQ TLT GLD).
- UTC timestamps; one file per symbol per tier.
- **Splits, chronological, per tier:** IS = first 60%, OOS = next 20%,
  HOLDOUT = last 20%. HOLDOUT is reserved and currently unused; nothing reads it.
- **Known limitation, shown on every daily-tier tearsheet:** the universe is
  today's index membership, so results carry survivorship bias.

New symbols fetched later (WO-11) follow the same hygiene and the same splits.

## Strategy contract

Strategy data inputs and session-time semantics are defined in the generated
[docs/DATA.md](docs/DATA.md). Do not maintain separate data-contract prompt text.

Additional statuses: `INACTIVE` is a bug-class IS activity failure, eligible only
for bounded self-heal; `VOID` invalidates an earlier run and excludes it from
leaderboards and trial selection while preserving the original evidence.

Every generated strategy is one Python file exposing:

```python
FREQUENCY = "1min"            # or "1day"
UNIVERSE  = ["SPY", "QQQ"]
PARAMS    = {"lookback": 30, "entry_z": 2.0}   # every tunable number lives here

def generate_signals(bars: dict[str, pd.DataFrame], params: dict) -> pd.DataFrame:
    ...
```

- `bars[sym]` has columns open, high, low, close, volume, UTC DatetimeIndex.
- Returns target weights: index = bar timestamps, columns = symbols, each
  weight in [-1, 1], row gross exposure `sum(|w|) <= 1`.
- Weights at bar t may use data up to and including bar t. The engine applies
  the execution lag; strategies must not shift themselves forward.
- Deterministic: no randomness without a fixed seed, no network, no file I/O,
  no wall-clock.
- No magic numbers outside `PARAMS`.

WO-12 adds an optional third argument, `extra: dict[str, pd.DataFrame]`, for
event datasets. Strategies that do not declare `EXTRA = [...]` are unaffected.

**Owner-sanctioned WO-12 extension, Nov 14:** implement event inputs now,
ahead of the remaining optional work orders. Event strategies declare
`EXTRA = [dataset_names]` and accept `generate_signals(bars, params, extra=None)`.
Legacy two-argument strategies keep their existing execution path and results.
Event visibility is determined exclusively by `available_at`, never by a
transaction date. Both normal execution and Eval 1 apply the availability gate.
Daily bar labels are midnight session labels, not decision timestamps; event
decisions use the completed session's close. Intraday decisions use bar end.
No change to eval thresholds is authorized by this extension.
An invalidated harness attempt may reuse its exact three retained candidates
only when the spec is identical and no candidate reached a performance eval or
has a recorded eval result. This records explicit reuse provenance, charges no
new generation call, and still performs normal validation and bounded bug repair.
Measured strategies cannot use this recovery path.
Event-only execution preserves typed empty symbol slices for stocks not yet
observed in a partition or Eval 1 prefix; targets must be zero before their first
quote. All declared symbols remain in the universe, and no prices are filled.
Eval 1 retains the same cuts and comparison; only event-input pass-through changes.
Legacy strategies retain their existing nonempty-symbol rule. Event executions
may use an explicit 600-second sandbox budget; the legacy 60-second cap remains.

The owner approved downloading and auditing Kadoa's public Congress archive
(`github.com/kadoa-org/congress-trading-monitor`, `public/data`) in this chat.
Pin and retain source provenance; use it only if eligible House/Senate stock
transactions span at least five years. Report exact date ranges, row counts
and daily-tier ticker overlap before any strategy run. Exclude executive-branch
rows, options, non-stock assets, missing tickers and transactions other than
purchases/sales. Keep both transaction and disclosure dates. Store normalized
events in `data/events/congress_trades.parquet`; `available_at` is the first
XNYS market open strictly after the disclosure date (date-only filings do not
establish same-day availability). Label results `unverified source` and retain
the daily universe's survivorship limitation. Raw source data stays uncommitted.

Freeze these handwritten `test_type = "original"`, `source_kind = "described"`
specifications before inspecting results; use normal A/B/C workers and all five
evals, with no performance-driven revision:

1. All Congress: equal-weight daily-tier stocks with a disclosed purchase in
   the last 60 trading sessions, rebalanced daily; short SPY by the same total.
   Use gross exposure one: +0.5 total long, -0.5 SPY; hold cash if the basket is
   empty. Purchases establish eligibility; sales do not remove it early.
2. Committee Congress, only after the first run completes: the same rules,
   limited to members serving on a relevant committee on the transaction date.
   Use dated rosters only within their documented periods; discard uncovered
   trades. Report roster sources and coverage before use, and qualifying trade
   count/date range before execution. Fewer than 200 qualifying purchases or
   less than three years requires `short sample: not a verdict` on every result
   and excludes VERIFIED eligibility even when all evals pass.

The committee mapping is fixed: Armed Services -> Aerospace & Defense
**industry**; Energy and Natural Resources / Energy and Commerce -> Energy;
Financial Services / Banking -> Financials; HELP / Energy and Commerce's
health jurisdiction -> Health Care; Commerce/Science/Transportation ->
Communication Services and Information Technology. Use GICS from `data/sp500.csv`
(its `GICS Sub-Industry` identifies Aerospace & Defense). Do not broaden mappings
or extend roster periods after seeing outcomes. Snapshot-only evidence establishes
membership on its snapshot date, not an entire congressional term.
Energy and Commerce's parent membership qualifies for both its mapped sectors;
the owner's health annotation does not add a Health-subcommittee requirement.

Report both specs' statuses, evals passed and Sharpe at every configured cost
level beside an explicitly marked buy-and-hold SPY control on the same stored
IS/OOS splits. Controls never enter Eval 5's trial cohort. A rigged strategy
using transaction dates must be unable to observe a disclosure early. Regression
checks must establish that strategies without EXTRA retain identical results.

## Backtest engine and strategy evals

Implemented; `factory/engine.py` and `factory/evals/` are the reference.
Thresholds are in `factory/evals/config.py`.

| # | Eval | Data | Pass rule |
|---|------|------|-----------|
| 1 | Lookahead | IS | At 5 cut points, weights from the truncated run equal the full run's weights up to the cut (max abs diff <= 1e-9). |
| 2 | Friction | IS | Net Sharpe at 5 bps round trip >= 0.5. Reports break-even bps. |
| 3 | Sensitivity | IS, 5 bps | Worst Sharpe under ±10% / ±20% parameter jitter >= 50% of base. |
| 4 | Decay | IS vs OOS, 5 bps | IS Sharpe > 0, OOS Sharpe > 0 and >= 50% of IS; both periods have positive total PnL and no 5-day window holds > 60% of PnL. |
| 5 | Deflated Sharpe | OOS, 5 bps | Bailey & López de Prado DSR >= 0.95; N and trial variance use every non-void, non-control variant that reached Eval 2 across all runs, with the unchanged configured minimum N. |

**Owner-sanctioned correction, Nov 14:** revision
`2026-11-14-eval45-global-v2` authorizes the Eval 4 positivity guards and Eval 5
global trial accounting. No value in `factory/evals/config.py` may change.
Concentration PnL is the existing sum of daily net returns. When a period's
total is zero, negative or unknown, its concentration share is not applicable
(null) and the check fails. A positive-total share can legitimately exceed one
when other windows lose money; retain it and fail against the unchanged cap.

Each trial is a distinct stored variant identity, including repeat runs and
failed variants that reached Eval 2. Exclude explicit `is_control` variants or
runs and voided evidence; pre-Eval-2 bugs and inactivity are not trials.
Persist `reached_eval_2` before entering Eval 2, so later execution failures
cannot disappear from N. Missing/conflicting Sharpes count toward N and fail
Eval 5 closed; do not estimate variance from a smaller complete-case subset.
Variance uses the same population's per-day OOS base-cost Sharpes (sample
variance, ddof=1). Store the exact cohort IDs and raw count; the configured
minimum trial-count floor is unchanged. A judgment records the global cohort
available at that time.

`python -m factory.rejudge --apply` re-judges retained Eval 4/5 sufficient
statistics without strategy execution, backtests or model calls. It backs up
the database/mirror, rejects conflicting snapshots or concurrent runs, updates
typed eval/variant/run projections atomically and appends revision events.
Void status and its original-result evidence stay preserved; missing evals are
not invented. The report includes every stored variant's before/after verdict.
Stop the local API before applying so its submission lock protects the revision.

Status values: `VERIFIED` (all five), `FAILED_EVAL_n` (first failing eval;
later evals are still run and recorded), `BUG_UNRESOLVED` (self-heal
exhausted), `BLOCKED_DATA` (a data need could not be met).

Every result also carries `evals_passed` (0–5). Show it everywhere a status is
shown, so near-misses are visible without touching a threshold.

### Owner-requested gross diagnostics (November 14)

Every variant additionally retains a separate `gross_diagnostics` object:
`schema_version`, `state` (complete, unavailable, pending), `cost_bps` (0),
`eval_3` and `eval_4` (nullable existing EvalResult shapes), `label` (nullable),
and `reason` (nullable). Compute sensitivity and decay with the same parameters,
splits, jitters, thresholds and pass rules, substituting zero trading cost only.
Reuse captured strategy targets during normal evaluation; do not execute a new
model call. Diagnostics never enter the five authoritative eval records, status,
evals_passed, critic verdict, trial selection or VERIFIED eligibility.

For a failed variant, the deterministic label is `signal before costs` only
when both gross diagnostics pass; otherwise it is `no signal before costs`.
When valid signals or required data are unavailable, retain null results and an
explicit reason beside the label; absence of measurements is not evidence of
economic failure. Active runs remain pending. Show the label and gross numbers
on the leaderboard and tearsheet, clearly marked diagnostic, never success-styled
unless the authoritative status is VERIFIED. Historical diagnostics may execute
retained code without model calls, self-heal, spec changes or verdict updates.
Backfill defers new record-field writes while the arena is active. For a process
that loaded an older strict record schema, guard its PID until exit as well;
terminal status alone does not establish that its final database reads are done.

Both LeaderboardRow and VariantDetail add nullable `gross_diagnostics` with this
shape. Old records without it remain readable. Zero bps means no trading-cost
deduction; it does not imply free computation or realistic executable returns.

## Agents

- **Extractor** — PDF text (pymupdf) -> `StrategySpec`. Fills claimed metrics,
  `ambiguities`, and `test_type`: `replication` if our data matches the paper's
  asset and frequency, else `transfer`.
- **Intake** — chat that turns an English description into a `StrategySpec`
  with `test_type = "original"`. See WO-10.
- **Worker** x3 per idea, in parallel; each sees the spec, the contract, and
  the IS data schema only:
  - A — literal: the rules and parameters as stated
  - B — conservative: same signal, inverse-volatility sizing, turnover damping
  - C — regime-filtered: same signal plus one volatility or trend filter
- **Self-heal** — on a bug-class failure, send the worker its code plus the
  exact error (stack trace, or the lookahead timestamp and symbol). Max 3.
- **Critic** — factual post-mortem text comes from deterministic record templates.
  The configured model selects qualitative review topics from a fixed list;
  code renders their fixed question text, with no model-authored status, metric
  or verdict. The narrative is appended to `wiki/graveyard.md`; historical free
  prose remains separately labelled as unverified model narrative.
- **Finder** — proposes public data sources for unmet data needs. See WO-14.

Generated code runs only through `factory/sandbox.py`. That is crash
isolation, not a security boundary; the README says so.

## Records and events

- SQLite `runs/factory.db`: `sources` (papers and described ideas), `runs`,
  `variants`, `eval_results`, `heal_attempts`, `critiques`, `data_needs`.
- `runs/events.jsonl`: one line per state change. Every event has this shape:

```json
{"seq": 17, "ts": "2026-11-14T06:20:03Z", "run_id": "r_ab12",
 "stage": "eval", "variant": "B", "status": "failed",
 "message": "Eval 2 failed: Sharpe 0.21 at 5 bps",
 "data": {"eval": 2, "sharpe": 0.21, "break_even_bps": 1.4}}
```

`stage` is one of `intake extract data worker heal eval critic done`.
`status` is one of `started passed failed info`. `variant` is `A`, `B`, `C`
or null.

## API contract

FastAPI, JSON, served under `/api`. These shapes are fixed: the backend
serves them and the interface consumes them. Change a shape only by editing
this section first.

| Method and path | Purpose | Returns |
|-----------------|---------|---------|
| `POST /api/runs` | Start a run. Multipart `pdf`, or JSON `{"spec_id": "..."}` | `{"run_id"}` |
| `GET /api/runs/{run_id}/events` | Server-sent events, one event object per message, replays from `seq=0` | stream |
| `GET /api/runs/{run_id}` | Run summary | `{"run_id","source","status","variants":[LeaderboardRow],"data_needs":[DataNeed]}` |
| `GET /api/leaderboard` | All variants | `{"rows":[LeaderboardRow]}` |
| `GET /api/variants/{variant_id}` | Tearsheet | `VariantDetail` |
| `GET /api/graveyard` | Structured post-mortems and compatible rendered evidence | `{"markdown", "entries":[GraveyardEntry]}` |
| `POST /api/intake` | One chat turn. `{"session_id"?, "message"}` | `IntakeReply` |
| `GET /api/data/catalog` | Datasets on disk | `{"datasets":[Dataset]}` |
| `POST /api/data/upload` | CSV of dated events, multipart, plus column mapping | `Dataset` |
| `GET /api/providers` | Provider status | `{"providers":[{"name","connected","covers":[kind]}]}` |
| `POST /api/providers/{name}/key` | Save a key server-side | `{"connected": true}` |
| `POST /api/data/candidates/{id}/approve` | Approve a found source | `Dataset` |
| `GET /api/evals/schema` | Every eval as data, with bounds and tooltips | `EvalSchema` |
| `GET /api/evals/profiles/{name}` | One profile's thresholds | `EvalProfile` |
| `PUT /api/evals/profiles/{name}` | Save a custom profile; rejected outside bounds | `EvalProfile` |

```
LeaderboardRow = {
  "variant_id", "run_id", "source_id", "source_title",
  "source_kind": "paper" | "described",
  "variant": "A" | "B" | "C",
  "test_type": "replication" | "transfer" | "original",
  "frequency": "1min" | "1day",
  "claimed_sharpe": number | null,
  "verified_sharpe": number | null,      # OOS, net of 5 bps
  "break_even_bps": number | null,
  "evals_passed": 0..5,
  "status": "VERIFIED" | "FAILED_EVAL_n" | "BUG_UNRESOLVED" | "BLOCKED_DATA" | "RUNNING" | "INACTIVE" | "VOID",
  "profile": string,                     # "default" until WO-16
  "default_status": string,              # verdict under the default profile
  "default_evals_passed": 0..5,
  "gross_diagnostics": GrossDiagnostics | null  # separate 0-bps observations, as defined above
}

VariantDetail = LeaderboardRow + {
  "code": string, "params": object,
  "evals": [{"n", "name", "passed", "metrics": object}],
  "equity": {"dates": [date], "gross": [number], "net": [number],
             "is_end": date, "oos_end": date},
  "heal_attempts": [{"attempt", "error", "fixed": bool}],
  "critique": string,
  "notes": [string]          # e.g. survivorship bias, unverified source
}

DataNeed = {
  "id", "kind": "price_bars" | "events", "name": string,
  "symbols": [string], "frequency": string | null,
  "start": date_or_UTC_timestamp | null, "end": date_or_UTC_timestamp | null,
  "status": "on_disk" | "fetching" | "fetched" | "needs_provider"
            | "needs_upload" | "candidates" | "unavailable",
  "provider": string | null,
  "candidates": [{"id", "title", "url", "licence": string | null,
                  "coverage": string, "availability_column": string}]
}

IntakeReply = {
  "session_id", "reply": string, "questions": [string],
  "spec": StrategySpec | null,        # non-null when ready to run
  "spec_id": string | null,
  "data_needs": [DataNeed]
}

Dataset = {"name", "kind", "symbols": [string], "frequency": string | null,
           "start": date, "end": date, "rows": int,
           "source": string, "verified": bool}

EvalSchema = {"evals": [{
  "n": 1..5, "name": string,
  "question": string,                    # plain English, e.g. "Does it still
                                         # make money after trading costs?"
  "settings": [Knob],                    # changing one needs a re-run
  "checks":   [Knob + {"metric": string, "op": ">=" | "<=" | ">",
                       "relative_to": string | null}]
}]}

Knob = {"key": string, "label": string, "default": number,
        "min": number, "max": number, "locked": bool,
        "tooltip": {"what_it_is": string, "if_raised": string,
                    "if_lowered": string}}

EvalProfile = {"name": string, "editable": bool,
               "values": {key: number}, "stale": bool}
```

### WO-09 implementation extensions (November 14)

The following additions are part of the API contract before implementation.
Persisted records use `factory/record_models.py`, schema version 1.0.0;
[docs/RECORDS.md](docs/RECORDS.md) records the completed migration. API projections
must validate their response shapes too. All reads exclude voided runs and
their children by default, including direct lookups, events and artifacts.
`include_voided=true` is an explicit audit opt-in; a hidden or absent identifier
returns 404. Filters/sorts use the store's indexed projections where applicable.
Unknown historical information stays null or absent; never fabricate a date,
metric, source association or completed step.

| Method and path | Purpose | Returns |
|---|---|---|
| `GET /api/health` | Local service and implemented capabilities | `{"status":"ok", "schema_version", "capabilities":{name:bool}}` |
| `GET /api/runs` | Run history; optional source_id/status filters and audit opt-in | `{"runs":[RunSummary]}` |
| `GET /api/sources` | Retained sources | `{"sources":[Source]}` |
| `GET /api/sources/{source_id}` | Current source and registered source artifacts | `{"source":Source, "artifacts":[Artifact]}` |
| `GET /api/runs/{run_id}/events/history` | Finite replay with after_seq and bounded limit | `{"events":[Event], "next_seq":int}` |
| `GET /api/runs/{run_id}/artifacts` | Related retained evidence | `{"artifacts":[Artifact]}` |
| `GET /api/artifacts` | Allowlisted evidence inventory; optional run_id | `{"artifacts":[Artifact]}` |
| `GET /api/artifacts/{artifact_id}` | Safe text/JSON preview or metadata for binary evidence | `ArtifactView` |
| `GET /api/artifacts/{artifact_id}/download` | Sanitized attachment, where descriptor permits | bytes with safe content type and attachment disposition |
| `GET /api/data/datasets/{dataset_id}` | Manifest, ingest metadata, splits and contract fields | `DatasetDetail` |
| `GET /api/data/datasets/{dataset_id}/preview` | Bounded downsampled IS/OOS rows and gap intervals | `DatasetPreview` |
| `GET /api/data/ingest-events` | Original ingest event schema; scope main/smoke, offset/limit | `{"events":[object], "total":int, "next_offset":int|null}` |
| `GET /api/data/audits` | Historical audit and related evidence | `{"audit":object|null, "artifacts":[Artifact]}` |
| `GET /api/data/contract` | Canonical data ontology and generated reference | `{"schema_version", "contract":object, "markdown":string}` |
| `GET /api/data/universe` | Current membership snapshot and source provenance | `{"symbols":[string], "provenance":object, "notes":[string]}` |
| `GET /api/records/schema` | Generated JSON schemas of all eight persisted record kinds | `{"schema_version", "models":{kind:object}}` |

Existing `/api/runs/{run_id}` returns RunDetail below. Leaderboard accepts
source_id, status, test_type and frequency filters, an allowlisted sort and
direction, plus include_voided. It returns rows only; headline counts derive
from those rows. Source records contain the current extraction, while RunDetail
retains the exact historical spec snapshot. All default-profile rows expose
`profile="default"`, `default_status` and `default_evals_passed` without rejudging.

Live progress exposes each eval independently. The owner's November 14 correction
requires exact Eval 1–4 results to be persisted and streamed as each finishes;
only Eval 5 waits for the shared trial cohort. Observational callbacks in the
harness are authorized for this purpose; they must not change executions,
thresholds or pass rules. Already-running processes must not be interrupted.
The Run screen shows five clickable result rows per variant, actual metrics,
the specific active check when reported, and an explicit dependency for Eval 5.
An elapsed timer requires a real per-eval start event; a generic harness start
does not establish which individual eval is active.

For an older active process that has not published individual results, the API
may recover display evidence from saved metrics without writes or strategy
execution: a recorded entry into Eval 2 establishes successful lookahead;
the saved cost grid establishes friction; a nonpositive base Sharpe establishes
sensitivity failure; complete daily equity with validated IS/OOS boundaries and
matching saved Sharpes supports decay reconstruction. Label this provenance in
each step and never invent missing cuts or jitter measurements. Original eval
records always take precedence. Recovery never changes persisted verdicts or
trial accounting. Active API pass counts reflect available results; final stored
counts replace them when published. Unknown individual outcomes stay explicitly
unpublished, rather than implying every check is running or hiding known failures.

```
RunSummary = {
  "run_id", "status", "source": Source|null,
  "variants":[LeaderboardRow], "data_needs":[DataNeed],
  "created_at": UTC|null, "started_at": UTC|null,
  "wall_seconds": number|null, "estimated_model_cost_usd": number|null,
  "cost_complete": bool|null, "voided": bool,
  "void_reason": string|null, "error_type": string|null, "error": string|null
}
RunDetail = RunSummary + {
  "variants":[VariantRun], "steps":[Step], "usage":[Usage],
  "extraction_diagnostics":[Diagnostic], "artifacts":[Artifact]
}
RunDetail += {"submission": {"origin":"api", "upload_name":string,
  "upload_sha256":string, "input_path":relative_path, "accepted_at":UTC}|null}
LeaderboardRow += {
  "summary": string, "days_traded": int|null, "notes":[string],
  "voided":bool, "void_reason":string|null, "created_at":UTC|null
}
VariantRun = LeaderboardRow + {"steps":[Step]}
Step = {
  "id":string, "kind":"extract"|"data"|"code"|"heal"|"eval"|"critic",
  "label":string,
  "state":"pending"|"running"|"pass"|"failed"|"recorded"|"fixed"|"not_run"
          |"awaiting_results"|"awaiting_judgment",
  "number":int|null, "attempts":int, "max_attempts":int|null,
  "details":[string], "logs":[Event]
}
VariantDetail += {
  "summary":string, "steps":[Step], "activity":object|null,
  "days_traded":int|null, "equity_boundaries":object|null,
  "source":Source|null, "artifacts":[Artifact], "original_result":object|null,
  "voided":bool, "void_reason":string|null
}
GraveyardEntry = {
  "variant_id", "run_id", "source_title", "variant", "status", "test_type",
  "frequency", "evals_passed", "summary", "cause":string,
  "critique":string|null, "notes":[string], "voided":bool,
  "void_reason":string|null, "original_result":object|null
}
Dataset += {
  "id", "scope":"main"|"smoke", "schema_version", "feed", "adjustment",
  "fill_rate":number, "expected_rows":int|null, "missing_rows":int|null,
  "notes":[string]
}
DatasetDetail = {"dataset":Dataset, "manifest":object, "metadata":object,
                 "splits":object, "fields":object, "artifacts":[Artifact]}
DatasetPreview = {
  "dataset_id", "rows":[object], "splits":object, "coverage":object,
  "gaps":[{"start":UTC,"end":UTC,"rows":int}],
  "total_gaps":int, "holdout_sealed":true, "downsampled":bool
}
Artifact = {
  "id", "name", "kind", "media_type", "size_bytes":int,
  "run_ids":[string], "source_id":string|null, "dataset_id":string|null,
  "historical":bool, "audit_only":bool, "downloadable":bool, "notes":[string]
}
ArtifactView = {"artifact":Artifact, "content":string|null,
                "offset":int, "next_offset":int|null}
```

Variant code, params, equity and critique are nullable when never produced;
missing charts must not become empty invented curves. Heal detail includes the
recorded `result_error` when present. Creation time is distinct from started_at:
the latter may use the earliest recorded run event when legacy creation time is
unknown. A fixed repair step labels the successful attempt as `fixed n/3`.
Terminated runs mark unexecuted steps `not_run`, not permanently pending.
Persisted eval results establish authoritative pass/fail. The labelled live
recovery described above exposes deterministically recoverable outcomes without
changing those records. Preliminary IS bug-check events alone do not establish
lookahead passage; the recorded entry into performance Eval 2 does.
Tearsheet eval views label recovered metrics with
`evidence_source="recovered_from_saved_evidence"` and a plain-English `reason`.

Summaries, status/metric/verdict detail lines and structured graveyard causes
are deterministic templates over stored facts. No model call writes or edits
these fields. Historical critic text is labelled unverified model narrative and
kept separate from authoritative results. New critic requests must not generate
status, metric or verdict claims; factual postmortem sections are deterministic.

PDF POST accepts a text-based PDF up to 30 MB, reserves a durable run_id, then
executes the real existing pipeline in the background. Invalid input returns
422/413, a concurrent local submission returns 409, and a background failure is
recorded as FAILED with a terminal event. SSE supplies global `id: seq` and one
typed Event JSON per `data:` message, supports `after_seq` and Last-Event-ID,
replays from zero, sends keepalive comments while active and closes after the
terminal event and the remaining recorded event tail. Reopening a run reloads durable state.
Restart recovery marks abandoned locally owned runs failed; it never pretends they
are still executing. An API-owned terminal run missing its final event receives an
explicit recovery event derived only from its stored state. A historical terminal
run with no retained final event closes SSE after a short idle grace period with
an explanatory comment; it does not receive an invented original event.

Catalog is built from actual manifests/metadata, since catalog.json does not
yet exist. Main datasets are the default; smoke is an explicit separate scope.
Previews accept `split=visible` (default, IS plus OOS), `IS` or `OOS` and
`limit=1..2000` (default 500). They show split boundaries and sealed HOLDOUT coverage;
no raw HOLDOUT observations or full Parquet downloads are exposed. Audits show
their historical timestamp and fill-rate denominator. Artifact IDs resolve
only through an allowlisted inventory; reject traversal/symlink escape, redact
credentials on reads/exports, and never serve arbitrary HTML or database bytes
as active content. Original PDFs are attachments, treated only as source text.

The eval schema reads actual constants in factory/evals/config.py; all current
settings/checks are read-only and locked. No invented capacity eval or fixture
counts. EvalSchema also returns `readonly=true`, `constants` (numeric scalar or
numeric-array values from config.py), and `notes`. Each eval additionally has
`data_scope`, `notes`, `source_file` and read-only `source_code` from its existing
implementation; these explain fixed mathematical guards as well as thresholds.
For checks, null `relative_to` means `metric op default`; a named relative metric
means `metric op (default * relative_to)`. Eval 4 compares OOS Sharpe against a
multiple of IS Sharpe and independently requires both Sharpes to be positive.
An OOS/IS ratio with nonpositive IS is not applicable. Eval 5's displayed rules
state the global, non-void, non-control cohort and the unchanged trial-count floor.
Only the default profile is readable. English intake, saved-spec start,
provider-key writes, source approval and custom profiles are not
implemented in this work: their controls stay disabled with "not available yet"
and their write endpoints return 501 with that detail. Provider presence may be
reported from configured environment-variable presence only, without a key or
an invented connectivity test. The interface does not change settings or eval logic;
the owner-sanctioned correction above is a separately audited backend revision.
WO-12 activates event upload under the explicit extension below.

## Interface

### WO-12 API extension (November 14)

`POST /api/data/upload` becomes available for event CSV files. Multipart fields:
`file` (UTF-8 CSV, maximum 10 MiB), `name` (letters/digits/underscores, starting
with a letter), and `mapping` (JSON object mapping canonical destination names
to source column names, including `available_at` and `symbol`). Availability
values must have explicit time zones; date-only inputs are rejected because
they do not identify when the event became usable. Scalar free fields are
preserved; invalid, empty or colliding mappings are rejected. Existing dataset
names cannot be overwritten. Missing/invalid data returns 422; oversized files
return 413; duplicate names return 409. Success returns the existing `Dataset`
shape with kind events, frequency null, verified false and `unverified source`
in notes. The catalog and dataset detail/preview routes include events, with
bounded previews and price-tier HOLDOUT cutoffs honored for strategy access.
No source downloader or remote fetch is implied by CSV upload.

Short-sample eligibility is distinct from deterministic eval outcomes:
`INSUFFICIENT_SAMPLE` is an additional variant status when all evals pass but
the fixed committee sample gate prohibits VERIFIED. Existing failed/bug statuses
remain, always accompanied by the short-sample note. Variant records additionally
retain `verification_eligible` and `eligibility_reason`; no eval is rewritten.
Variant detail also returns nullable `cost_sharpes`, keyed by IS/OOS and round-trip
bps, computed from the exact captured targets without new strategy executions.
It returns `verification_eligible` and nullable `eligibility_reason` explicitly.

The owner also approved the seven official House/Senate roster snapshots in chat.
`report/wo12-committee-audit.md` records URLs, document dates and limitations.
No continuous membership intervals or historical publication timestamps are
inferred from those snapshots. Current audit yields zero qualifying purchases;
the committee experiment still runs, with the fixed short-sample exclusion.

Lives in `web/`. If the owner's mock-up specifies a stack or layout, the
mock-up wins. Otherwise use React + Vite + TypeScript. It talks to the API
only, through one data-access module. Keep presentation separate from data
and state, so applying the mock-up later is a restyle and not a rebuild.

Screens:

1. **New run** — two entry points side by side: upload a paper, or describe a
   strategy in a chat box (follow-up questions appear inline).
2. **Run** — the live assembly line. Stages left to right, three variant lanes,
   each eval lighting up pass/fail as events arrive, self-heal attempts shown
   in place with the error that triggered them. Data needs appear as a card
   with one action each: fetching, connect a provider, upload, approve a
   source, or blocked.
3. **Leaderboard** — sortable; claimed Sharpe next to verified Sharpe,
   break-even bps, evals passed n/5, status.
4. **Tearsheet** — equity curve gross vs net with the IS/OOS boundary marked,
   eval table with metrics, code, heal history, critique, notes.
5. **Data** — catalog, provider connections, uploads.
6. **Graveyard** — rendered post-mortems.
7. **Rules** (WO-16) — every eval with its question, checks and thresholds.
   Sliders limited to each knob's bounds; locked knobs shown but disabled;
   the three-line tooltip on hover.

UX rules:
- Failure is the main content, not an error state. A failed strategy gets as
  much design attention as a verified one.
- `test_type` and `evals_passed` are visible wherever a result is.
- Nothing is coloured or labelled as good unless its status is `VERIFIED`.
- Notes such as survivorship bias and "unverified source" are always shown,
  never behind a click.
- Key fields are write-only: once saved, the interface shows "connected",
  never the value.
- When a custom eval profile is active, every result shows which profile
  judged it and its default verdict next to the custom one.

## Work orders

Do them in the order given in "Order of work". Commit after each. If
acceptance still fails after two honest attempts, stop and report; do not
loosen the criteria. Each work order also gets a file in `work-orders/` with
four headings: Summary, Acceptance Criteria, Out of Scope, Linked Spec
Section. Regenerate `WO-08.md` onward from this file; older versions of
WO-08 and WO-09 are superseded.

**WO-01 to WO-04 — done.**

**WO-05 Extractor and LLM wrapper.** `factory/llm.py`, `agents/extractor.py`.
Accept: a valid `StrategySpec` for two papers in `papers/`, each with
`ambiguities` and a `test_type`; switching `EXTRACTOR_MODEL` between providers
needs no code change.

**WO-06 Workers and self-heal.**
Accept: three variants generated in parallel for one paper; a deliberately
injected lookahead bug is caught by Eval 1 and fixed within 3 attempts, with
every attempt in `heal_attempts` and `events.jsonl`.

**WO-07 Orchestrator, critic, records.**
`python -m factory.orchestrator papers/<file>.pdf` still works as a debug
entry point.
Accept: one real paper end to end; all tables written; events match the event
shape above; critique appended to the graveyard. Report wall-clock time and
model cost for the run. **Checkpoint: before sleeping Friday. Record a backup
screen capture of this run as soon as it works.**

**WO-09 API.** `factory/api/` serving the runs, events, leaderboard, variants
and graveyard rows of the API contract.
Accept: each endpoint returns the documented shape, checked by tests; the
event stream replays a finished run and follows a live one.

**WO-08 Interface.** Screens 1–6 in `web/`, built directly on the live API.
Use the owner's mock-up if it exists; otherwise build plain, working pages
with minimal default styling and do not invent a visual design. Screens whose
backend is not built yet (intake chat, data needs, providers) show a clear
"not available yet" state and light up as later work orders land.
Accept: uploading a paper in the interface starts a real run and the Run
screen follows it live to completion; leaderboard and tearsheets show real
records. **Checkpoint: noon Saturday.**

**WO-15 Batch.** Run 3–5 papers from "Candidate papers" through the interface.
Accept: every variant appears on the leaderboard with a tearsheet and a
graveyard entry; total time and model cost are recorded in the work order.

**WO-10 Describe a strategy.** `factory/intake.py`, `POST /api/intake`.
`StrategySpec` gains `test_type = "original"`, `source_kind`, and allows empty
`ambiguities` once follow-ups are answered. The agent asks at most 3
follow-up questions, drawn from the ambiguities, then produces the spec.
Claimed metrics are empty. It never invents a proxy for data it lacks.
Accept: "buy SPY when it opens down more than 1% versus the prior close, sell
at the close" yields a spec after follow-ups and runs end to end.

**WO-16 Eval profiles and Rules screen.** `factory/evals/schema.py` describes
each eval as data in the `EvalSchema` shape. Tooltips are plain English with
no jargon. The built-in `default` profile mirrors `config.py` and cannot be
edited. A custom profile may move a knob only within `[min, max]`; locked
knobs cannot move. Bounds:

| Knob | Default | Min | Max |
|------|---------|-----|-----|
| Lookahead tolerance | 1e-9 | locked | locked |
| Minimum net Sharpe (Eval 2) | 0.5 | 0.3 | 1.5 |
| Trading cost assumed, bps round trip (setting) | 5 | 1 | 20 |
| Parameter robustness ratio (Eval 3) | 0.5 | 0.3 | 0.8 |
| OOS / IS Sharpe ratio (Eval 4) | 0.5 | 0.3 | 0.9 |
| OOS Sharpe above zero (Eval 4) | on | locked | locked |
| Largest 5-day share of PnL (Eval 4) | 0.60 | 0.30 | 0.75 |
| Minimum deflated Sharpe (Eval 5) | 0.95 | 0.90 | 0.99 |

Threshold changes re-judge stored metrics without re-running backtests. A
change to a setting marks the profile `stale` until affected variants are
re-run. Every result records the profile that judged it, and the API returns
the default verdict alongside. Add the three `/api/evals` endpoints and the
Rules screen. This is a sanctioned change to `factory/evals/`, in addition to
the Nov 14 owner-authorized Eval 4/5 correction above; default values still may
not be altered.
Accept: a PUT outside bounds or on a locked knob is rejected; lowering minimum
net Sharpe to 0.45 flips the clean fixture's Eval 2 verdict under the custom
profile while its default verdict stays FAIL; the Rules screen shows all five
evals with working sliders and tooltips.

**WO-11 Data needs check.** `factory/data_needs.py`. `StrategySpec` gains
`data_requirements`. `data/catalog.json` lists every dataset on disk. The
resolver gives each requirement a `DataNeed.status`. Price-bar gaps that
Alpaca covers are fetched with the existing ingest code, then the run
continues. Anything else pauses the run with the need shown; if it cannot be
met the run ends `BLOCKED_DATA`. Every resolution is an event with
`stage = "data"`.
Accept: a described strategy on a ticker outside the 50 triggers a fetch and
then runs end to end; a strategy needing non-price data pauses with the
missing dataset named.

**WO-12 Event data.** `data/events/{name}.parquet` with required columns
`available_at` (UTC) and `symbol`, plus free fields. The contract gains
`EXTRA = [names]` and the `extra` argument. The engine and Eval 1 truncate
every extra dataset on `available_at` at the same cut as the bars.
`POST /api/data/upload` maps CSV columns and rejects a file with no
availability date. Uploaded data is parsed as data only, size-capped, never
executed.
Accept: a strategy using an uploaded event file runs end to end; a rigged
variant that reads rows dated after the current bar fails Eval 1.

**WO-13 Providers.** `providers/base.py` with `covers(need)` and
`fetch(need)`. Alpaca first; add Databento for price bars (its bars are
unadjusted, so mark such data in `notes` unless adjustment factors are
applied). `POST /api/providers/{name}/key` writes to `runs/secrets.env`,
gitignored, mode 600.
Accept: with no Databento key a need shows `needs_provider`; after adding the
key the same need fetches and the run continues. A test greps the database,
`events.jsonl`, logs and captured prompts for the key value and finds nothing.

**WO-14 Open-data finder.** For needs no provider covers, the Finder agent
uses its model provider's web search tool to return up to 3 candidates (URL,
licence if stated, coverage, which column is the availability date). If no
search tool is available it returns none and says so. Nothing is downloaded
before `POST /api/data/candidates/{id}/approve`. Approved data goes through
WO-12's path with `verified = false` and the note "unverified source" on
every tearsheet that used it.
Accept: a congressional-trades strategy yields candidates; approving one
ingests it and the strategy runs with trades keyed on disclosure date, not
trade date.

## Checkpoints

| When | What must be true | If not |
|------|-------------------|--------|
| Fri, before sleep | WO-07: one paper end to end, backup recorded | Nothing else matters until it is |
| Sat 10:00am | WO-09 API serving real data | Skip extras; interface gets all remaining time |
| Sat noon | WO-08: interface live on the API | Demo with whatever screens work plus the debug CLI |
| Sat 1:00pm | Feature freeze | Unmerged branches stay unmerged |
| Sat 1:00–3:30pm | WO-15 batch done, README, demo script, second backup recording | |

## Candidate papers

Owner supplies the PDFs. Claimed numbers are from abstracts; the extractor
must re-read them from the PDF.

| Paper | Tier | Type | Claim |
|-------|------|------|-------|
| Zarattini, Aziz, Barbon — Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY) | intraday | replication | Sharpe 1.33, 2007–early 2024, net of costs |
| Gao, Han, Li, Zhou — Market Intraday Momentum (first half-hour predicts last half-hour) | intraday | replication | Sharpe 1.08 on SPY, 1993–2013 |
| Miao (2014) — High Frequency and Dynamic Pairs Trading (two-stage correlation and cointegration) | intraday | transfer (paper uses 177 oil and gas stocks, 15-min bars) | annual Sharpe 9.25 |
| Avellaneda & Lee (2010) — Statistical Arbitrage in the US Equities Market | daily | replication, later sample | Sharpe 1.44 for PCA strategies, 1997–2007 |
| de Groot, Huij, Zhou — Another Look at Trading Costs and Short-Term Reversal Profits | daily | replication, later sample | 30–50 bps per week net, large caps |

## Demo (what the build must make possible)

1. Upload a paper; the Run screen shows extraction, then three variants.
2. A variant trips Eval 1; the screen names the timestamp; the worker fixes it.
3. The fixed variant dies at Eval 2; break-even cost sits next to the paper's
   claimed Sharpe.
4. Leaderboard: claimed vs verified across all papers.
5. Type a strategy in English; answer a follow-up; watch it get tested.
6. If WO-16 landed: open Rules, hover a threshold to read what it means, move
   a slider within its bounds and watch verdicts change next to the defaults.
7. If WO-11 to WO-14 landed: ask for a strategy that needs data the system
   lacks, and show it fetch, ask for a key, or find and propose a source.
