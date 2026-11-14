# Financial Models In the Arena

A paper goes in, strategy candidates come out, and deterministic code judges
them. The blueprint is [AGENTS.md](AGENTS.md); the ordered backlog is in
[work-orders/](work-orders/). No LLM may influence a pass/fail decision.

## Checkpoint

- **WO-01 complete:** all 50 minute files and 503 daily files downloaded through
  2026-11-12. Live audit passed on Nov 13 PT: both NVDA split checks passed;
  five wide OHLCV frames loaded in **1.024 seconds**.
- **WO-02 complete:** contract, engine and subprocess runner implemented;
  **50 tests passed**, with lint and formatting checks passing.
- **WO-03 onward:** not started. The requested stopping point is after WO-02.

The minute tier contains 14,620,048 rows (39,230 filled, 452 unfilled gaps across
15 symbols); the daily tier contains 1,323,320 rows. Remaining gaps are reported,
not invented away. `data/audit.txt` contains the per-symbol inventory and fill
rates; `data/audit.json` contains the machine-readable acceptance record.
`data/wo02-smoke.json` records a cash-only SPY/QQQ IS integration check through
the real loader, subprocess and engine. It is not a strategy evaluation.

## Setup

Python 3.11+ (developed on Python 3.12). No brokerage or trading calls are used.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

Set `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in `.env`. Environment variables
take precedence. Keys, data, generated strategies, and run output are ignored
by Git. Paper runs read `EXTRACTOR_MODEL`, `WORKER_MODEL`, and `CRITIC_MODEL`
as `provider:model-id`, with `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` for the
selected provider. The debug CLIs load `.env`; exported settings take precedence.
See [agent execution notes](factory/agents/README.md) for pricing and paper intake.

`requirements.lock` records the installed dependency versions. To reproduce
that environment, install it first, then install the project with
`python -m pip install -e . --no-deps`.

## Data ingestion and acceptance

```sh
# All 50 minute symbols, then the saved current S&P 500 daily universe.
python -m factory.ingest_alpaca --through 2026-11-12
python -m factory.audit_data

# Optional small connection check in its own directory, not the acceptance data.
python -m factory.ingest_alpaca --tier 1day --symbols SPY BRK.B NVDA \
  --start 2024-06-03 --through 2024-06-14 --data-root data/smoke
```

Without `--through`, ingestion ends yesterday in America/Los_Angeles. Minute
history starts three years before that date; daily history starts 2016-01-01.
Pin `--through` when resuming so the snapshot does not change across midnight.
Use a different `--data-root` for a different date range or universe. Each
symbol completes atomically; interrupted minute symbols resume from monthly
chunks. A daily symbol uses one paginated range for its whole history.

Requests always use SIP and all corporate-action adjustments. Each page is at
most 10,000 points; pagination, a shared <200 requests/minute limiter, and bounded
retries are explicit. The installed `alpaca-py` request class and enums validate
request parameters. HTTP pagination is handled here so every page is throttled.
No automatic IEX substitution occurs on a permissions failure.

The S&P 500 list is fetched once from Wikipedia's constituents table and saved
to `data/sp500.csv`, with its source and retrieval time. `--sp500-csv` accepts an
owner-supplied snapshot instead. Share classes retain Alpaca's dot spelling
(`BRK.B`, `BF.B`); live format acceptance remains part of the connection check.
**The daily universe is today's index membership, so all daily results carry
survivorship bias.**

NYSE sessions determine minute coverage, including holidays, DST, and early
closes. Bars are UTC, opening-time stamped, from 09:30 up to but excluding the
session close. Missing minutes receive flat OHLC at the last close and volume
zero for at most five consecutive bars, never across sessions. Remaining gaps
stay absent and are counted. Daily bars are never filled. Invalid OHLC or
conflicting duplicate timestamps fail ingestion.

`data/ingest.jsonl` and per-symbol JSON metadata preserve fill counts/rates,
missing counts, source rows, and request settings. The audit prints the actual
file inventory, times all five wide OHLCV frames across the 50 minute symbols,
and checks the June 7 → June 10, 2024 NVDA split in both tiers. A missing check
is an incomplete acceptance, not a pass. `data/audit.json` holds the result.
Daily missing counts include dates before a symbol's first available
observation; they must not all be interpreted as vendor outages.

Splits use the shared exchange-session timestamp grid for each tier: first 60%
IS, next 20% OOS, last 20% HOLDOUT (integer boundaries rounded down). They never
depend on a strategy's chosen symbols or an individual symbol's listing date.
The intraday boundary may fall within a session. `factory.data.load_bars`
requires an explicit partition, uses Parquet predicate pushdown, and rejects
HOLDOUT unless explicitly unlocked for WO-09. Data ingestion and the trusted
inventory/load benchmark necessarily process the full tier; they run no
strategy and compute no strategy performance on held-out data.

## Checks

```sh
python -m pytest -q
ruff check factory tests
ruff format --check factory tests
```

Data tests use synthetic bars and mocked HTTP responses. They verify fill
limits, session boundaries, half days, DST, pagination, retries, persisted
Parquet, resume behavior, and partition isolation. Synthetic tests do not
stand in for the live-data acceptance checks.

## Contract and engine

`factory.contract.StrategySpec` defines the later extractor's required JSON
schema, including ambiguities, claimed metrics and replication/transfer labels.
`read_strategy` parses generated Python without importing it. The source policy
allows NumPy, pandas and math, supported deterministic operations, and seeded
`numpy.random.default_rng(params['seed'])`. It rejects I/O, network/clock APIs,
reflection, global state declarations and arbitrary top-level execution. This
is conservative lint, not proof about every possible Python program.

All tunable numbers must live in the flat `PARAMS` dictionary. Only structural
zero/one literals (including unary `-1`, for indexing, identities or cash) are
allowed elsewhere. Parameter overrides preserve names and scalar types. New
scientific APIs may need explicit review before adding them to the policy.

Weights must cover the ordered union of input timestamps, with exactly the
strategy's universe as columns. Values must be finite and within [-1, 1], with
gross exposure at most 1 (1e-12 tolerance for floating-point summation). Warmup
weights must be zero, not NaN. The subprocess checks repeated identical calls
for exact reproducibility; the parent validates its output again. Lookahead
verification still belongs to WO-03.

```python
from factory.contract import read_strategy
from factory.data import load_bars
from factory.engine import backtest
from factory.sandbox import run_strategy

path = "strategies/example/A.py"  # supplied by later worker work orders
definition = read_strategy(path)
bars = load_bars("data", definition.frequency, list(definition.universe), split="IS")
weights = run_strategy(path, bars)  # temporary cwd, 60s total limit, no provider keys
result = backtest(bars, weights, frequency=definition.frequency, round_trip_bps=5)
print(result.metrics)
```

Each evaluation slice starts flat. The engine always executes `target.shift(1)`
and charges `sum(abs(executed - previous_executed)) * (round_trip_bps / 2) / 1e4`.
It does not reset at session boundaries, so held positions earn the overnight
close-to-close return. Missing prices for held exposure are errors; the engine
does not invent fills. There is no implicit terminal liquidation.

Net bar returns compound within New York trading dates. Sharpe uses daily
returns, sample standard deviation (`ddof=1`) and `sqrt(252)` for both tiers.
Annualized return is geometric; daily turnover sums bar turnover. Maximum
drawdown uses bar-level equity including initial capital, so intraday losses
remain visible even if recovered before the close. Report equity is daily.
An undefined Sharpe (fewer than two days or zero variance) is `None`, never an
automatic pass. Daily results carry the survivorship-bias notice in
`BacktestResult.limitations`.

Contract violations, runtime tracebacks and timeouts are exposed as typed
errors for later bug-only healing. The child has no parent credentials in its
environment. Temporary files are cleaned on success, failure and timeout.

## Reference contracts

- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars):
  page size, pagination, SIP, and adjustment settings.
- [Alpaca Python request types](https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html).
- [NVIDIA's 2024 split announcement](https://investor.nvidia.com/news/press-release-details/2024/NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2025/):
  ten-for-one split with adjusted trading beginning June 10, 2024.

Generated Python will run in a separate process with a temporary working
directory and a timeout. **This is crash isolation, not a security boundary.**
Hostile Python must not be treated as safely contained by this mechanism.
