"""Offline, reproducible audit of the owner-approved Congress source snapshot.

Reads pinned public JSON only. Never reads prices, executes strategy code, or
writes canonical events. Raw and row-level audit evidence stay under data/.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "c8fbd482625207cd4f3cecf98b7538886311834a"
BASE = ROOT / "data/source/congress"
SNAPSHOT = BASE / COMMIT
SOURCE = f"https://github.com/kadoa-org/congress-trading-monitor/tree/{COMMIT}/public/data"
ALLOWED_TYPES = {"house_clerk": "ST", "senate_efd": "Stock"}
SIDES = {"Purchase": "purchase", "Sale (Full)": "sale", "Sale (Partial)": "sale"}
OPTION = re.compile(r"\b(?:calls?|puts?|options?|warrants?|strike\s+price)\b", re.I)
NONSTOCK = re.compile(
    r"\b(?:ETF|ETN|mutual\s+fund|exchange.traded|bonds?|treasur(?:y|ies)|"
    r"municipal|debentures?|preferred|funds?|units?|iShares|SPDR|Vanguard)\b",
    re.I,
)
# Narrow instrument descriptors, not brokerage/account words such as "Trust"
# or "Portfolio" alone. Class A common equities and asset-manager companies
# (BLK, IVZ, TROW, etc.) remain eligible absent conflicting instrument evidence.
MUTUAL_FUND_TICKER = re.compile(r"[A-Z]{4}X\Z")
FUND_DESCRIPTOR = re.compile(
    r"\b(?:ProShares|PowerShares|Direxion|FlexShares|VanEck|First\s+Trust|"
    r"Goldman\s+Sachs\s+ActiveBeta|MidCap\s+Trust|Permanent\s+Portfolio|Tortoise)\b|"
    r"\bBlackRock\b[^;\n]*\bTrust\b|"
    r"\bInvesco\s+(?:QQQ|Optimum)\b|"
    r"\b(?:Inv|Investor|Institutional|Admiral)\s+(?:[A-Z]|Shares)\b|"
    r"\bFd\s+Inst\b",
    re.I,
)
# These source-confirmed fund families also have truncated names ("DR S&P
# 500" and "Corporation") in other rows, so name filtering alone is unsafe.
FUND_SYMBOL_EVIDENCE = {
    "SPY": {"source_row_id": "house_20008517_g46", "asset_name": "SPDR S&P 500"},
    "TYG": {
        "source_row_id": "house_20022756_t4",
        "asset_name": "Tortoise Energy Infrastructure Corporation",
    },
}
DEBT_OR_PRIVATE = re.compile(
    r"\b(?:structured\s+notes?|preferr\w*|PFD|privately\s+traded|"
    r"limited\s+partnership|master\s+limited)\b|"
    r"\d+(?:\.\d+)?\s*%\s*(?:due|series)\b|"
    r"\[(?:CS|GS|MF|ET|OP)\]",
    re.I,
)
CORRECTION = re.compile(r"\b(?:amend\w*|correct\w*)\b|wrong ticker|initial reporting", re.I)
TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,14}\Z")
SUPPORTED_SYMBOL = re.compile(r"[A-Z][A-Z0-9.]{0,14}\Z")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def load_rows() -> tuple[list[dict], list[dict]]:
    tree = json.loads((BASE / "tree.json").read_text())["tree"]
    files = [
        x
        for x in tree
        if x["path"].startswith(("public/data/filer/house_", "public/data/filer/senate_"))
    ]
    rows, manifest = [], []
    for item in sorted(files, key=lambda x: x["path"]):
        path = SNAPSHOT / item["path"]
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if len(raw) != item["size"] or blob != item["sha"]:
            raise ValueError(f"Pinned Git blob mismatch: {item['path']}")
        manifest.append(
            {
                "path": item["path"],
                "bytes": len(raw),
                "git_blob_sha": blob,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        payload = json.loads(raw)
        filer = payload["filer"]
        for offset, trade in enumerate(payload["trades"]):
            rows.append(
                {
                    **trade,
                    "member_name": filer["full_name"],
                    "chamber": filer["chamber"],
                    "branch": filer["branch"],
                    "source_file": item["path"],
                    "source_row": offset,
                }
            )
    return rows, manifest


def reasons(row: dict) -> list[str]:
    rejected = []
    source = row.get("source_id")
    if source not in ALLOWED_TYPES or row.get("branch") != "congress":
        rejected.append("not_congress")
    elif row.get("chamber") != {"house_clerk": "house", "senate_efd": "senate"}[source]:
        rejected.append("chamber_source_conflict")
    if row.get("asset_type") != ALLOWED_TYPES.get(source):
        rejected.append(
            "unknown_asset_type" if not row.get("asset_type") else "non_stock_asset_type"
        )
    if row.get("transaction_type") not in SIDES:
        rejected.append("not_purchase_or_sale")
    if not row.get("ticker"):
        rejected.append("missing_ticker")
    elif not isinstance(row["ticker"], str) or not TICKER.fullmatch(row["ticker"]):
        rejected.append("invalid_ticker")
    for field in ("transaction_date", "filing_date"):
        if not valid_date(row.get(field)):
            rejected.append(f"missing_or_invalid_{field}")
    if all(valid_date(row.get(k)) for k in ("transaction_date", "filing_date")):
        if row["filing_date"] < row["transaction_date"]:
            rejected.append("filing_before_transaction")
    text = f"{row.get('asset_name') or ''} {row.get('comment') or ''}"
    if OPTION.search(text):
        rejected.append("option_or_warrant_text")
    if NONSTOCK.search(text):
        rejected.append("non_stock_or_ambiguous_asset_text")
    if MUTUAL_FUND_TICKER.fullmatch(row.get("ticker") or ""):
        rejected.append("mutual_fund_ticker_heuristic")
    if row.get("ticker") in FUND_SYMBOL_EVIDENCE:
        rejected.append("source_identified_fund_symbol")
    if FUND_DESCRIPTOR.search(row.get("asset_name") or ""):
        rejected.append("fund_or_etf_descriptor")
    if DEBT_OR_PRIVATE.search(text):
        rejected.append("debt_preferred_private_or_partnership_text")
    if CORRECTION.search(text):
        rejected.append("correction_or_amendment_text")
    for field in ("id", "filing_id", "filer_id", "doc_url"):
        if not row.get(field):
            rejected.append(f"missing_{field}")
    return rejected


def normalize_eligible() -> tuple[list[dict], dict, list[dict]]:
    """Return strictly eligible records, aggregate audit, and row dispositions.

    Semantic duplicate groups are fully quarantined because source rows lack
    amendment links; picking an updated row could backdate a correction.
    """
    rows, manifest = load_rows()
    ids = Counter(r["id"] for r in rows)
    dispositions = []
    initial = []
    for row in rows:
        why = reasons(row)
        if ids[row["id"]] > 1:
            why.append("repeated_source_id")
        disposition = {
            "id": row["id"],
            "source_file": row["source_file"],
            "source_row": row["source_row"],
            "reasons": why,
        }
        dispositions.append(disposition)
        if not why:
            initial.append((row, disposition))
    groups = defaultdict(list)
    key_fields = (
        "source_id",
        "filer_id",
        "owner",
        "transaction_date",
        "ticker",
        "transaction_type",
        "amount_range_low",
        "amount_range_high",
    )
    # Check identities across raw source rows, including rejected instruments:
    # a stricter type filter must not revive the other half of an amendment.
    for row, disposition in zip(rows, dispositions, strict=True):
        if (
            row.get("ticker")
            and row.get("transaction_type") in SIDES
            and valid_date(row.get("transaction_date"))
        ):
            groups[tuple(row.get(k) for k in key_fields)].append((row, disposition))
    duplicate_groups = []
    for key, group in groups.items():
        if len(group) > 1 and any(not d["reasons"] for _, d in group):
            ids_in_group = [r["id"] for r, _ in group]
            duplicate_groups.append(
                {
                    "key": dict(zip(key_fields, key, strict=True)),
                    "source_ids": ids_in_group,
                    "filing_dates": [r["filing_date"] for r, _ in group],
                    "filing_ids": [r["filing_id"] for r, _ in group],
                }
            )
            for _, disposition in group:
                disposition["reasons"].append("ambiguous_economic_duplicate")
                disposition["duplicate_source_ids"] = ids_in_group
    eligible = []
    for row, disposition in initial:
        if disposition["reasons"]:
            continue
        # Deliberately exclude cached returns/prices and ingestion timestamps.
        eligible.append(
            {
                "transaction_date": row["transaction_date"],
                "filing_date": row["filing_date"],
                "symbol": row["ticker"],
                "transaction_type": SIDES[row["transaction_type"]],
                "transaction_type_raw": row["transaction_type"],
                "asset_type_raw": row["asset_type"],
                "asset_name": row.get("asset_name"),
                "comment": row.get("comment"),
                "member_id": row["filer_id"],
                "member_name": row["member_name"],
                "chamber": row["chamber"],
                "owner": row.get("owner"),
                "amount_range_low": row.get("amount_range_low"),
                "amount_range_high": row.get("amount_range_high"),
                "source_id": row["source_id"],
                "source_row_id": row["id"],
                "source_filing_id": row["filing_id"],
                "source_url": row["doc_url"],
                "source_commit": COMMIT,
                "source_file": row["source_file"],
                "source_row": row["source_row"],
                "verified": False,
            }
        )
    eligible.sort(key=lambda r: (r["filing_date"], r["source_row_id"]))
    source_stock_eligible = eligible
    eligible = [r for r in source_stock_eligible if SUPPORTED_SYMBOL.fullmatch(r["symbol"])]
    incompatible = [r for r in source_stock_eligible if not SUPPORTED_SYMBOL.fullmatch(r["symbol"])]
    incompatible_ids = {r["source_row_id"] for r in incompatible}
    for disposition in dispositions:
        if disposition["id"] in incompatible_ids:
            disposition["reasons"].append("unsupported_event_symbol")
    daily = {p.stem for p in (ROOT / "data/1day").glob("*.parquet")}
    matched = [r for r in eligible if r["symbol"] in daily]

    def coverage(records):
        result = {
            "rows": len(records),
            "tickers": len({r["symbol"] for r in records}),
            "chambers": dict(Counter(r["chamber"] for r in records)),
            "filing_years": dict(sorted(Counter(r["filing_date"][:4] for r in records).items())),
        }
        for field in ("transaction_date", "filing_date"):
            dates = [r[field] for r in records]
            result[field] = {
                "start": min(dates) if dates else None,
                "end": max(dates) if dates else None,
            }
        dates = result["filing_date"]
        result["filing_span_days"] = (
            (date.fromisoformat(dates["end"]) - date.fromisoformat(dates["start"])).days
            if records
            else 0
        )
        result["at_least_five_years"] = bool(
            records
            and date.fromisoformat(dates["end"])
            >= date.fromisoformat(dates["start"]).replace(
                year=date.fromisoformat(dates["start"]).year + 5
            )
        )
        return result

    statistics = json.loads((SNAPSHOT / "public/data/stats.json").read_text())
    root_rows = json.loads((SNAPSHOT / "public/data/trades.json").read_text())
    all_reasons = Counter(reason for d in dispositions for reason in d["reasons"])
    primary = Counter(d["reasons"][0] for d in dispositions if d["reasons"])
    matched_tickers = {r["symbol"] for r in matched}
    eligible_tickers = {r["symbol"] for r in eligible}
    audit = {
        "schema_version": "1.0.0",
        "audit_revision": "stock-classification-v3-symbol-schema",
        "source": SOURCE,
        "commit": COMMIT,
        "published_generated_at": statistics["generatedAt"],
        "published_total_rows": statistics["totalTrades"],
        "published_sources": statistics["bySource"],
        "root_latest_subset_rows": len(root_rows),
        "downloaded_congress_files": len(manifest),
        "downloaded_congress_rows": len(rows),
        "source_counts": dict(Counter(r["source_id"] for r in rows)),
        "excluded_executive_rows_from_published_total": statistics["bySource"]["oge_executive"],
        "asset_type_counts": dict(Counter(f"{r['source_id']}:{r.get('asset_type')}" for r in rows)),
        "strict_rows_before_duplicate_quarantine": len(initial),
        "duplicate_groups_quarantined": len(duplicate_groups),
        "duplicate_rows_quarantined": sum(
            d["reasons"] == ["ambiguous_economic_duplicate"] for d in dispositions
        ),
        "duplicate_group_raw_rows": sum(len(g["source_ids"]) for g in duplicate_groups),
        "cross_filing_duplicate_groups": sum(
            len(set(g["filing_ids"])) > 1 for g in duplicate_groups
        ),
        "repeated_source_ids": sum(n - 1 for n in ids.values()),
        "excluded_rows": sum(bool(d["reasons"]) for d in dispositions),
        "primary_exclusion_counts": dict(primary),
        "overlapping_exclusion_counts": dict(all_reasons),
        "source_stock_eligible": coverage(source_stock_eligible),
        "schema_compatibility": {
            "pattern": "^[A-Z][A-Z0-9.]{0,14}$",
            "excluded_rows": len(incompatible),
            "excluded_symbols": dict(sorted(Counter(r["symbol"] for r in incompatible).items())),
            "policy": (
                "Exclude unsupported symbols without remapping; no class-share or "
                "exchange-suffix guesses."
            ),
        },
        "eligible": coverage(eligible),
        "by_chamber": {
            ch: coverage([r for r in eligible if r["chamber"] == ch]) for ch in ("house", "senate")
        },
        "daily_overlap": {
            **coverage(matched),
            "daily_symbols_on_disk": len(daily),
            "row_fraction": len(matched) / len(eligible) if eligible else 0,
            "ticker_fraction": len(matched_tickers) / len(eligible_tickers)
            if eligible_tickers
            else 0,
            "matched_symbols": sorted(matched_tickers),
            "unmatched_symbols": sorted(eligible_tickers - daily),
        },
        "availability_policy": (
            "Strictly next XNYS session open after filing_date in "
            "America/New_York; never transaction_date. Audit does not yet create "
            "available_at."
        ),
        "classification_policy": {
            "accepted_types": ALLOWED_TYPES,
            "supported_symbol_pattern": "^[A-Z][A-Z0-9.]{0,14}$",
            "fund_symbol_evidence": FUND_SYMBOL_EVIDENCE,
            "mutual_fund_ticker_heuristic": MUTUAL_FUND_TICKER.pattern,
            "fund_descriptor_pattern": FUND_DESCRIPTOR.pattern,
            "debt_private_pattern": DEBT_OR_PRIVATE.pattern,
            "evidence_basis": (
                "Explicit source ST/Stock type plus conservative instrument-text "
                "exclusions; current index membership is not used as historical "
                "security-type proof."
            ),
        },
        "source_files": manifest,
        "supporting_files": [
            {"path": str(p.relative_to(SNAPSHOT)), "sha256": digest(p)}
            for p in sorted(SNAPSHOT.rglob("*"))
            if p.is_file() and "/filer/" not in str(p)
        ],
        "limitations": [
            "Unverified third-party extraction; source filing documents not independently checked.",
            (
                "Repository publishes no extractor/generator source; root "
                "trades.json is a 5,000-row subset. Congress per-filer rows "
                "exactly match both chamber totals."
            ),
            (
                "Only explicit House ST and Senate Stock accepted. Missing types "
                "are not guessed from tickers. Explicit derivative/fund/debt/units "
                "and correction text are conservatively excluded even when tagged "
                "Stock."
            ),
            (
                "Revision stock-classification-v2 corrects retained mutual "
                "funds/ETFs mislabeled Stock/ST: five-letter tickers ending X are "
                "quarantined as a heuristic; named fund/ETF descriptors, investor "
                "share classes, preferred/debt/private text are excluded. Generic "
                "Class A, Trust, Portfolio and asset-manager names alone are not "
                "exclusion rules."
            ),
            (
                "Revision stock-classification-v3-symbol-schema separates source "
                "stock candidates from schema-compatible retained rows; "
                "digit-leading and hyphenated symbols are excluded without "
                "speculative remapping."
            ),
            (
                "Source ST/Stock labels can be wrong. These are conservative "
                "source-based candidates, not independently verified historical "
                "security classifications, including symbols outside the current "
                "S&P 500."
            ),
            (
                "Economic duplicate groups are checked against all raw rows and "
                "quarantined in full; filtering one instrument cannot revive "
                "another row from its duplicate group. This can exclude distinct "
                "same-day trades with identical reported amount ranges; no "
                "amendment linkage exists."
            ),
            (
                "Changed-ticker/date/amount amendments and member identity aliases "
                "cannot be comprehensively resolved from retained fields. No claim "
                "of complete amendment reconciliation."
            ),
            (
                "Filing dates have no verified public posting timestamp; "
                "next-session-open rule is a conservative date-only convention, "
                "not proof of actual dissemination time."
            ),
            (
                "Historical breadth does not imply complete Congress coverage; "
                "source README says pre-2015 Senate paper filings are skipped."
            ),
            (
                "Daily overlap uses exact filenames only, not historical ticker "
                "mapping or price completeness; no bar data or holdout rows were "
                "read."
            ),
            (
                "Current daily universe has survivorship bias. Cached source "
                "return metrics and prices are never used."
            ),
        ],
    }
    assert len(rows) == sum(statistics["bySource"][s] for s in ALLOWED_TYPES)
    assert len(eligible) + audit["excluded_rows"] == len(rows)
    (BASE / "duplicate_groups.json").write_text(json.dumps(duplicate_groups, indent=2) + "\n")
    return eligible, audit, dispositions


def main():
    eligible, audit, dispositions = normalize_eligible()
    out = ROOT / "report"
    out.mkdir(exist_ok=True)
    (BASE / "eligible_intermediate.json").write_text(json.dumps(eligible, indent=2) + "\n")
    (BASE / "row_dispositions.jsonl").write_text(
        "".join(json.dumps(d) + "\n" for d in dispositions)
    )
    audit["eligible_intermediate_sha256"] = digest(BASE / "eligible_intermediate.json")
    audit["row_dispositions_sha256"] = digest(BASE / "row_dispositions.jsonl")
    audit["duplicate_groups_sha256"] = digest(BASE / "duplicate_groups.json")
    (out / "wo12-source-audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    e, overlap = audit["eligible"], audit["daily_overlap"]
    lines = [
        "# WO-12 Congress source audit",
        "",
        f"Pinned source: {SOURCE}",
        "",
        (
            "Audit revision: stock-classification-v3-symbol-schema (corrects "
            "initial fund classification and distinguishes source-eligible stocks "
            "from schema-compatible retained rows)."
        ),
        "",
        (
            f"**Five-year source gate: "
            f"{'PASS' if e['at_least_five_years'] else 'FAIL'}.** Strict eligible "
            f"filing coverage is {e['filing_date']['start']} through "
            f"{e['filing_date']['end']} ({e['filing_span_days']:,} days). This is "
            f"source coverage, not an investment result."
        ),
        "",
        (
            f"The latest-feed trades.json has only "
            f"{audit['root_latest_subset_rows']:,} rows. Downloaded and "
            f"Git-blob-verified all {audit['downloaded_congress_files']} Congress "
            f"filer files: {audit['downloaded_congress_rows']:,} rows, exactly the "
            f"published House/Senate totals. The "
            f"{audit['excluded_executive_rows_from_published_total']:,} executive "
            f"rows were not downloaded as per-filer data and are excluded."
        ),
        "",
        (
            f"Strict stock/date/action filters leave "
            f"{audit['strict_rows_before_duplicate_quarantine']:,} rows before "
            f"duplicate quarantine. {audit['duplicate_groups_quarantined']:,} "
            f"ambiguous duplicate groups ({audit['duplicate_rows_quarantined']:,} "
            f"rows) are quarantined, leaving "
            f"**{audit['source_stock_eligible']['rows']:,} source-eligible stock "
            f"rows across {audit['source_stock_eligible']['tickers']:,} tickers**."
        ),
        "",
        (
            f"The event schema requires `^[A-Z][A-Z0-9.]{{0,14}}$`. Excluding "
            f"{audit['schema_compatibility']['excluded_rows']:,} rows with "
            f"unsupported symbols without remapping leaves **{e['rows']:,} "
            f"schema-compatible retained rows across {e['tickers']:,} tickers**. "
            f"The counts below describe these retained rows."
        ),
        "",
        "| Chamber | Rows | Tickers | Filing dates | Transaction dates |",
        "|---|---:|---:|---|---|",
    ]
    for ch, c in audit["by_chamber"].items():
        lines.append(
            f"| {ch} | {c['rows']:,} | {c['tickers']:,} | "
            f"{c['filing_date']['start']}–{c['filing_date']['end']} | "
            f"{c['transaction_date']['start']}–{c['transaction_date']['end']} |"
        )
    lines += [
        "",
        (
            f"Exact-symbol overlap with {overlap['daily_symbols_on_disk']} local "
            f"daily files: **{overlap['rows']:,}/{e['rows']:,} rows "
            f"({overlap['row_fraction']:.1%})**, "
            f"**{overlap['tickers']:,}/{e['tickers']:,} tickers "
            f"({overlap['ticker_fraction']:.1%})**. Matched filing coverage: "
            f"{overlap['filing_date']['start']}–{overlap['filing_date']['end']}. "
            f"This does not assert price availability for every event; bar contents "
            f"were not read."
        ),
        "",
        "Primary exclusion reasons (mutually exclusive, in validation order):",
        "",
        "| Reason | Rows |",
        "|---|---:|",
    ]
    lines += [f"| {key} | {value:,} |" for key, value in audit["primary_exclusion_counts"].items()]
    lines += [
        "",
        (
            f"Filing-before-transaction anomalies: "
            f"{audit['overlapping_exclusion_counts'].get('filing_before_transaction', 0):,}. "
            f"Repeated source IDs: {audit['repeated_source_ids']}. Cross-filing "
            f"duplicate groups quarantined: "
            f"{audit['cross_filing_duplicate_groups']:,}. Full overlapping reasons, "
            f"annual counts, checksums, and overlap symbols are in the JSON report; "
            f"row IDs and exclusion traces remain ignored under "
            f"data/source/congress/."
        ),
        "",
        (
            "Availability must be the strictly next XNYS session open after the "
            "filing's New York calendar date, never its transaction date. No "
            "canonical event file, strategy execution, model call, or backtest was "
            "produced by this audit."
        ),
        "",
        "Limitations:",
        "",
    ]
    lines += [f"- {note}" for note in audit["limitations"]]
    lines += [
        "",
        "Reproduce offline: `.venv/bin/python scripts/audit_congress_source.py`.",
        "",
        (
            "The ignored eligible_intermediate.json preserves transaction and "
            "filing dates, member, chamber, symbol, source row/filing IDs, source "
            "URL, and pinned payload location. It intentionally omits cached "
            "performance fields."
        ),
    ]
    (out / "wo12-source-audit.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {k: audit[k] for k in ("eligible", "by_chamber", "primary_exclusion_counts")}, indent=2
        )
    )
    print(
        "Daily overlap",
        overlap["rows"],
        overlap["tickers"],
        overlap["row_fraction"],
        overlap["ticker_fraction"],
    )


if __name__ == "__main__":
    main()
