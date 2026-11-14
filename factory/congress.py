"""Frozen Congress experiment inputs; no outcome-dependent selection or tuning."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from factory.contract import StrategySpec
from factory.data import session_schedule
from factory.data_contract.storage import write_dataset

SOURCE = "https://github.com/kadoa-org/congress-trading-monitor"
SHORT_SAMPLE = "short sample: not a verdict"


def disclosure_availability(dates) -> pd.DatetimeIndex:
    """A date-only filing is usable at the strictly following XNYS open."""
    values = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    if values.empty or values.hasnans or values.tz is not None:
        raise ValueError("Disclosure dates must be nonempty, finite local dates")
    if not values.equals(values.normalize()):
        raise ValueError("Disclosure dates must contain dates only")
    schedule = session_schedule(
        str(values.min().date()), str((values.max() + pd.Timedelta(days=14)).date())
    )
    positions = schedule.index.searchsorted(values, side="right")
    return pd.DatetimeIndex(schedule.open.iloc[positions]).as_unit("ns")


def committee_sample_gate(dates):
    """Count/date gate fixed before evaluating any return; three calendar years."""
    dates = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    eligible = len(dates) >= 200 and dates.max() >= dates.min() + pd.DateOffset(years=3)
    return {
        "qualifying_purchases": len(dates),
        "start": None if dates.empty else str(dates.min().date()),
        "end": None if dates.empty else str(dates.max().date()),
        "verification_eligible": bool(eligible),
        "eligibility_reason": None if eligible else SHORT_SAMPLE,
    }


def store_congress_events(
    intermediate, data_root="data", *, committee_ids=None, name="congress_trades"
):
    """Normalize only an already approved/audited local source; never fetch remotely.

    Raw fields omitted from the strategy input remain in the pinned source archive.
    Empty committee samples are represented by an all-false eligibility column on
    the nonempty disclosed transaction dataset, not by fabricated purchases.
    """
    path = Path(intermediate)
    rows = json.loads(path.read_text())
    audit = json.loads(Path("report/wo12-source-audit.json").read_text())
    # The raw archive audit is independently reproducible; bind this projection
    # to its exact retained intermediate, not a mutable untracked input.
    expected = audit.get("eligible_intermediate_sha256")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is None or digest != expected:
        raise ValueError("Congress intermediate differs from approved audit")
    columns = [
        "symbol",
        "transaction_date",
        "filing_date",
        "transaction_type",
        "member_id",
        "member_name",
        "chamber",
        "source_row_id",
        "source_filing_id",
        "source_url",
        "source_commit",
    ]
    frame = pd.DataFrame(rows)[columns].astype("string")
    if (frame.filing_date < frame.transaction_date).any():
        raise ValueError("A filing precedes its transaction")
    frame.insert(0, "available_at", disclosure_availability(frame.filing_date))
    if committee_ids is not None:
        frame["committee_match"] = frame.source_row_id.isin(set(committee_ids)).astype(bool)
    frame = frame.sort_values("available_at", kind="stable").reset_index(drop=True)
    destination = Path(data_root) / "events" / f"{name}.parquet"
    if destination.exists():
        raise FileExistsError(destination)
    local = frame.available_at.dt.tz_convert("America/New_York")
    notes = ["unverified source", "Stock classifications and amendment parsing are unverified."]
    metadata = {}
    if committee_ids is not None:
        purchases = frame.loc[frame.committee_match & frame.transaction_type.eq("purchase")]
        sample = committee_sample_gate(purchases.transaction_date)
        metadata["committee_qualifying_purchases"] = len(purchases)
        notes.append(
            f"{len(purchases)} qualifying purchases; all disclosed rows are retained, "
            "and only committee_match=true rows qualify for the committee strategy."
        )
        notes.append("Committee membership is limited to exact official snapshot dates.")
        if not sample["verification_eligible"]:
            notes.append(SHORT_SAMPLE)
        roster_audit = Path("report/wo12-committee-audit.json")
        if roster_audit.exists():
            metadata["committee_audit_sha256"] = hashlib.sha256(
                roster_audit.read_bytes()
            ).hexdigest()
    manifest = write_dataset(
        destination,
        frame,
        kind="events",
        frequency="event",
        feed="user_supplied",
        adjustment="not_applicable",
        source=f"{SOURCE}/tree/{frame.source_commit.iloc[0]}",
        start=str(local.min().date()),
        through=str(local.max().date()),
        intermediate_sha256=digest,
        verified=False,
        notes=notes,
        **metadata,
    )
    return manifest


def frozen_spec(data_root="data", *, committee=False, sample=None) -> StrategySpec:
    root = Path(data_root)
    daily = set(json.loads((root / "1day/manifest.json").read_text())["symbols"])
    stocks = sorted(set(pd.read_csv(root / "sp500.csv").symbol) & daily)
    notes = [
        "unverified source",
        "Third-party disclosure parsing and amendments are unverified.",
        "GICS classifications and stock universe are current snapshots, not point-in-time.",
    ]
    rules = [
        "At each completed daily session, select distinct daily-tier stocks with at least one "
        "purchase in congress_trades whose sessions_since_available is less than 60. "
        "Availability is the next XNYS open strictly after the filing date, "
        "never transaction date.",
        "Use the supplied read-only event sessions_since_available field for the trading-session "
        "window. Include disclosed purchases from before IS when still within 60 sessions.",
        "Literal variant A equally weights selected stocks at total +0.5, and shorts SPY at -0.5. "
        "The basket excludes SPY and all other ETFs. If no stocks qualify, all weights are zero. "
        "Sales do not cancel eligibility established by a recent purchase. Rebalance daily.",
        "Use normal arena variants B (inverse-volatility sizing and turnover damping) and C "
        "(one trend or volatility filter) without changing the underlying disclosed-purchase rule. "
        "Maintain dollar neutrality and gross exposure at most one in all variants.",
        "Use only available current/past prices. Missing or too-short price histories cannot "
        "justify inventing a signal. Return only the current target row "
        "for efficient causal calls.",
    ]
    if committee:
        rules[0] = rules[0].replace("in congress_trades", "in congress_committee_trades")
        rules.insert(
            1,
            "Additionally require committee_match == True: the owner-fixed committee "
            "mapping was matched to dated rosters on transaction_date. False or uncovered "
            "rows never qualify. Do not infer or broaden committee membership.",
        )
        notes += [
            "Committee snapshots establish membership on exact documented dates only; "
            "uncovered dates are excluded."
        ]
        if sample and not sample["verification_eligible"]:
            notes.append(SHORT_SAMPLE)
    return StrategySpec(
        paper_id="congress_committee" if committee else "congress_all",
        title="Congress committee purchase basket vs SPY"
        if committee
        else "Congress purchase basket vs SPY",
        category="event-driven",
        hypothesis="Publicly disclosed congressional purchases predict "
        "returns relative to SPY; this fixed hypothesis is not tuned after results.",
        universe=["SPY", *stocks],
        frequency="1day",
        signal_rules=rules,
        claimed_metrics={},
        ambiguities=[],
        test_type="original",
        source_kind="described",
        extra=["congress_committee_trades" if committee else "congress_trades"],
        notes=notes,
        verification_eligible=(sample or {}).get("verification_eligible", True),
        eligibility_reason=(sample or {}).get("eligibility_reason"),
    )
