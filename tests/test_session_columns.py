"""Calendar-derived session inputs must survive slices without moving boundaries."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from factory.data_contract.errors import DataError


def session_api():
    from factory.data_contract.sessions import (
        add_session_columns,
        protected_session_columns,
        validate_session_columns,
    )

    return add_session_columns, protected_session_columns, validate_session_columns


def bars(index):
    index = pd.DatetimeIndex(index, dtype="datetime64[ns, UTC]", name="timestamp")
    frame = pd.DataFrame(100.0, index=index, columns=["open", "high", "low", "close"])
    frame["volume"] = 1.0
    frame["is_filled"] = False
    return frame


@pytest.mark.parametrize(
    "day,utc_open,utc_last,duration",
    [
        ("2024-03-08", "14:30", "20:59", 390),
        ("2024-03-11", "13:30", "19:59", 390),
        ("2024-11-01", "13:30", "19:59", 390),
        ("2024-11-04", "14:30", "20:59", 390),
        ("2024-11-29", "14:30", "17:59", 210),
    ],
)
def test_calendar_offsets_across_dst_and_early_close(day, utc_open, utc_last, duration):
    add, _, validate = session_api()
    frame = bars([f"{day}T{utc_open}Z", f"{day}T{utc_last}Z"])
    original = frame.copy(deep=True)
    result = add(frame, "1min")
    assert result.minutes_since_open.tolist() == [0, duration - 1]
    assert result.minutes_to_close.tolist() == [duration, 1]
    assert result.is_first_bar.tolist() == [True, False]
    assert result.is_last_bar.tolist() == [False, True]
    assert result.session_date.tolist() == [pd.Timestamp(day, tz="America/New_York")] * 2
    assert str(result.session_date.dtype) == "datetime64[ns, America/New_York]"
    assert str(result.minutes_since_open.dtype) == str(result.minutes_to_close.dtype) == "int64"
    assert str(result.is_first_bar.dtype) == str(result.is_last_bar.dtype) == "bool"
    pd.testing.assert_frame_equal(frame, original)
    validate(result, "1min", "SPY/1min")


@pytest.mark.parametrize(
    "day,utc_midnight,duration",
    [
        ("2024-03-08", "05:00", 390),
        ("2024-03-11", "04:00", 390),
        ("2024-11-29", "05:00", 210),
    ],
)
def test_daily_labels_describe_scheduled_session(day, utc_midnight, duration):
    add, _, validate = session_api()
    result = add(bars([f"{day}T{utc_midnight}Z"]), "1day")
    assert result.minutes_since_open.tolist() == [0]
    assert result.minutes_to_close.tolist() == [duration]
    assert result.is_first_bar.all() and result.is_last_bar.all()
    assert result.session_date.iloc[0] == pd.Timestamp(day, tz="America/New_York")
    validate(result, "1day", "SPY/1day")


@settings(max_examples=40, deadline=None)
@given(
    day=st.sampled_from(["2024-03-08", "2024-03-11", "2024-11-29"]),
    retained=st.sets(st.integers(min_value=1, max_value=208), min_size=1, max_size=40),
)
def test_missing_edges_and_arbitrary_subsets_never_move_session_flags(day, retained):
    add, _, _ = session_api()
    start = pd.Timestamp(f"{day} 09:30", tz="America/New_York").tz_convert("UTC")
    frame = bars(start + pd.to_timedelta(sorted(retained), unit="min"))
    result = add(frame, "1min")
    assert not result.is_first_bar.any()
    assert not result.is_last_bar.any()
    assert result.minutes_since_open.tolist() == sorted(retained)
    duration = 210 if day == "2024-11-29" else 390
    assert (result.minutes_since_open + result.minutes_to_close).eq(duration).all()
    subset = frame.iloc[: max(1, len(frame) // 2)]
    pd.testing.assert_frame_equal(add(subset, "1min"), result.loc[subset.index])


@pytest.mark.parametrize(
    "stamp,frequency",
    [
        ("2024-11-28T15:30Z", "1min"),  # Thanksgiving
        ("2024-11-30T15:30Z", "1min"),  # Saturday
        ("2024-11-29T18:00Z", "1min"),  # At early close, outside half-open session
        ("2024-03-11T13:29Z", "1min"),  # Before open
        ("2024-03-11T13:30:30Z", "1min"),
        ("2024-03-11T00:00Z", "1day"),  # UTC midnight is not NY date label
    ],
)
def test_invalid_calendar_labels_fail_with_dataset_rule_and_first_row(stamp, frequency):
    add, _, _ = session_api()
    with pytest.raises(DataError, match="rule=session_derivation.calendar; row=0:"):
        add(bars([stamp]), frequency)


@pytest.mark.parametrize(
    "column,value",
    [
        ("session_date", pd.Timestamp("2024-03-12", tz="America/New_York")),
        ("minutes_since_open", 100),
        ("minutes_to_close", 100),
        ("is_first_bar", True),
        ("is_last_bar", True),
    ],
)
def test_validator_names_first_mismatched_row(column, value):
    add, protected, validate = session_api()
    result = add(bars(pd.date_range("2024-03-11T13:30Z", periods=3, freq="min")), "1min")
    assert column in protected()
    result.loc[result.index[1], column] = value
    with pytest.raises(DataError, match=r"SPY/1min: rule=session_derivation; row=1:"):
        validate(result, "1min", "SPY/1min")


def test_validator_rejects_missing_and_wrong_dtype_columns():
    add, _, validate = session_api()
    result = add(bars(["2024-03-11T13:30Z"]), "1min")
    with pytest.raises(DataError, match="session_derivation.columns"):
        validate(result.drop(columns="is_last_bar"), "1min", "SPY")
    result["minutes_to_close"] = result.minutes_to_close.astype(float)
    with pytest.raises(DataError, match="session_derivation.dtype"):
        validate(result, "1min", "SPY")


def test_empty_slices_keep_declared_dtypes():
    add, _, validate = session_api()
    result = add(bars([]), "1min")
    assert str(result.session_date.dtype) == "datetime64[ns, America/New_York]"
    assert str(result.minutes_since_open.dtype) == "int64"
    assert str(result.is_last_bar.dtype) == "bool"
    validate(result, "1min", "empty slice")


def load_canary():
    path = Path(__file__).parent / "fixtures" / "session_canary.py"
    spec = importlib.util.spec_from_file_location("session_canary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canary_has_exact_decision_window_and_flattens_early_close():
    add, _, _ = session_api()
    canary = load_canary()
    index = (
        pd.date_range("2024-11-27T14:30Z", "2024-11-27T20:59Z", freq="min")
        .append(pd.date_range("2024-11-29T14:30Z", "2024-11-29T17:59Z", freq="min"))
        .append(pd.DatetimeIndex(["2024-12-02T14:30Z"]))
    )
    frame = add(bars(index), "1min")
    # A large overnight gap must earn no PnL after the early-close target is zero.
    frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = 200.0
    weights = canary.generate_signals({"SPY": frame}, canary.PARAMS)
    np.testing.assert_array_equal(
        weights.SPY.iloc[:390], np.r_[np.zeros(29), np.ones(330), np.zeros(31)]
    )
    np.testing.assert_array_equal(weights.SPY.iloc[390:600], np.r_[np.zeros(29), np.ones(180), 0])
    from factory.engine import backtest

    result = backtest({"SPY": frame}, weights, frequency="1min")
    assert result.turnover.sum() == 4
    assert result.gross_bar_returns.iloc[-1] == 0
    assert result.executed.SPY.loc[frame.is_first_bar].eq(0).all()
    assert weights.SPY.loc[frame.is_last_bar].eq(0).all()
