"""Mutation properties for every canonical invariant; stored scans are opt-in."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from factory.data_contract import DataError, validate_events, validate_price_bars
from factory.data_contract.generated import SPEC
from factory.data_contract.runtime import validate_entity
from factory.data_contract.sessions import add_session_columns, validate_session_columns
from factory.data_contract.storage import manifest_path, read_dataset, write_dataset

QUICK = settings(max_examples=8, derandomize=True, deadline=None)
PRICE_RULES = (
    "nonempty",
    "columns",
    "timestamp_order",
    "finite",
    "positive",
    "nonnegative",
    "ohlc_bounds",
    "calendar",
    "fill_shape",
    "fill_history",
)
EVENT_RULES = ("nonempty", "columns", "availability_order", "symbol", "event_values")
RECORD_TESTS = {
    "entity_fields": "test_entity_fields_property",
    "session_interval": "test_session_interval_property",
    "split_interval": "test_split_interval_property",
    "manifest_content": "test_manifest_content_property",
    "session_derivation": "test_session_derivation_property",
    "activity": "test_activity_property",
}


def minute_frame(price=100.0):
    # The final ten actual slots of the 2024 Thanksgiving half-day.
    index = pd.date_range("2024-11-29T17:50:00Z", periods=10, freq="min", name="timestamp")
    prices = float(price) + np.arange(10, dtype=float)
    return pd.DataFrame(
        {
            **{c: prices.copy() for c in ("open", "high", "low", "close")},
            "volume": 10.0,
            "is_filled": False,
        },
        index=index,
    )


def validate_minutes(frame):
    return validate_price_bars(
        frame,
        dataset="property/SPY",
        frequency="1min",
        start="2024-11-29",
        through="2024-11-29",
    )


def event_frame(score=1.0):
    return pd.DataFrame(
        {
            "available_at": pd.to_datetime(["2024-11-29T14:30Z", "2024-11-29T14:31Z"]),
            "symbol": pd.Series(["SPY", "BRK.B"], dtype="string"),
            "score": [float(score), float(score)],
        }
    )


def test_declared_invariants_have_executable_property_cases():
    # A newly declared rule must get a mutation case, not just a document entry.
    assert set(SPEC["datasets"]) == {"price_bars", "events"}
    assert {r["id"] for r in SPEC["datasets"]["price_bars"]["invariants"]} == set(PRICE_RULES)
    assert {r["id"] for r in SPEC["datasets"]["events"]["invariants"]} == set(EVENT_RULES)
    assert {r["id"] for r in SPEC["record_invariants"]} == set(RECORD_TESTS)
    assert all(callable(globals().get(name)) for name in RECORD_TESTS.values())
    assert set(SPEC["ontology"]) == {"Instrument", "Session", "Bar", "Dataset", "Split"}


@pytest.mark.parametrize("rule", PRICE_RULES)
@QUICK
@given(price=st.integers(1, 10000), row=st.integers(1, 9))
def test_price_invariant_property(rule, price, row):
    frame = minute_frame(price)
    validate_minutes(frame)
    if rule == "nonempty":
        frame = frame.iloc[:0]
    elif rule == "columns":
        frame = frame.drop(columns="is_filled")
    elif rule == "timestamp_order":
        stamps = frame.index.to_list()
        stamps[row] = stamps[row - 1]
        frame.index = pd.DatetimeIndex(stamps, name="timestamp")
    elif rule == "finite":
        frame.iloc[row, frame.columns.get_loc("close")] = np.inf
    elif rule == "positive":
        frame.iloc[row, frame.columns.get_loc("open")] = 0.0
    elif rule == "nonnegative":
        frame.iloc[row, frame.columns.get_loc("volume")] = -1.0
    elif rule == "ohlc_bounds":
        frame.iloc[row, frame.columns.get_loc("high")] = 0.5
    elif rule == "calendar":
        frame.index += pd.Timedelta(seconds=1)
    elif rule == "fill_shape":
        frame.iloc[row, frame.columns.get_loc("is_filled")] = True
    elif rule == "fill_history":
        # Flat OHLC/zero volume alone cannot prove a synthetic row's provenance.
        frame.iloc[row, frame.columns.get_loc("is_filled")] = True
        frame.iloc[row, frame.columns.get_loc("volume")] = 0.0
    with pytest.raises(DataError, match=rf"property/SPY.*rule={rule}[;.]"):
        validate_minutes(frame)


@pytest.mark.parametrize("rule", EVENT_RULES)
@QUICK
@given(score=st.integers(-10000, 10000), invalid=st.sampled_from([np.nan, np.inf, -np.inf]))
def test_event_invariant_property(rule, score, invalid):
    frame = event_frame(score)
    validate_events(frame, dataset="property/events")
    if rule == "nonempty":
        frame = frame.iloc[:0]
    elif rule == "columns":
        frame = frame.drop(columns="available_at")
    elif rule == "availability_order":
        frame = frame.iloc[::-1]
    elif rule == "symbol":
        frame.loc[0, "symbol"] = "../SPY"
    elif rule == "event_values":
        frame.loc[0, "score"] = invalid
    with pytest.raises(DataError, match=rf"property/events.*rule={rule}[;.]"):
        validate_events(frame, dataset="property/events")


@QUICK
@given(count=st.integers(1, 5), price=st.integers(1, 10000))
def test_fill_history_accepts_only_same_session_previous_close(count, price):
    frame = minute_frame(price)
    for column in ("open", "high", "low", "close"):
        frame.iloc[1 : count + 1, frame.columns.get_loc(column)] = float(price)
    frame.iloc[1 : count + 1, frame.columns.get_loc("volume")] = 0.0
    frame.iloc[1 : count + 1, frame.columns.get_loc("is_filled")] = True
    validate_minutes(frame)
    # A synthetic row cannot be the first retained observation of a session.
    with pytest.raises(DataError, match="fill_history"):
        validate_minutes(frame.iloc[1:])


@QUICK
@given(price=st.integers(1, 10000))
def test_fill_limit_and_daily_fill_prohibition(price):
    frame = minute_frame(price)
    for column in ("open", "high", "low", "close"):
        frame.iloc[1:7, frame.columns.get_loc(column)] = float(price)
    frame.iloc[1:7, frame.columns.get_loc("volume")] = 0.0
    frame.iloc[1:7, frame.columns.get_loc("is_filled")] = True
    with pytest.raises(DataError, match="fill_history"):
        validate_minutes(frame)
    daily = frame.iloc[:1].copy()
    daily.index = pd.DatetimeIndex(["2024-11-29T05:00Z"], name="timestamp")
    validate_price_bars(
        daily, dataset="daily", frequency="1day", start="2024-11-29", through="2024-11-29"
    )
    daily["volume"] = 0.0
    daily["is_filled"] = True
    with pytest.raises(DataError, match="fill_shape"):
        validate_price_bars(
            daily, dataset="daily", frequency="1day", start="2024-11-29", through="2024-11-29"
        )


@pytest.mark.parametrize("fault", ["nat", "naive", "extension_null", "extension_object"])
@QUICK
@given(score=st.integers(-100, 100))
def test_event_availability_and_scalar_extensions(fault, score):
    frame = event_frame(score)
    if fault == "nat":
        frame.loc[0, "available_at"] = pd.NaT
    elif fault == "naive":
        frame["available_at"] = frame.available_at.dt.tz_localize(None)
    elif fault == "extension_null":
        frame["label"] = pd.Series(["known", pd.NA], dtype="string")
    else:
        frame["object"] = [{"nested": "data"}, {"nested": "data"}]
    with pytest.raises(DataError, match="property/events.*row="):
        validate_events(frame, dataset="property/events")


def records():
    bar = minute_frame().iloc[0].to_dict() | {"timestamp": minute_frame().index[0]}
    return {
        "Instrument": dict(
            symbol="SPY",
            asset_class="etf",
            currency="USD",
            calendar="XNYS",
            timezone="America/New_York",
        ),
        "Bar": bar,
        "Session": dict(
            session_date=pd.Timestamp("2024-11-29", tz="America/New_York"),
            open=pd.Timestamp("2024-11-29T14:30Z"),
            close=pd.Timestamp("2024-11-29T18:00Z"),
            duration_minutes=210,
        ),
        "Split": dict(name="IS", start="2024-11-29T14:30Z", end="2024-11-29T17:59Z", fraction=0.6),
        "Dataset": dict(
            name="SPY",
            kind="price_bars",
            schema_version="1.0.0",
            source="test",
            feed="sip",
            adjustment="all",
            row_count=10,
            fill_rate=0.0,
            date_range={"start": "2024-11-29T17:50Z", "end": "2024-11-29T17:59Z"},
            created_at="2024-11-30T00:00Z",
            sha256="0" * 64,
            frequency="1min",
            start="2024-11-29",
            through="2024-11-29",
            calendar="XNYS",
            calendar_version="4.13.2",
        ),
    }


@pytest.mark.parametrize("entity", ["Instrument", "Session", "Bar", "Dataset", "Split"])
@QUICK
@given(choice=st.integers(0, 100))
def test_entity_fields_property(entity, choice):
    record = records()[entity]
    validate_entity(SPEC, entity, record, dataset="property/entity")
    field = list(record)[choice % len(record)]
    del record[field]
    with pytest.raises(DataError, match="property/entity.*entity_fields"):
        validate_entity(SPEC, entity, record, dataset="property/entity")


@QUICK
@given(delta=st.integers(1, 200), field=st.sampled_from(["open", "close", "duration_minutes"]))
def test_session_interval_property(delta, field):
    record = records()["Session"]
    validate_entity(SPEC, "Session", record, dataset="property/session")
    record[field] += delta if field == "duration_minutes" else pd.Timedelta(minutes=delta)
    with pytest.raises(DataError, match="session_interval"):
        validate_entity(SPEC, "Session", record, dataset="property/session")


@QUICK
@given(name=st.sampled_from(["IS", "OOS", "HOLDOUT"]), reversed_bounds=st.booleans())
def test_split_interval_property(name, reversed_bounds):
    record = records()["Split"] | {"name": name, "fraction": 0.6 if name == "IS" else 0.2}
    validate_entity(SPEC, "Split", record, dataset="property/split")
    if reversed_bounds:
        record["start"], record["end"] = record["end"], record["start"]
    else:
        record["fraction"] = 0.2 if name == "IS" else 0.6
    with pytest.raises(DataError, match="split_interval"):
        validate_entity(SPEC, "Split", record, dataset="property/split")


@pytest.mark.parametrize("fault", ["sha256", "row_count", "date_range", "fill_rate", "feed"])
@QUICK
@given(price=st.integers(1, 10000))
def test_manifest_content_property(fault, price):
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "SPY.parquet"
        frame = minute_frame(price)
        write_dataset(
            path,
            frame,
            kind="price_bars",
            frequency="1min",
            source="test",
            start="2024-11-29",
            through="2024-11-29",
            feed="sip",
            adjustment="all",
        )
        pd.testing.assert_frame_equal(read_dataset(path), frame, check_freq=False)
        sidecar = manifest_path(path)
        entry = json.loads(sidecar.read_text())
        entry[fault] = {
            "sha256": "0" * 64,
            "row_count": 11,
            "fill_rate": 0.5,
            "date_range": {"start": "2024-11-29T17:51Z", "end": "2024-11-29T17:59Z"},
            "feed": "user_supplied",
        }[fault]
        sidecar.write_text(json.dumps(entry))
        with pytest.raises(DataError, match=rf"manifest\.{fault}"):
            read_dataset(path)


@pytest.mark.parametrize("field", list(SPEC["ontology"]["Bar"]["derived_fields"]))
@QUICK
@given(row=st.integers(0, 9), remove=st.booleans())
def test_session_derivation_property(field, row, remove):
    frame = add_session_columns(minute_frame(), "1min")
    validate_session_columns(frame, "1min", "property/session")
    if remove:
        frame = frame.drop(columns=field)
    else:
        column = frame.columns.get_loc(field)
        value = frame.iloc[row, column]
        if field == "session_date":
            value += pd.Timedelta(days=1)
        elif field in ("is_first_bar", "is_last_bar"):
            value = not value
        else:
            value += 1
        frame.iloc[row, column] = value
    with pytest.raises(DataError, match="session_derivation"):
        validate_session_columns(frame, "1min", "property/session")


@pytest.mark.parametrize(
    "date,first,last,length",
    [
        ("2024-03-08", "14:30", "20:59", 390),
        ("2024-03-11", "13:30", "19:59", 390),
        ("2024-11-01", "13:30", "19:59", 390),
        ("2024-11-04", "14:30", "20:59", 390),
        ("2024-11-29", "14:30", "17:59", 210),
    ],
)
def test_session_calendar_facts_across_dst_and_half_day(date, first, last, length):
    index = pd.DatetimeIndex([f"{date}T{first}Z", f"{date}T{last}Z"], name="timestamp")
    bars = pd.DataFrame({c: 100.0 for c in ("open", "high", "low", "close", "volume")}, index=index)
    frame = add_session_columns(bars, "1min")
    assert frame.minutes_since_open.tolist() == [0, length - 1]
    assert frame.minutes_to_close.tolist() == [length, 1]
    assert frame.is_first_bar.tolist() == [True, False]
    assert frame.is_last_bar.tolist() == [False, True]
    middle = bars.iloc[:1].copy()
    middle.index += pd.Timedelta(minutes=20)
    sliced = add_session_columns(middle, "1min")
    assert not sliced.is_first_bar.any() and not sliced.is_last_bar.any()
    assert sliced.minutes_since_open.tolist() == [20]


@QUICK
@given(days=st.integers(0, 7), weight=st.sampled_from([-0.5, 0.25, 1.0]))
def test_activity_property(days, weight):
    from factory.contract import InactiveStrategy, validate_activity

    dates = pd.bdate_range("2024-11-18T14:30:00Z", periods=7)
    index = dates.append(dates + pd.Timedelta(minutes=1)).sort_values()
    weights = pd.DataFrame(0.0, index=index, columns=["SPY", "QQQ"])
    # Both bars carry the same target: activity counts days with held exposure,
    # including shorts, rather than counting turnover or individual bars.
    weights.iloc[: 2 * days, 0] = weight
    expected = {"active_bars": 2 * days, "total_bars": 14, "days_traded": days}
    if days < 5:
        with pytest.raises(InactiveStrategy) as error:
            validate_activity(weights)
        assert error.value.status == "INACTIVE"
        assert error.value.activity == expected
        assert str(error.value) == SPEC["activity"]["message"]
    else:
        assert validate_activity(weights) == expected


@pytest.mark.skipif(
    os.environ.get("ARENA_TEST_STORED_DATA") != "1",
    reason="Explicit opt-in for full trusted stored-data hygiene scan",
)
def test_all_stored_datasets_and_derived_sessions():
    root = Path(os.environ.get("ARENA_DATA_ROOT", Path(__file__).resolve().parents[1] / "data"))
    paths = sorted(root.rglob("*.parquet"))
    assert paths, f"No stored datasets found under {root}"
    for path in paths:
        frame = read_dataset(path)
        metadata = json.loads(manifest_path(path).read_text())
        if metadata["kind"] == "price_bars":
            frequency = metadata["frequency"]
            derived = add_session_columns(frame, frequency)
            validate_session_columns(derived, frequency, str(path))
            pd.testing.assert_frame_equal(derived.loc[:, frame.columns], frame)
