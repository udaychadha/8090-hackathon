"""Audit only the seven owner-approved official point-in-time rosters.

Raw PDFs, extracted text and membership rows stay in gitignored data/source.
No model, strategy, price observations, or production records are accessed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/source/committee"
SOURCES = [
    (
        "house",
        "2019-12-02",
        "https://historycms.house.gov/WorkArea/DownloadAsset.aspx?id=25769816736",
    ),
    (
        "house",
        "2021-02-01",
        "https://historycms.house.gov/WorkArea/DownloadAsset.aspx?id=25769822882",
    ),
    (
        "house",
        "2024-12-16",
        "https://historycms.house.gov/WorkArea/DownloadAsset.aspx?id=36507226670",
    ),
] + [
    (
        "senate",
        date,
        f"https://www.govinfo.gov/content/pkg/GPO-CPUB-{edition}/pdf/GPO-CPUB-{edition}.pdf",
    )
    for date, edition in [
        ("2019-03-18", "116spub2"),
        ("2021-06-08", "117spub5"),
        ("2023-03-30", "118spub3"),
        ("2025-06-12", "119spub4"),
    ]
]

COMMITTEES = {
    "ARMED SERVICES": ("Armed Services", "GICS Sub-Industry", ["Aerospace & Defense"]),
    "ENERGY AND COMMERCE": ("Energy and Commerce", "GICS Sector", ["Energy"]),
    "FINANCIAL SERVICES": ("Financial Services", "GICS Sector", ["Financials"]),
    "BANKING, HOUSING, AND URBAN AFFAIRS": (
        "Banking, Housing, and Urban Affairs",
        "GICS Sector",
        ["Financials"],
    ),
    "COMMERCE, SCIENCE, AND TRANSPORTATION": (
        "Commerce, Science, and Transportation",
        "GICS Sector",
        ["Communication Services", "Information Technology"],
    ),
    "ENERGY AND NATURAL RESOURCES": ("Energy and Natural Resources", "GICS Sector", ["Energy"]),
    "HEALTH, EDUCATION, LABOR, AND PENSIONS": (
        "Health, Education, Labor, and Pensions",
        "GICS Sector",
        ["Health Care"],
    ),
    "ENERGY AND COMMERCE / HEALTH": (
        "Energy and Commerce / Health",
        "GICS Sector",
        ["Health Care"],
    ),
}
# Page references are one-based PDF pages, not the printed page labels.
HEALTH_PAGES = {"house-2019-12-02": 20, "house-2024-12-16": 21}


def normalized_name(name: str) -> str:
    """Case, accents, and punctuation only; retain names, initials and suffixes."""
    name = unicodedata.normalize("NFKD", name.casefold())
    return " ".join(re.sub(r"[^a-z0-9 ]", "", name).split())


def memberships(manifest: list[dict]) -> list[dict]:
    rows = []
    checks = []
    for source in manifest:
        with pymupdf.open(OUT / f"{source['id']}.pdf") as doc:
            for page_index, page in enumerate(doc):
                lines = [line.strip() for line in page.get_text().splitlines()]
                for heading_index, heading in enumerate(lines):
                    key = heading
                    if heading == "HEALTH" and page_index + 1 == HEALTH_PAGES.get(source["id"]):
                        key = "ENERGY AND COMMERCE / HEALTH"
                    if key not in COMMITTEES:
                        continue
                    names = []
                    for line in lines[heading_index + 1 :]:
                        if line == "Subcommittees" or line.startswith("SUBCOMMITTEES"):
                            break
                        if line.isupper() and len(line) > 8:
                            break
                        if source["chamber"] == "house":
                            match = re.match(r"^(.+?),\s*([A-Z]{2})(?:,|$)", line)
                        else:
                            match = re.match(r"^(.+?), of (.+)", line)
                        if match:
                            name = re.sub(r"^\d+\.\s*", "", match.group(1)).strip()
                            names.append(name)
                            rows.append(
                                {
                                    "member_name": name,
                                    "normalized_name": normalized_name(name),
                                    "chamber": source["chamber"],
                                    "committee": COMMITTEES[key][0],
                                    "start": source["snapshot_date"],
                                    "end": source["snapshot_date"],
                                    "period_kind": "snapshot_day_only",
                                    "source_url": source["url"],
                                    "source_id": source["id"],
                                    "source_sha256": source["sha256"],
                                    "source_page": page_index + 1,
                                    "source_line": line,
                                    "ex_officio": "Ex Officio" in line,
                                    "published_at": None,
                                    "publication_status": (
                                        "historical_public_availability_unestablished"
                                    ),
                                    "gics_field": COMMITTEES[key][1],
                                    "gics_values": COMMITTEES[key][2],
                                }
                            )
                    if not names:
                        raise ValueError(f"Roster heading without members: {source['id']} {key}")
                    checks.append(
                        {
                            "source_id": source["id"],
                            "committee": COMMITTEES[key][0],
                            "source_page": page_index + 1,
                            "member_count": len(names),
                        }
                    )
    expected = 3 * 3 + 2 + 4 * 5
    if len(checks) != expected:
        raise ValueError(f"Expected {expected} roster sections, found {len(checks)}")
    keys = [(r["source_id"], r["committee"], r["normalized_name"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Ambiguous duplicate roster membership")
    (OUT / "memberships.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    (OUT / "extraction_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    return rows


def audit(manifest: list[dict], members: list[dict]) -> dict:
    trade_path = ROOT / "data/source/congress/eligible_intermediate.json"
    universe_path = ROOT / "data/sp500.csv"
    trades = json.loads(trade_path.read_text())
    with universe_path.open() as handle:
        universe = {r["symbol"]: r for r in csv.DictReader(handle)}
    snapshot_dates = {(s["chamber"], s["snapshot_date"]) for s in manifest}
    index = {}
    for member in members:
        key = (member["chamber"], member["start"], member["normalized_name"])
        index.setdefault(key, []).append(member)
    dispositions = Counter()
    point_rows = []
    qualifying = []
    for trade in trades:
        if trade["transaction_type"] != "purchase":
            dispositions["not_purchase"] += 1
            continue
        if (trade["chamber"], trade["transaction_date"]) not in snapshot_dates:
            dispositions["no_snapshot_on_transaction_date"] += 1
            continue
        matched = index.get(
            (trade["chamber"], trade["transaction_date"], normalized_name(trade["member_name"])), []
        )
        classification = universe.get(trade["symbol"])
        relevant = [
            m
            for m in matched
            if classification and classification[m["gics_field"]] in m["gics_values"]
        ]
        reason = (
            "not_in_current_daily_universe"
            if classification is None
            else "no_strict_name_match_on_relevant_rosters"
            if not matched
            else "gics_mapping_does_not_match"
            if not relevant
            else "qualifies_membership_only"
        )
        dispositions[reason] += 1
        item = dict(
            trade,
            matched_committees=[m["committee"] for m in matched],
            matching_memberships=relevant,
            gics_sector=classification.get("GICS Sector") if classification else None,
            gics_sub_industry=classification.get("GICS Sub-Industry") if classification else None,
            committee_audit_disposition=reason,
        )
        point_rows.append(item)
        if relevant:
            qualifying.append(item)
    (OUT / "point_date_purchase_audit.json").write_text(
        json.dumps(point_rows, indent=2, ensure_ascii=False) + "\n"
    )
    (OUT / "qualifying_purchases_membership_only.json").write_text(
        json.dumps(qualifying, indent=2, ensure_ascii=False) + "\n"
    )
    dates = sorted(r["transaction_date"] for r in qualifying)
    short_sample = (
        len(qualifying) < 200
        or not dates
        or (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days < 1095
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "sources": manifest,
        "input_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (trade_path, universe_path)
        },
        "membership_rows": len(members),
        "roster_sections": json.loads((OUT / "extraction_checks.json").read_text()),
        "eligible_trade_input_rows": len(trades),
        "point_date_purchases": len(point_rows),
        "point_date_purchases_in_daily_universe": sum(x["symbol"] in universe for x in point_rows),
        "dispositions": dict(dispositions),
        "qualifying_purchase_count": len(qualifying),
        "qualifying_transaction_start": dates[0] if dates else None,
        "qualifying_transaction_end": dates[-1] if dates else None,
        "short_sample": short_sample,
        "required_note": "short sample: not a verdict" if short_sample else None,
        "verified_eligible": not short_sample,
        "historical_availability_eligible_count": 0,
        "historical_availability_policy": (
            "No roster public-release timestamp established. Do not treat cover, metadata or "
            "production date as public availability. Historical usable rows are zero until "
            "evidence or owner decision resolves this; no inferred timestamp was created."
        ),
        "matching_policy": (
            "Exact normalized name plus chamber and exact snapshot/transaction date; "
            "punctuation/case/accents normalized; no aliases, middle-name deletion, "
            "fuzzy matching or crosswalk used."
        ),
        "aliases_applied": [],
        "limitations": [
            "unverified source",
            "Current daily universe carries survivorship bias.",
            "GICS sector/sub-industry classifications come from the current static "
            "data/sp500.csv, not historical classifications.",
            "Seven snapshot days only; no inference over congressional terms or between snapshots.",
            "The 2021-02-01 House publication contains no Health subcommittee roster; "
            "no Health membership inferred from full Energy and Commerce membership.",
            "Strict matching can exclude genuine aliases; unmatched rows remain excluded "
            "and are retained for review.",
            "PDF metadata and production timestamps do not establish public availability.",
        ],
    }
    report_dir = ROOT / "report"
    report_dir.mkdir(exist_ok=True)
    (report_dir / "wo12-committee-audit.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    lines = [
        "# WO-12 committee snapshot audit",
        "",
        "Approved source PDFs were downloaded, hashed and retained under gitignored "
        "`data/source/committee/`. No strategies or models were run.",
        "",
        f"**Qualifying purchases: {len(qualifying)}. "
        f"Date range: {dates[0] if dates else 'none'} to {dates[-1] if dates else 'none'}.**",
        f"Required result note: **{report['required_note']}**. "
        f"VERIFIED eligibility: **{report['verified_eligible']}**.",
        "",
        f"Input rows: {len(trades)}. Purchases on an approved snapshot day for the same chamber: "
        f"{len(point_rows)}; current daily-universe overlap: "
        f"{report['point_date_purchases_in_daily_universe']}.",
        "",
        "## Approved sources and exact coverage",
        "",
        "| Source | Membership coverage | Extracted rows | SHA-256 |",
        "|---|---|---:|---|",
    ]
    for s in manifest:
        lines.append(
            f"| [{s['id']}]({s['url']}) | {s['snapshot_date']} only | "
            f"{sum(r['source_id'] == s['id'] for r in members)} | `{s['sha256']}` |"
        )
    lines += [
        "",
        "## Matching and fixed mapping",
        "",
        report["matching_policy"],
        "",
        "No aliases were applied. Normalized rows retain original member spelling, source line, "
        "source PDF page, hash, and start=end=snapshot date.",
        "",
    ]
    for name, field, values in COMMITTEES.values():
        lines.append(f"- {name}: {field} = {', '.join(values)}.")
    lines += [
        "",
        "## Point-date purchase disposition",
        "",
        "| Member | Chamber | Transaction date | Symbol | Sector | "
        "Matched relevant committees | Disposition |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in point_rows:
        lines.append(
            f"| {r['member_name']} | {r['chamber']} | {r['transaction_date']} | {r['symbol']} | "
            f"{r['gics_sector'] or 'outside universe'} | "
            f"{', '.join(r['matched_committees']) or 'none'} | "
            f"{r['committee_audit_disposition']} |"
        )
    lines += [
        "",
        "## Public availability",
        "",
        report["historical_availability_policy"],
        "",
        "If an independently evidenced publication time becomes available, derived event "
        "availability must be no earlier than BOTH the disclosure-based next market open "
        "and roster publication availability. A snapshot date establishes the membership "
        "observation, not when that observation was public.",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {x}" for x in report["limitations"]]
    (report_dir / "wo12-committee-audit.md").write_text("\n".join(lines) + "\n")
    return report


def prepare(download: bool = False) -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "download_manifest.json"
    existing = (
        {x["id"]: x for x in json.loads(manifest_path.read_text())}
        if manifest_path.exists()
        else {}
    )
    manifest = []
    for chamber, date, url in SOURCES:
        key = f"{chamber}-{date}"
        path = OUT / f"{key}.pdf"
        retrieved_at = existing.get(key, {}).get("retrieved_at")
        if not path.exists():
            if not download:
                raise FileNotFoundError(f"Approved source not downloaded: {path}")
            body = subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "60",
                    url,
                ],
                check=True,
                capture_output=True,
            ).stdout
            if not body.startswith(b"%PDF"):
                raise ValueError(f"Not a PDF: {url}")
            path.write_bytes(body)
            retrieved_at = datetime.now(UTC).isoformat()
        with pymupdf.open(path) as doc:
            pages = [page.get_text() for page in doc]
            path.with_suffix(".md").write_text(
                "\n\n".join(
                    f"## PDF page {i + 1}\n\n```text\n{text}\n```" for i, text in enumerate(pages)
                )
            )
            manifest.append(
                {
                    "id": key,
                    "chamber": chamber,
                    "snapshot_date": date,
                    "url": url,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "pages": len(pages),
                    "pdf_metadata": doc.metadata,
                    "retrieved_at": retrieved_at,
                    "published_at": None,
                    "publication_issue": (
                        "Cover date is a roster snapshot date. Public release timestamp is not "
                        "established; PDF creation/modification is not public availability."
                    ),
                }
            )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-approved", action="store_true")
    args = parser.parse_args()
    sources = prepare(args.download_approved)
    report = audit(sources, memberships(sources))
    print(
        json.dumps(
            {
                key: report[key]
                for key in [
                    "membership_rows",
                    "point_date_purchases",
                    "point_date_purchases_in_daily_universe",
                    "qualifying_purchase_count",
                    "qualifying_transaction_start",
                    "qualifying_transaction_end",
                    "short_sample",
                    "verified_eligible",
                    "dispositions",
                ]
            },
            indent=2,
        )
    )
