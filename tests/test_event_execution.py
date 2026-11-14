import pandas as pd
import pytest
from pydantic import ValidationError

from factory.contract import ContractViolation, StrategySpec, parse_strategy
from factory.event_execution import decision_times, truncate_extra
from factory.sandbox import run_strategy


def bars_on(labels):
    index = pd.DatetimeIndex(labels, tz="America/New_York").tz_convert("UTC").as_unit("ns")
    index.name = "timestamp"
    return {
        "SPY": pd.DataFrame(
            {
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 10.0,
            },
            index=index,
        )
    }


def events(available="2024-06-05T13:30:00Z"):
    return {
        "trades": pd.DataFrame(
            {
                "available_at": pd.Series(pd.to_datetime([available], utc=True)),
                "symbol": pd.Series(["SPY"], dtype="string"),
                "transaction_date": pd.Series(pd.to_datetime(["2000-01-01"], utc=True)),
            }
        )
    }


def source(body, frequency="1day"):
    return f'''import pandas as pd
FREQUENCY = "{frequency}"
UNIVERSE = ["SPY"]
PARAMS = {{"weight": 0.5}}
EXTRA = ["trades"]
def generate_signals(bars, params, extra=None):
{body}
'''


def execute(tmp_path, code, bars, extra):
    path = tmp_path / "events.py"
    path.write_text(code)
    return run_strategy(path, bars, extra=extra)


def test_transaction_date_cannot_expose_disclosure_early(tmp_path, five_bars):
    code = source("""    index = bars["SPY"].index
    trades = extra["trades"]
    eligible = trades[trades.transaction_date <= index[-1]]
    weight = params["weight"] if len(eligible) else 0
    return pd.DataFrame(weight, index=index, columns=UNIVERSE)""")
    actual = execute(tmp_path, code, five_bars, events())
    assert actual.SPY.tolist() == [0, 0, 0.5, 0.5, 0.5]
    # Later invocations intentionally rewrite the entire historical output.
    # The execution gate must retain only each decision's final row.
    truncated = {name: frame.iloc[:2] for name, frame in five_bars.items()}
    earlier = execute(tmp_path, code, truncated, events())
    pd.testing.assert_frame_equal(earlier, actual.iloc[:2])


def test_daily_clocks_cover_dst_and_early_close_and_exclude_holidays():
    bars = bars_on(["2024-03-08", "2024-03-11", "2024-11-29"])
    assert decision_times(bars, "1day").tolist() == list(
        pd.to_datetime(
            [
                "2024-03-08T21:00:00Z",
                "2024-03-11T20:00:00Z",
                "2024-11-29T18:00:00Z",
            ]
        )
    )
    with pytest.raises(ContractViolation, match="scheduled"):
        decision_times(bars_on(["2024-11-28"]), "1day")


def test_intraday_uses_bar_end_inclusive_availability(tmp_path):
    bars = bars_on(["2024-06-03 09:30", "2024-06-03 09:31", "2024-06-03 09:32"])
    code = source(
        """    return pd.DataFrame(params["weight"] if len(extra["trades"]) else 0,
                        index=bars["SPY"].index, columns=UNIVERSE)""",
        "1min",
    )
    result = execute(tmp_path, code, bars, events("2024-06-03T13:32:00Z"))
    assert result.SPY.tolist() == [0, 0.5, 0.5]


def test_each_call_gets_prefix_bars_fresh_extra_and_no_metadata(tmp_path, five_bars):
    code = source("""    trades = extra["trades"]
    if trades.attrs or bars["SPY"].attrs:
        raise ValueError("metadata leaked")
    weight = params["weight"] if len(trades) else 0
    trades.loc[:, "symbol"] = "QQQ"
    if len(bars["SPY"]) > 1:
        weight = weight if bars["SPY"].index[-1] > bars["SPY"].index[0] else 0
    return pd.DataFrame(weight, index=bars["SPY"].index, columns=UNIVERSE)""")
    extra = events()
    extra["trades"].attrs["future"] = "must disappear"
    five_bars["SPY"].attrs["future"] = "must disappear"
    result = execute(tmp_path, code, five_bars, extra)
    assert result.SPY.tolist() == [0, 0, 0.5, 0.5, 0.5]
    assert extra["trades"].symbol.tolist() == ["SPY"]
    assert not truncate_extra(extra, pd.Timestamp("2000-01-01", tz="UTC"))["trades"].attrs


@pytest.mark.parametrize(
    "replacement",
    [
        'EXTRA = ["../trades"]',
        'EXTRA = ["trades", "trades"]',
        'EXTRA = "trades"',
        "EXTRA = list()",
    ],
)
def test_invalid_extra_declaration_rejected(replacement):
    with pytest.raises(ContractViolation, match="EXTRA"):
        parse_strategy(source("    return 0").replace('EXTRA = ["trades"]', replacement))


@pytest.mark.parametrize(
    "signature", ["bars, params", "bars, params, extra", "bars, params, extra={}"]
)
def test_event_signature_requires_optional_extra(signature):
    with pytest.raises(ContractViolation, match="generate_signals"):
        parse_strategy(source("    return 0").replace("bars, params, extra=None", signature))


def test_missing_or_malformed_event_data_rejected(tmp_path, five_bars):
    code = source('    return pd.DataFrame(0, index=bars["SPY"].index, columns=UNIVERSE)')
    with pytest.raises(ContractViolation, match="missing"):
        execute(tmp_path, code, five_bars, {})
    malformed = events()
    malformed["trades"]["available_at"] = "2024-06-03"
    with pytest.raises(ContractViolation, match="dtype"):
        execute(tmp_path, code, five_bars, malformed)
    empty = {name: frame.iloc[:0] for name, frame in events().items()}
    assert execute(tmp_path, code, five_bars, empty).eq(0).all().all()
    with pytest.raises(ContractViolation, match="dtype"):
        execute(tmp_path, code, five_bars, {"trades": malformed["trades"].iloc[:0]})


def test_event_session_fields_stay_read_only(tmp_path, five_bars):
    code = source("""    bars["SPY"]["minutes_to_close"] = 0
    return pd.DataFrame(0, index=bars["SPY"].index, columns=UNIVERSE)""")
    with pytest.raises(ContractViolation, match="read-only"):
        execute(tmp_path, code, five_bars, events())


def test_legacy_exact_weights_unchanged_with_unused_extra(tmp_path, five_bars, valid_source):
    path = tmp_path / "legacy.py"
    path.write_text(valid_source)
    before = run_strategy(path, five_bars)
    after = run_strategy(path, five_bars, extra=events())
    pd.testing.assert_frame_equal(before, after, check_exact=True)
    pd.testing.assert_frame_equal(
        before,
        pd.DataFrame(0.25, index=five_bars["SPY"].index, columns=["SPY"]),
        check_freq=False,
    )


def test_spec_extensions_preserve_historical_paper_validation():
    base = dict(
        paper_id="sample",
        title="Sample",
        category="event",
        hypothesis="Disclosures",
        universe=["SPY"],
        frequency="1day",
        signal_rules=["Buy disclosures"],
        claimed_metrics={},
        ambiguities=["Sizing"],
        test_type="transfer",
    )
    assert StrategySpec(**base).source_kind == "paper"
    assert StrategySpec(**base).extra == []
    with pytest.raises(ValidationError):
        StrategySpec(**{**base, "ambiguities": []})
    described = StrategySpec(
        **{
            **base,
            "source_kind": "described",
            "test_type": "original",
            "ambiguities": [],
            "extra": ["trades"],
        }
    )
    assert described.extra == ["trades"] and described.verification_eligible


def test_event_last_row_output_and_legacy_full_shape(tmp_path, five_bars, valid_source):
    code = source("""    return pd.DataFrame(params["weight"] if len(extra["trades"]) else 0,
                        index=bars["SPY"].index[-1:], columns=UNIVERSE)""")
    result = execute(tmp_path, code, five_bars, events())
    assert result.SPY.tolist() == [0, 0, 0.5, 0.5, 0.5]
    legacy = tmp_path / "legacy.py"
    legacy.write_text(valid_source.replace('bars["SPY"].index', 'bars["SPY"].index[-1:]'))
    with pytest.raises(ContractViolation, match="timestamp"):
        run_strategy(legacy, five_bars)
    with pytest.raises(ValueError, match="at most 60"):
        run_strategy(legacy, five_bars, timeout=600)
    path = tmp_path / "events.py"
    path.write_text(code)
    assert run_strategy(path, five_bars, extra=events(), timeout=600).equals(result)
    with pytest.raises(ValueError, match="at most 600"):
        run_strategy(path, five_bars, extra=events(), timeout=601)


@pytest.mark.parametrize(
    "access",
    [
        'bars["SPY"]',
        'bars.get("SPY")',
        'dict(bars)["SPY"]',
        'bars.copy()["SPY"]',
        "list(bars.values())[0]",
        "list(bars.items())[0][1]",
    ],
)
def test_lazy_bars_materialize_causal_real_frames_for_dict_operations(tmp_path, five_bars, access):
    code = source(f"""    frame = {access}
    return pd.DataFrame(params["weight"], index=frame.index[-1:], columns=UNIVERSE)""")
    assert execute(tmp_path, code, five_bars, events()).eq(0.5).all().all()


@pytest.mark.parametrize(
    "mutation",
    [
        'bars["SPY"]["minutes_to_close"] = 0',
        'list(bars.values())[0]["minutes_to_close"] = 0',
        'bars.update({"SPY": bars["SPY"].drop(columns=["minutes_to_close"])})',
        'del bars["SPY"]',
    ],
)
def test_lazy_bars_protect_fields_across_access_and_replacement(tmp_path, five_bars, mutation):
    code = source(f"""    index = bars["SPY"].index[-1:]
    {mutation}
    return pd.DataFrame(0, index=index, columns=UNIVERSE)""")
    with pytest.raises(ContractViolation, match="read-only"):
        execute(tmp_path, code, five_bars, events())


def test_session_age_crosses_holiday_weekend_and_pre_slice_history(tmp_path):
    extra = events("2024-11-27T14:30:00Z")
    # Thanksgiving is closed; Friday is an early close; Monday is age two.
    bars = bars_on(["2024-12-02", "2024-12-03"])
    code = source("""    ages = extra["trades"].sessions_since_available
    weight = 1 / (1 + ages.iloc[-1])
    return pd.DataFrame(weight, index=bars["SPY"].index[-1:], columns=UNIVERSE)""")
    result = execute(tmp_path, code, bars, extra)
    assert result.SPY.tolist() == [1 / 3, 1 / 4]
    # A post-close Friday observation first belongs to Monday, not Friday.
    post_close = events("2024-11-29T18:01:00Z")
    visible = truncate_extra(post_close, pd.Timestamp("2024-12-02T21:00:00Z"))
    assert visible["trades"].sessions_since_available.tolist() == [0]
    assert str(visible["trades"].sessions_since_available.dtype) == "int64"


def test_derived_session_age_is_read_only(tmp_path, five_bars):
    code = source("""    extra["trades"]["sessions_since_available"] = 0
    return pd.DataFrame(0, index=bars["SPY"].index[-1:], columns=UNIVERSE)""")
    with pytest.raises(ContractViolation, match="sessions_since_available is read-only"):
        execute(tmp_path, code, five_bars, events("2024-06-03T13:30:00Z"))


def test_extra_staging_excludes_after_final_decision(tmp_path, five_bars, monkeypatch):
    from factory import sandbox

    original = sandbox.subprocess.Popen
    observed = {}

    def inspect_staged(*args, **kwargs):
        frame = pd.read_parquet(kwargs["cwd"] / "extra-trades.parquet")
        observed["rows"] = len(frame)
        return original(*args, **kwargs)

    monkeypatch.setattr(sandbox.subprocess, "Popen", inspect_staged)
    code = source('    return pd.DataFrame(0, index=bars["SPY"].index[-1:], columns=UNIVERSE)')
    execute(tmp_path, code, five_bars, events("2024-06-10T13:30:00Z"))
    assert observed["rows"] == 0


def test_native_dict_update_cannot_bypass_lazy_protection(tmp_path, five_bars):
    code = source("""    dict.update(bars, {"SPY": pd.DataFrame()})
    return pd.DataFrame(0, index=[pd.Timestamp("2024-06-03T04:00:00Z")], columns=UNIVERSE)""")
    with pytest.raises(ContractViolation, match="read-only"):
        execute(tmp_path, code, five_bars, events())


def test_event_bars_keep_late_and_absent_symbols_without_filling(tmp_path, five_bars):
    from factory.contract import validate_bars
    from factory.data import EventBars
    from factory.engine import BacktestError, backtest
    from factory.evals.lookahead import truncate_bars

    bars = EventBars(
        {
            "SPY": five_bars["SPY"],
            "QQQ": five_bars["SPY"].iloc[2:].copy(),
            "LATE": five_bars["SPY"].iloc[:0].copy(),
        }
    )
    assert validate_bars(bars).equals(five_bars["SPY"].index)
    with pytest.raises(ContractViolation, match="nonempty"):
        validate_bars(dict(bars))
    with pytest.raises(ContractViolation, match="observed timestamp"):
        validate_bars(EventBars({"SPY": five_bars["SPY"].iloc[:0]}))
    cut = truncate_bars(bars, five_bars["SPY"].index[0])
    assert isinstance(cut, EventBars)
    assert set(cut) == {"SPY", "QQQ", "LATE"}
    assert cut["QQQ"].empty and cut["LATE"].empty
    code = source("""    weight = params["weight"] if len(bars["QQQ"]) else 0
    return pd.DataFrame({"SPY": 0, "QQQ": weight, "LATE": 0},
                        index=bars["SPY"].index[-1:])""").replace(
        'UNIVERSE = ["SPY"]', 'UNIVERSE = ["SPY", "QQQ", "LATE"]'
    )
    weights = execute(tmp_path, code, bars, events())
    assert weights.QQQ.tolist() == [0, 0, 0.5, 0.5, 0.5]
    assert weights.LATE.eq(0).all()
    result = backtest(bars, weights, frequency="1day")
    assert result.executed.QQQ.tolist() == [0, 0, 0, 0.5, 0.5]
    # A later gap under held exposure remains a hard accounting error.
    gapped = EventBars(bars)
    gapped["QQQ"] = gapped["QQQ"].drop(index=weights.index[3])
    with pytest.raises(BacktestError, match="Missing close-to-close"):
        backtest(gapped, weights, frequency="1day")
    invalid = code.replace('params["weight"] if len(bars["QQQ"]) else 0', 'params["weight"]')
    with pytest.raises(ContractViolation, match="zero before its first observed"):
        execute(tmp_path, invalid, bars, events())


def test_event_loader_retains_validated_empty_symbols_and_typed_session_columns(tmp_path):
    import json

    from factory.data import DataError, EventBars, expected_index, load_bars, split_boundaries
    from factory.data_contract.sessions import validate_session_columns
    from factory.data_contract.storage import write_dataset

    index = expected_index("1day", "2024-06-03", "2024-06-14")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 10.0,
            "is_filled": False,
        },
        index=index,
    )
    tier = tmp_path / "1day"
    for symbol, data in {"SPY": frame, "LATE": frame.iloc[7:]}.items():
        write_dataset(
            tier / f"{symbol}.parquet",
            data,
            kind="price_bars",
            frequency="1day",
            start="2024-06-03",
            through="2024-06-14",
            source="fixture",
            feed="sip",
            adjustment="all",
        )
    (tier / "manifest.json").write_text(
        json.dumps(
            {
                "frequency": "1day",
                "start": "2024-06-03",
                "through": "2024-06-14",
                "feed": "sip",
                "adjustment": "all",
                "symbols": ["SPY", "LATE"],
                "complete": True,
                "splits": split_boundaries(index),
            }
        )
    )
    with pytest.raises(DataError, match="No IS data for LATE"):
        load_bars(tmp_path, "1day", ["SPY", "LATE"], split="IS")
    loaded = load_bars(tmp_path, "1day", ["SPY", "LATE"], split="IS", allow_empty_symbols=True)
    assert isinstance(loaded, EventBars) and loaded["LATE"].empty
    validate_session_columns(loaded["LATE"], "1day", "LATE")
    assert loaded["LATE"].close.dtype == frame.close.dtype
    with pytest.raises(DataError, match="any requested symbol"):
        load_bars(tmp_path, "1day", ["LATE"], split="IS", allow_empty_symbols=True)
    # Corrupting even an unseen physical row must fail normal storage validation.
    path = tier / "LATE.parquet"
    broken = pd.read_parquet(path)
    broken.iloc[0, broken.columns.get_loc("close")] = -1
    broken.to_parquet(path)
    with pytest.raises(DataError):
        load_bars(tmp_path, "1day", ["SPY", "LATE"], split="IS", allow_empty_symbols=True)


def test_event_lookahead_keeps_symbols_absent_before_cuts(tmp_path):
    from factory.data import EventBars, expected_index
    from factory.evals.lookahead import lookahead_eval

    index = expected_index("1day", "2024-06-03", "2024-06-14")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 10.0,
        },
        index=index,
    )
    bars = EventBars({"SPY": frame, "QQQ": frame.iloc[7:].copy()})
    code = source("""    weight = params["weight"] if len(bars["QQQ"]) else 0
    return pd.DataFrame({"SPY": 0, "QQQ": weight}, index=bars["SPY"].index[-1:])""").replace(
        'UNIVERSE = ["SPY"]', 'UNIVERSE = ["SPY", "QQQ"]'
    )
    path = tmp_path / "late.py"
    path.write_text(code)
    result, weights = lookahead_eval(
        lambda data, params: run_strategy(path, data, extra=events()), bars
    )
    assert result.passed and weights.QQQ.iloc[:7].eq(0).all()
    assert weights.QQQ.iloc[7:].eq(0.5).all()


def test_extra_names_match_upload_contract():
    from factory.contract import validate_extra_names

    assert validate_extra_names(["A" * 128]) == ("A" * 128,)
    for invalid in ["A" * 129, "has-hyphen", "1starts_digit"]:
        with pytest.raises(ContractViolation):
            validate_extra_names([invalid])
