"""Disclosure calendars and fixed research rules are independent of outcomes."""

import pandas as pd

from factory.congress import committee_sample_gate, disclosure_availability


def test_date_only_disclosures_use_strict_next_open_across_calendar_changes():
    dates = ["2024-03-08", "2024-11-01", "2024-11-27", "2024-11-29", "2024-11-30"]
    actual = disclosure_availability(dates)
    assert actual.tolist() == list(
        pd.to_datetime(
            [
                "2024-03-11T13:30:00Z",
                "2024-11-04T14:30:00Z",
                "2024-11-29T14:30:00Z",
                "2024-12-02T14:30:00Z",
                "2024-12-02T14:30:00Z",
            ],
            utc=True,
        )
    )


def test_sample_gate_counts_only_fixed_qualifying_purchases_and_calendar_years():
    assert not committee_sample_gate([])["verification_eligible"]
    dates = ["2020-01-02"] * 199 + ["2023-01-02"]
    assert committee_sample_gate(dates)["verification_eligible"]
    assert not committee_sample_gate(dates[:-1])["verification_eligible"]
    assert not committee_sample_gate(["2020-01-02"] * 199 + ["2023-01-01"])["verification_eligible"]


def test_owner_mapping_keeps_both_energy_and_commerce_jurisdictions():
    from scripts.audit_committee_rosters import COMMITTEES

    assert COMMITTEES["ENERGY AND COMMERCE"][2] == ["Energy", "Health Care"]
    assert COMMITTEES["ARMED SERVICES"][1:] == ("GICS Sub-Industry", ["Aerospace & Defense"])


def test_committee_manifest_explains_empty_eligibility(tmp_path, monkeypatch):
    import hashlib
    import json

    from factory.congress import store_congress_events

    monkeypatch.chdir(tmp_path)
    rows = [
        {
            "symbol": "SPY",
            "transaction_date": "2024-06-01",
            "filing_date": "2024-06-03",
            "transaction_type": "purchase",
            "member_id": "example",
            "member_name": "Example",
            "chamber": "house",
            "source_row_id": "one",
            "source_filing_id": "filing",
            "source_url": "https://example.test",
            "source_commit": "a" * 40,
        }
    ]
    path = tmp_path / "intermediate.json"
    path.write_text(json.dumps(rows))
    (tmp_path / "report").mkdir()
    (tmp_path / "report/wo12-source-audit.json").write_text(
        json.dumps(
            {
                "eligible_intermediate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    )
    manifest = store_congress_events(path, committee_ids=[], name="congress_committee_trades")
    assert manifest["committee_qualifying_purchases"] == 0
    assert any("0 qualifying purchases" in note for note in manifest["notes"])
    assert "short sample: not a verdict" in manifest["notes"]
