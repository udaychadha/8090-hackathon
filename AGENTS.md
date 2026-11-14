# AGENTS.md — Financial Models In the Arena

A software factory for quantitative research. A paper goes in; three candidate
strategy implementations come out; a deterministic verification harness decides
which, if any, survive. Built for the 8090 EVOLVE hackathon.

**Hard deadline: code freeze Saturday Nov 14, 3:30pm PT.** Feature freeze 1:00pm.

## The one idea to protect

LLM agents write strategy code. **Only deterministic, non-LLM code judges it.**
The analogy we are demoing: paper = ticket, strategy = pull request, strategy evals = CI,
strategy eval failure fed back to the worker = the factory loop.

Rules that follow from this:

- Never weaken, skip or special-case a strategy eval to get a pass. "0 of 15 verified"
  is a valid and interesting result.
- Workers never see out-of-sample or holdout data. Only the harness touches it.
- Self-healing is allowed for **bugs only** (runtime error, contract violation,
  lookahead leak). A strategy that fails Evals 2–5 is dead. Re-prompting until
  it passes is overfitting to the strategy evals.
- No LLM call may influence a pass/fail decision.

## Assumptions (owner has not confirmed; ask if any blocks you)

- Solo builder, Python 3.11+, runs on a laptop.
- LLM calls go through the Anthropic Python SDK. Model name comes from
  `ANTHROPIC_MODEL`; key from `ANTHROPIC_API_KEY`. Do not hardcode either.
- Alpaca keys in `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`, free plan.
- Never commit keys or `data/`.

## Scope

In:
- Two-tier Parquet market data
- Strategy contract + backtest engine
- Five strategy evals
- Extractor -> 3 workers -> strategy evals -> bug-only self-heal -> critic
- SQLite run records, static HTML leaderboard, JSONL event log

Out (do not build unless every work order below is done):
- arXiv batch harvester (papers are hand-supplied PDFs)
- Next.js dashboard, SSE streaming
- HydraDB or any vector/graph store
- Reconciled multi-section wiki (a single `wiki/graveyard.md` is enough)
- Strategy synthesis (stretch, see WO-09)

## Repo layout

```
data/            # parquet, gitignored
papers/          # PDFs + extracted spec JSON
strategies/      # generated: {paper_id}/{variant}.py
runs/            # factory.db (SQLite), events.jsonl
wiki/graveyard.md
report/          # generated leaderboard.html
factory/
  ingest_alpaca.py
  contract.py    # StrategySpec, loader, contract validation
  engine.py      # backtest: lag, costs, returns, Sharpe
  evals/         # lookahead.py friction.py sensitivity.py decay.py deflated.py
  agents/        # extractor.py worker.py critic.py
  sandbox.py     # subprocess runner with timeout
  orchestrator.py
  report.py
tests/
work-orders/     # one .md per WO below, copied from this file
```

## Data

The canonical data contract is `factory/data_contract/contract.yaml`. Its generated
reference is [docs/DATA.md](docs/DATA.md); use it for fields, units, timestamp
meaning, session offsets, fill provenance and dataset validation rules.

Two tiers. Both: `feed=sip`, `adjustment=all` (Alpaca defaults to raw prices;
without this every split looks like a crash). Free plan cannot query the most
recent 15 minutes, so end the range at yesterday. Page size max is 10,000 data
points across all symbols in a request; follow `next_page_token`. Rate limit
200 requests/min: throttle and retry. Confirm class and enum names against the
installed `alpaca-py` rather than trusting memory.

**Intraday tier** — 1-minute bars, last 3 years, 50 symbols:

- ETFs: SPY QQQ IWM DIA TLT GLD XLF XLE XLK XLV XLY XLP XLI XLU
- Pairs: KO PEP, XOM CVX, NVDA AMD, JPM BAC, V MA, HD LOW, GS MS, UPS FDX,
  WMT TGT, MRK PFE
- Singles: AAPL MSFT AMZN GOOGL META TSLA NFLX AVGO COST UNH JNJ PG DIS CSCO
  INTC BA

**Daily tier** — 1-day bars, 2016 to present, current S&P 500 constituents
(save the list used to `data/sp500.csv`; check Alpaca's symbol format for
share classes such as BRK.B). Plus four ETFs, SPY QQQ TLT GLD
(`DAILY_ETFS`), added 2026-11-13 so the WO-03 fixtures run on this tier.

Hygiene:
- Store timestamps in UTC. Intraday: keep regular hours only, 09:30–16:00
  America/New_York.
- Forward-fill missing intraday bars with volume 0, max 5 consecutive bars,
  never across sessions. Log the fill rate per symbol.
- One file per symbol per tier: `data/1min/{SYM}.parquet`, `data/1day/{SYM}.parquet`.

**Splits, chronological, per tier:** IS = first 60%, OOS = next 20%,
HOLDOUT = last 20%. HOLDOUT is touched only by WO-09.

**Known limitation to print on every daily-tier tearsheet:** the universe is
today's index membership, so results carry survivorship bias.

## Strategy contract

Strategy data inputs and session-time semantics are defined in the generated
[docs/DATA.md](docs/DATA.md). Do not maintain separate data-contract prompt text.

Additional statuses: `INACTIVE` is a bug-class IS activity failure, eligible only
for bounded self-heal; `VOID` invalidates an earlier run and excludes it from
leaderboards and trial selection while preserving the original evidence.

Every generated strategy is one Python file exposing:

```python
FREQUENCY = "1min"            # or "1day"
UNIVERSE  = ["SPY", "QQQ"]    # subset of the tier
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
- No magic numbers outside `PARAMS` (Eval 3 jitters `PARAMS`, nothing else).

`contract.py` validates all of the above before any strategy eval runs. A violation is
a bug and goes to self-heal.

## Backtest engine

- `executed = target.shift(1)` always.
- Bar return per symbol = close-to-close, including the overnight gap.
- `turnover_t = sum(|executed_t - executed_{t-1}|)`.
- Cost at `c` bps round trip: `turnover_t * (c / 2) / 1e4`.
- Aggregate net PnL to **daily** returns, then
  `Sharpe = mean / std * sqrt(252)`. Same formula for both tiers.
- Also report: annualised return, max drawdown, average daily turnover.

## Strategy evals

Proposed thresholds. They are config values in one file (`evals/config.py`);
the owner may change them, agents may not.

| # | Eval | Data | Pass rule |
|---|------|------|-----------|
| 1 | Lookahead | IS | For 5 cut points (30/45/60/75/90% of IS), weights from the truncated run equal the full run's weights up to the cut, max abs diff <= 1e-9 (NaN == NaN). On failure raise `LookaheadBiasError` with the first offending timestamp and symbol. |
| 2 | Friction | IS | Run at 0, 2, 5, 10 bps round trip. Pass if net Sharpe at 5 bps >= 0.5. Report break-even bps (linear interpolation where Sharpe crosses 0.5). |
| 3 | Sensitivity | IS, 5 bps | Jitter each numeric param one at a time by ±10% and ±20% (ints rounded, minimum change 1; at most 4 params). Pass if the worst jittered Sharpe >= 50% of base Sharpe. |
| 4 | Decay | IS vs OOS, 5 bps | Pass if OOS Sharpe > 0 and >= 50% of IS Sharpe, and no 5-consecutive-day window holds more than 60% of total PnL. |
| 5 | Deflated Sharpe | OOS, 5 bps | Bailey & López de Prado (2014) DSR >= 0.95. |

Eval 5 detail (implement from the paper, do not trust this summary blindly):

```
SR0 = sqrt(V) * ((1 - g) * Zinv(1 - 1/N) + g * Zinv(1 - 1/(N*e)))
DSR = Phi( (SR - SR0) * sqrt(T - 1) / sqrt(1 - skew*SR + ((kurt - 1)/4) * SR^2) )
```

`SR` is the per-day (not annualised) Sharpe, `T` the number of daily returns,
`skew`/`kurt` of those returns (kurt non-excess), `g` the Euler–Mascheroni
constant, `V` the variance of per-day Sharpes across trials, `N` the number of
variants that reached Eval 2 in this factory run (jitters do not count,
minimum 3). Sanity test: DSR must fall as N rises.

Status values: `VERIFIED` (all five), `FAILED_EVAL_n` (first failing strategy eval;
still run and record the later strategy evals for the tearsheet), `BUG_UNRESOLVED`
(self-heal exhausted).

## Agents

- **Extractor** — PDF text (pymupdf) -> `StrategySpec` JSON (pydantic):
  paper_id, title, category, hypothesis, universe, frequency, signal rules,
  claimed metrics (Sharpe, sample period, costs assumed), `ambiguities`, and
  `test_type`: `replication` if our data matches the paper's asset and
  frequency, else `transfer`. That label is shown everywhere results are shown.
- **Worker** x3 per paper, run in parallel, each sees the spec, the contract,
  and IS data schema only:
  - A — literal: the paper's rules and parameters as written
  - B — conservative: same signal, inverse-volatility sizing, turnover damping
  - C — regime-filtered: same signal plus one volatility or trend filter
- **Self-heal** — on bug-class failure, send the worker its code plus the exact
  error (stack trace, or the lookahead timestamp/symbol). Max 3 attempts.
- **Critic** — given claimed metrics and strategy eval telemetry, writes a short
  post-mortem: what the paper omitted, where the strategy breaks. Appends one
  entry to `wiki/graveyard.md`. Narrative only; it decides nothing.

Generated code runs through `sandbox.py`: separate subprocess, timeout (60s
per run), working directory limited to a temp dir. This is crash isolation,
not a security boundary; say so in the README.

## Records and output

- SQLite `runs/factory.db`: `papers`, `variants`, `eval_results`
  (one row per variant per strategy eval with metrics JSON), `heal_attempts`, `critiques`.
- `runs/events.jsonl`: one line per state transition (extracted, variant
  written, eval n pass/fail, heal attempt, critique). The CLI prints these
  live; this is the demo's "assembly line" view.
- `report/leaderboard.html`: one static, self-contained file generated from
  SQLite. Columns: paper, variant, test type, claimed Sharpe, verified net
  Sharpe (5 bps, OOS), break-even bps, status. Each row expands to a tearsheet:
  equity curve at 0 vs 5 bps with the IS/OOS line, strategy eval table, critique.

## Work orders

Do them in order. Commit after each. If acceptance still fails after two
honest attempts, stop and report rather than loosening the criteria.

**WO-01 Data.** `ingest_alpaca.py` for both tiers.
Accept: all files present; a script prints rows, date range and fill rate per
symbol; loading the 50-symbol intraday tier into wide frames is timed and
logged; a known split (e.g. NVDA, June 2024) shows no price discontinuity.

**WO-02 Contract and engine.** `contract.py`, `engine.py`, `sandbox.py`.
Accept: unit tests for lag, cost arithmetic on a hand-computed 5-bar example,
daily aggregation, and contract rejection of out-of-range weights.

**WO-03 Evals 1 and 2.** Plus two fixture strategies in `tests/fixtures/`:
`rigged.py` (uses `close.shift(-1)` and flips position every bar) and
`clean.py` (volatility-scaled trend on SPY/QQQ/TLT/GLD, daily tier).
Accept: rigged fails Eval 1 naming a timestamp and symbol; with the leak
removed it fails Eval 2; clean passes Eval 1. Record what clean does on Eval 2
honestly; do not tune it until it passes.

**WO-04 Evals 3, 4, 5.**
Accept: unit tests on synthetic return series with known answers (a constant
positive drift passes Eval 4; a series whose PnL is one spike fails it; DSR
decreases in N). Time one full five-eval pass on an intraday strategy and
report it. **Checkpoint: this must be done before sleeping.**

**WO-05 Extractor.**
Accept: produces a valid `StrategySpec` for two papers in `papers/`, with a
non-empty `ambiguities` list and a `test_type`.

**WO-06 Workers and self-heal.**
Accept: three variants generated in parallel for one paper; a deliberately
injected lookahead bug is caught by Eval 1 and fixed within 3 attempts, with
every attempt in `heal_attempts` and `events.jsonl`.

**WO-07 Orchestrator, critic, records.** One command:
`python -m factory.orchestrator papers/<file>.pdf`.
Accept: end to end on one real paper, all rows written, critique appended to
the graveyard. **Checkpoint: 11:00am Saturday.** If missed, drop to 2 workers
and report Evals 3 and 5 as "not run".

**WO-08 Leaderboard and batch.** `report.py`; run 3–5 papers.
Accept: `report/leaderboard.html` opens offline and shows every variant.
**Checkpoint: 1:00pm Saturday, feature freeze.** After this: README, demo
script, a recorded backup run. No new features.

**WO-09 (stretch) Synthesis.** One agent reads `wiki/graveyard.md` and the
verified rows, proposes one hybrid strategy, which goes through the same five
strategy evals and is then scored once on HOLDOUT. Only start if WO-08 is done by noon.

## Candidate papers

Owner supplies the PDFs. Claimed numbers below are from abstracts; the
extractor must re-read them from the PDF.

| Paper | Tier | Type | Claim |
|-------|------|------|-------|
| Zarattini, Aziz, Barbon — Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY) | intraday | replication | Sharpe 1.33, 2007–early 2024, net of costs |
| Gao, Han, Li, Zhou — Market Intraday Momentum (first half-hour predicts last half-hour) | intraday | replication | Sharpe 1.08 on SPY, 1993–2013 |
| Miao (2014) — High Frequency and Dynamic Pairs Trading (two-stage correlation and cointegration) | intraday | transfer (paper uses 177 oil and gas stocks, 15-min bars) | annual Sharpe 9.25 |
| Avellaneda & Lee (2010) — Statistical Arbitrage in the US Equities Market | daily | replication, later sample | Sharpe 1.44 for PCA strategies, 1997–2007 |
| de Groot, Huij, Zhou — Another Look at Trading Costs and Short-Term Reversal Profits | daily | replication, later sample | 30–50 bps per week net, large caps |

## Software Factory breadcrumbs

Copy each work order above into `work-orders/WO-0n.md` with four headings:
Summary, Acceptance Criteria, Out of Scope, Linked Spec Section. Keep the strategy eval
table and contract as the "blueprint" they link to. This lets the repo be
indexed and the work orders imported into 8090 Software Factory later without
rewriting.

## Demo (what the build must make possible)

1. Run one paper live; the event log shows extract -> 3 variants.
2. A variant trips Eval 1; the log names the timestamp; the worker fixes it.
3. The fixed variant dies at Eval 2; break-even cost is shown next to the
   paper's claimed Sharpe.
4. Open the leaderboard: claimed vs verified across all papers.
5. One line on what survived, if anything, and the graveyard entry for what
   did not.