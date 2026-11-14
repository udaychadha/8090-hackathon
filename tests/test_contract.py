import pandas as pd
import pytest
from pydantic import ValidationError

from factory.contract import (
    ContractViolation,
    StrategySpec,
    parse_strategy,
    validate_bars,
    validate_params,
    validate_weights,
)


@pytest.mark.parametrize("weight", [-1.01, 1.01, float("nan"), float("inf")])
def test_out_of_range_or_nonfinite_weights_are_rejected(five_bars, weight):
    index = five_bars["SPY"].index
    with pytest.raises(ContractViolation, match="SPY"):
        validate_weights(pd.DataFrame(weight, index=index, columns=["SPY"]), index, ["SPY"])


def test_gross_exposure_is_absolute_not_net(five_bars):
    index = five_bars["SPY"].index
    with pytest.raises(ContractViolation, match="Gross exposure"):
        validate_weights(
            pd.DataFrame({"SPY": 0.6, "QQQ": -0.6}, index=index), index, ["SPY", "QQQ"]
        )


def test_wrong_timestamp_or_column_fails(five_bars):
    index = five_bars["SPY"].index
    with pytest.raises(ContractViolation, match="timestamp"):
        validate_weights(pd.DataFrame(0, index=index[:-1], columns=["SPY"]), index, ["SPY"])
    with pytest.raises(ContractViolation, match="columns"):
        validate_weights(pd.DataFrame(0, index=index, columns=["QQQ"]), index, ["SPY"])


def test_source_metadata_and_tunable_numbers(valid_source):
    result = parse_strategy(valid_source, available_universe=["SPY", "QQQ"])
    assert result.frequency == "1day" and result.params == {"weight": 0.25}
    with pytest.raises(ContractViolation, match="numeric literal"):
        parse_strategy(valid_source.replace('params["weight"]', "0.25"))
    with pytest.raises(ContractViolation, match="subset"):
        parse_strategy(valid_source, available_universe=["QQQ"])
    with pytest.raises(ContractViolation, match="unique"):
        parse_strategy(valid_source.replace('["SPY"]\n', '["SPY", "SPY"]\n'))


@pytest.mark.parametrize(
    "bad_code",
    [
        "import os\n",
        "import requests\n",
        "import random\n",
        "from pandas import read_csv\n",
        "print('hello')\n",
    ],
)
def test_forbidden_module_code(valid_source, bad_code):
    with pytest.raises(ContractViolation):
        parse_strategy(bad_code + valid_source)


@pytest.mark.parametrize(
    "expression",
    [
        "open('somewhere')",
        "pd.read_csv('somewhere')",
        "pd.Timestamp.now()",
        "pd.Timestamp('now')",
        "getattr(pd, 'read_csv')('somewhere')",
        "pd.DataFrame.__subclasses__()",
        "pd.eval('1')",
    ],
)
def test_io_wall_clock_and_reflection_fail_source_policy(valid_source, expression):
    source = valid_source[: valid_source.index("    return")] + "    return " + expression
    with pytest.raises(ContractViolation):
        parse_strategy(source)


def test_unseeded_rng_rejected_and_seeded_rng_allowed(valid_source):
    source = "import numpy as np\n" + valid_source
    source = source.replace('PARAMS = {"weight": 0.25}', 'PARAMS = {"weight": 0.25, "seed": 7}')
    source = source.replace(
        "    return", "    rng = np.random.default_rng(params['seed'])\n    return"
    )
    parse_strategy(source)
    with pytest.raises(ContractViolation, match="seed"):
        parse_strategy(source.replace("params['seed']", ""))


def test_metadata_parse_does_not_execute_and_lookahead_is_left_to_eval_one(valid_source):
    source = valid_source.replace('params["weight"]', 'bars["SPY"].close.shift(-1)')
    assert parse_strategy(source).universe == ("SPY",)


def test_parameter_overrides_keep_keys_and_types():
    assert validate_params({"lookback": 11}, {"lookback": 10}) == {"lookback": 11}
    with pytest.raises(ContractViolation, match="type"):
        validate_params({"lookback": 10.5}, {"lookback": 10})
    with pytest.raises(ContractViolation, match="key"):
        validate_params({"other": 10}, {"lookback": 10})


def test_bars_require_utc_unique_timestamps(five_bars):
    frame = five_bars["SPY"].copy()
    frame.index = frame.index.tz_convert("America/New_York")
    with pytest.raises(ContractViolation, match="UTC"):
        validate_bars({"SPY": frame})


def test_extractor_schema_requires_ambiguities_and_test_type():
    spec = dict(
        paper_id="sample",
        title="Sample",
        category="momentum",
        hypothesis="Trend persists",
        universe=["SPY"],
        frequency="1day",
        signal_rules=["Follow yesterday's trend"],
        claimed_metrics={"sharpe": None},
        ambiguities=["Costs not specified"],
        test_type="transfer",
    )
    assert StrategySpec(**spec).test_type == "transfer"
    with pytest.raises(ValidationError):
        StrategySpec(**{**spec, "ambiguities": []})
    with pytest.raises(ValidationError):
        StrategySpec(**{key: value for key, value in spec.items() if key != "test_type"})
