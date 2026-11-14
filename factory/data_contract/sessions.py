"""Scheduled session facts for strategies, independent of observed slice endpoints."""

from functools import lru_cache

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from factory.data_contract.errors import fail
from factory.data_contract.generated import SPEC


def protected_session_columns() -> tuple[str, ...]:
    """Names whose calendar-derived values strategies must not alter or delete."""
    return tuple(
        name
        for name, definition in SPEC["ontology"]["Bar"]["derived_fields"].items()
        if definition["read_only"]
    )


@lru_cache(maxsize=16)
def _schedule(name: str, start: str, end: str) -> pd.DataFrame:
    calendar = xcals.get_calendar(
        name,
        start=pd.Timestamp(start) - pd.Timedelta(days=7),
        end=pd.Timestamp(end) + pd.Timedelta(days=7),
    )
    return calendar.schedule.loc[start:end, ["open", "close"]]


def _derived(frame: pd.DataFrame, frequency: str, dataset: str) -> pd.DataFrame:
    rule = "session_derivation"
    if not isinstance(frame, pd.DataFrame):
        fail(dataset, rule, detail="Expected a DataFrame")
    if frequency not in ("1min", "1day"):
        fail(dataset, rule, frame, detail=f"Unsupported frequency {frequency!r}")
    calendar = SPEC["calendar"]
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or str(frame.index.dtype) != f"datetime64[ns, {calendar['timestamp_timezone']}]"
    ):
        fail(dataset, rule + ".index", frame, detail="Expected UTC nanosecond timestamps")
    if frame.index.hasnans:
        fail(dataset, rule + ".index", frame, np.flatnonzero(frame.index.isna())[0], "NaT")
    definitions = SPEC["ontology"]["Bar"]["derived_fields"]
    if frame.empty:
        return pd.DataFrame(
            {
                name: pd.Series(index=frame.index, dtype=definition["dtype"])
                for name, definition in definitions.items()
            },
            index=frame.index,
        )
    dates = frame.index.tz_convert(calendar["timezone"]).normalize()
    local_dates = dates.tz_localize(None)
    schedule = _schedule(
        calendar["name"], str(local_dates.min().date()), str(local_dates.max().date())
    )
    aligned = schedule.reindex(local_dates)
    opens = pd.DatetimeIndex(aligned.open)
    closes = pd.DatetimeIndex(aligned.close)
    minute = pd.Timedelta(minutes=1)
    slot = pd.Timedelta(minutes=calendar["minute_duration"])
    elapsed = frame.index - opens
    valid = ~opens.isna()
    if frequency == "1min":
        valid &= (
            (frame.index >= opens) & (frame.index < closes) & (elapsed % slot == pd.Timedelta(0))
        )
    else:
        valid &= frame.index == dates.tz_convert(calendar["timestamp_timezone"])
    if not valid.all():
        fail(
            dataset,
            rule + ".calendar",
            frame,
            np.flatnonzero(~valid)[0],
            "Label is not a scheduled calendar slot",
        )
    daily = frequency == "1day"
    values = {
        "local_date": dates,
        "elapsed_start": np.zeros(len(frame), dtype="int64") if daily else elapsed // minute,
        "remaining_start": ((closes - opens) if daily else (closes - frame.index)) // minute,
        "scheduled_first": np.ones(len(frame), dtype=bool) if daily else frame.index == opens,
        "scheduled_last": np.ones(len(frame), dtype=bool)
        if daily
        else frame.index == closes - slot,
    }
    result = pd.DataFrame(index=frame.index)
    for name, definition in definitions.items():
        operation = definition["derive"]
        if operation not in values:
            fail(dataset, rule, frame, detail=f"Unknown derivation {operation!r}")
        result[name] = pd.Series(values[operation], index=frame.index, dtype=definition["dtype"])
    return result


def add_session_columns(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Return a copy with canonical columns; missing bars never change boundaries."""
    derived = _derived(frame, frequency, "strategy bars")
    result = frame.copy()
    for name in derived:
        result[name] = derived[name]
    return result


def validate_session_columns(frame: pd.DataFrame, frequency: str, dataset: str) -> pd.DataFrame:
    """Reject absent, mistyped or incorrect derived values with the first bad row."""
    expected = _derived(frame, frequency, dataset)
    if not frame.columns.is_unique or not set(expected.columns) <= set(frame.columns):
        fail(
            dataset,
            "session_derivation.columns",
            frame,
            detail="Missing or duplicate session fields",
        )
    mismatched = np.zeros(len(frame), dtype=bool)
    for name in expected:
        if frame[name].dtype != expected[name].dtype:
            fail(
                dataset,
                "session_derivation.dtype",
                frame,
                detail=f"{name}: expected {expected[name].dtype}, got {frame[name].dtype}",
            )
        mismatched |= frame[name].isna().to_numpy() | frame[name].ne(expected[name]).to_numpy()
    if mismatched.any():
        position = np.flatnonzero(mismatched)[0]
        fields = [
            name
            for name in expected
            if not frame[name].iloc[position] == expected[name].iloc[position]
        ]
        fail(
            dataset,
            "session_derivation",
            frame,
            position,
            f"Values differ from scheduled calendar: {fields}",
        )
    return frame
