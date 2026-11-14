import json

import numpy as np
import pandas as pd
import pytest

from factory.data import (
    INTRADAY_UNIVERSE,
    OHLCV,
    DataError,
    clean_bars,
    expected_index,
    load_bars,
    normalize_bars,
    split_boundaries,
)
from factory.ingest_alpaca import AlpacaBars, ingest_symbol


def bars(index, prices=None):
    prices = np.asarray(prices if prices is not None else np.full(len(index), 100.0))
    return pd.DataFrame({**{c: prices for c in OHLCV[:4]}, "volume": 10.0}, index=index)


def test_intraday_universe_is_exactly_fifty_unique_symbols():
    assert len(INTRADAY_UNIVERSE) == len(set(INTRADAY_UNIVERSE)) == 50


def test_fill_limit_flat_ohlc_and_no_session_carry():
    expected = expected_index("1min", "2024-06-06", "2024-06-07")
    source = bars(expected[[0, 7, 389, 392]], [100, 107, 110, 120])
    clean, stats = clean_bars(source, "1min", "2024-06-06", "2024-06-07")
    assert (clean.loc[expected[1:6], OHLCV[:4]] == 100).all().all()
    assert (clean.loc[expected[1:6], "volume"] == 0).all()
    assert expected[6] not in clean.index  # sixth missing minute remains absent
    assert expected[390] not in clean.index  # next session cannot inherit yesterday
    assert expected[391] not in clean.index
    assert stats["filled_rows"] == 15
    assert stats["fill_rate"] == 15 / 780
    assert stats["missing_rows"] == 761


def test_holiday_half_day_dst_and_regular_hours():
    expected = expected_index("1min", "2024-11-27", "2024-11-29")
    assert len(expected) == 390 + 210
    assert expected[-1] == pd.Timestamp("2024-11-29T17:59:00Z")
    source = bars(expected.append(pd.DatetimeIndex(["2024-11-29T18:00:00Z"])))
    clean, stats = clean_bars(source, "1min", "2024-11-27", "2024-11-29")
    assert len(clean) == 600
    assert stats["off_session_rows"] == 1
    march = expected_index("1min", "2024-03-08", "2024-03-11")
    assert march[0].hour == 14 and march[390].hour == 13
    assert expected_index("1min", "2024-06-08", "2024-06-09").empty


def test_daily_does_not_fill_missing_prices():
    expected = expected_index("1day", "2024-06-03", "2024-06-07")
    clean, stats = clean_bars(bars(expected[[0, 2]]), "1day", "2024-06-03", "2024-06-07")
    assert len(clean) == 2 and stats["filled_rows"] == 0 and stats["missing_rows"] == 3


def test_conflicting_duplicates_rejected():
    index = pd.DatetimeIndex(["2024-06-03T13:30Z", "2024-06-03T13:30Z"])
    with pytest.raises(DataError, match="Conflicting duplicate"):
        normalize_bars(bars(index, [100, 101]))


def test_loader_partition_pushdown_and_holdout_guard(tmp_path):
    index = expected_index("1day", "2024-06-03", "2024-06-14")
    tier = tmp_path / "1day"
    tier.mkdir()
    bars(index).to_parquet(tier / "SPY.parquet")
    splits = split_boundaries(index)
    (tier / "manifest.json").write_text(
        json.dumps(
            {
                "symbols": ["SPY"],
                "splits": splits,
                "complete": True,
            }
        )
    )
    assert len(load_bars(tmp_path, "1day", ["SPY"], split="IS")["SPY"]) == 6
    assert len(load_bars(tmp_path, "1day", ["SPY"], split="OOS")["SPY"]) == 2
    with pytest.raises(DataError, match="sealed"):
        load_bars(tmp_path, "1day", ["SPY"], split="HOLDOUT")
    assert (
        len(load_bars(tmp_path, "1day", ["SPY"], split="HOLDOUT", allow_holdout=True)["SPY"]) == 2
    )
    with pytest.raises(DataError, match="symbol"):
        load_bars(tmp_path, "1day", ["../secret"], split="IS")


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.headers = payload, status, {}

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls, self.headers = [], {}

    def get(self, url, **kwargs):
        self.calls.append((url, {**kwargs, "params": dict(kwargs["params"])}))
        return next(self.responses)


def test_pagination_retry_adjustments_and_share_class_format():
    row = {"t": "2024-06-07T04:00:00Z", "o": 120, "h": 121, "l": 119, "c": 120, "v": 10}
    session = FakeSession(
        [
            FakeResponse({}, 429),
            FakeResponse({"bars": {"BRK.B": [row]}, "next_page_token": "next"}),
            FakeResponse(
                {"bars": {"BRK.B": [{**row, "t": "2024-06-10T04:00:00Z"}]}, "next_page_token": None}
            ),
        ]
    )
    sleeps = []
    client = AlpacaBars(
        "test-key", "test-secret", session=session, sleep=sleeps.append, clock=lambda: 0
    )
    result = client.fetch("BRK.B", "1day", "2024-06-07", "2024-06-10")
    assert len(result) == 2
    params = session.calls[-1][1]["params"]
    assert params["page_token"] == "next"
    assert params["feed"] == "sip" and params["adjustment"] == "all"
    assert params["symbols"] == "BRK.B" and params["limit"] == 10000
    assert params["timeframe"] == "1Day"
    assert max(sleeps) >= 1


def test_repeated_page_token_fails_instead_of_looping():
    session = FakeSession([FakeResponse({"bars": {}, "next_page_token": "same"})] * 2)
    client = AlpacaBars("x", "y", session=session, sleep=lambda _: None, clock=lambda: 0)
    with pytest.raises(DataError, match="repeated"):
        client.fetch("SPY", "1day", "2024-06-03", "2024-06-07")


def test_ingestion_writes_parquet_and_resumes_without_requesting_again(tmp_path):
    class Client:
        calls = 0

        def fetch(self, symbol, frequency, start, through):
            self.calls += 1
            return bars(expected_index(frequency, start, through))

    client = Client()
    first = ingest_symbol(client, tmp_path, "1day", "SPY", "2024-06-03", "2024-06-07")
    second = ingest_symbol(client, tmp_path, "1day", "SPY", "2024-06-03", "2024-06-07")
    assert first == second and client.calls == 1
    assert len(pd.read_parquet(tmp_path / "1day" / "SPY.parquet")) == 5
    assert first["fill_rate"] == 0
