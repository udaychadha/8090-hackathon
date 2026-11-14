# Financial Models In the Arena

A paper goes in, strategy candidates come out, and deterministic code judges
them. The blueprint is [AGENTS.md](AGENTS.md); the ordered backlog is in
[work-orders/](work-orders/). No LLM may influence a pass/fail decision.

## Checkpoint

- **WO-01:** ingestion and offline tests implemented. Live acceptance is pending
  Alpaca credentials: full files, full-tier load timing, and the actual NVDA
  split check have **not** been verified.
- **WO-02:** in progress.
- **WO-03 onward:** not started. The requested stopping point is after WO-02.

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
by Git. Later agent work will read `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`;
neither is needed for WO-01 or WO-02.

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
symbol completes atomically; interrupted symbols resume from monthly chunks.

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

## Reference contracts

- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars):
  page size, pagination, SIP, and adjustment settings.
- [Alpaca Python request types](https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html).
- [NVIDIA's 2024 split announcement](https://investor.nvidia.com/news/press-release-details/2024/NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2025/):
  ten-for-one split with adjusted trading beginning June 10, 2024.

Generated Python will run in a separate process with a temporary working
directory and a timeout. **This is crash isolation, not a security boundary.**
Hostile Python must not be treated as safely contained by this mechanism.
