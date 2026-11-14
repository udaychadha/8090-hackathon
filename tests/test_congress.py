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
