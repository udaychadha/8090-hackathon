# WO-12 Congress source audit

Pinned source: https://github.com/kadoa-org/congress-trading-monitor/tree/c8fbd482625207cd4f3cecf98b7538886311834a/public/data

Audit revision: stock-classification-v3-symbol-schema (corrects initial fund classification and distinguishes source-eligible stocks from schema-compatible retained rows).

**Five-year source gate: PASS.** Strict eligible filing coverage is 2015-01-20 through 2026-11-10 (4,312 days). This is source coverage, not an investment result.

The latest-feed trades.json has only 5,000 rows. Downloaded and Git-blob-verified all 371 Congress filer files: 63,737 rows, exactly the published House/Senate totals. The 15,528 executive rows were not downloaded as per-filer data and are excluded.

Strict stock/date/action filters leave 32,225 rows before duplicate quarantine. 937 ambiguous duplicate groups (1,835 rows) are quarantined, leaving **30,390 source-eligible stock rows across 2,788 tickers**.

The event schema requires `^[A-Z][A-Z0-9.]{0,14}$`. Excluding 24 rows with unsupported symbols without remapping leaves **30,366 schema-compatible retained rows across 2,782 tickers**. The counts below describe these retained rows.

| Chamber | Rows | Tickers | Filing dates | Transaction dates |
|---|---:|---:|---|---|
| house | 25,928 | 2,530 | 2018-04-18–2026-11-10 | 2011-06-20–2026-11-02 |
| senate | 4,438 | 1,186 | 2015-01-20–2026-11-04 | 2014-03-20–2026-10-21 |

Exact-symbol overlap with 507 local daily files: **19,147/30,366 rows (63.1%)**, **495/2,782 tickers (17.8%)**. Matched filing coverage: 2015-01-20–2026-11-10. This does not assert price availability for every event; bar contents were not read.

Primary exclusion reasons (mutually exclusive, in validation order):

| Reason | Rows |
|---|---:|
| non_stock_or_ambiguous_asset_text | 1,399 |
| non_stock_asset_type | 3,956 |
| unknown_asset_type | 25,337 |
| fund_or_etf_descriptor | 87 |
| not_purchase_or_sale | 244 |
| ambiguous_economic_duplicate | 1,835 |
| option_or_warrant_text | 126 |
| source_identified_fund_symbol | 12 |
| debt_preferred_private_or_partnership_text | 45 |
| missing_ticker | 254 |
| correction_or_amendment_text | 20 |
| missing_or_invalid_transaction_date | 3 |
| unsupported_event_symbol | 24 |
| mutual_fund_ticker_heuristic | 29 |

Filing-before-transaction anomalies: 0. Repeated source IDs: 0. Cross-filing duplicate groups quarantined: 920. Full overlapping reasons, annual counts, checksums, and overlap symbols are in the JSON report; row IDs and exclusion traces remain ignored under data/source/congress/.

Availability must be the strictly next XNYS session open after the filing's New York calendar date, never its transaction date. No canonical event file, strategy execution, model call, or backtest was produced by this audit.

Limitations:

- Unverified third-party extraction; source filing documents not independently checked.
- Repository publishes no extractor/generator source; root trades.json is a 5,000-row subset. Congress per-filer rows exactly match both chamber totals.
- Only explicit House ST and Senate Stock accepted. Missing types are not guessed from tickers. Explicit derivative/fund/debt/units and correction text are conservatively excluded even when tagged Stock.
- Revision stock-classification-v2 corrects retained mutual funds/ETFs mislabeled Stock/ST: five-letter tickers ending X are quarantined as a heuristic; named fund/ETF descriptors, investor share classes, preferred/debt/private text are excluded. Generic Class A, Trust, Portfolio and asset-manager names alone are not exclusion rules.
- Revision stock-classification-v3-symbol-schema separates source stock candidates from schema-compatible retained rows; digit-leading and hyphenated symbols are excluded without speculative remapping.
- Source ST/Stock labels can be wrong. These are conservative source-based candidates, not independently verified historical security classifications, including symbols outside the current S&P 500.
- Economic duplicate groups are checked against all raw rows and quarantined in full; filtering one instrument cannot revive another row from its duplicate group. This can exclude distinct same-day trades with identical reported amount ranges; no amendment linkage exists.
- Changed-ticker/date/amount amendments and member identity aliases cannot be comprehensively resolved from retained fields. No claim of complete amendment reconciliation.
- Filing dates have no verified public posting timestamp; next-session-open rule is a conservative date-only convention, not proof of actual dissemination time.
- Historical breadth does not imply complete Congress coverage; source README says pre-2015 Senate paper filings are skipped.
- Daily overlap uses exact filenames only, not historical ticker mapping or price completeness; no bar data or holdout rows were read.
- Current daily universe has survivorship bias. Cached source return metrics and prices are never used.

Reproduce offline: `.venv/bin/python scripts/audit_congress_source.py`.

The ignored eligible_intermediate.json preserves transaction and filing dates, member, chamber, symbol, source row/filing IDs, source URL, and pinned payload location. It intentionally omits cached performance fields.
