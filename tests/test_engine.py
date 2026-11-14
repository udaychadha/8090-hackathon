import math

import numpy as np
import pandas as pd
import pytest

from factory.engine import BacktestError, backtest, daily_compound, performance_metrics


def test_hand_computed_five_bar_lag_turnover_and_costs(five_bars):
    target = pd.DataFrame({"SPY": [1.0, -1.0, 0.5, 0.0, 1.0]}, index=five_bars["SPY"].index)
    result = backtest(five_bars, target, frequency="1day", round_trip_bps=10)
    np.testing.assert_allclose(result.executed.SPY, [0, 1, -1, 0.5, 0])
    np.testing.assert_allclose(result.asset_returns.SPY, [0, 0.1, -0.1, 0.2, -0.1])
    np.testing.assert_allclose(result.turnover, [0, 1, 2, 1.5, 0.5])
    np.testing.assert_allclose(result.costs, [0, 0.0005, 0.001, 0.00075, 0.00025])
    np.testing.assert_allclose(result.gross_bar_returns, [0, 0.1, 0.1, 0.1, 0])
    np.testing.assert_allclose(result.net_bar_returns, [0, 0.0995, 0.099, 0.09925, -0.00025])
    assert result.metrics.average_daily_turnover == pytest.approx(1.0)
    assert result.metrics.sharpe == pytest.approx(
        np.mean([0, 0.0995, 0.099, 0.09925, -0.00025])
        / np.std([0, 0.0995, 0.099, 0.09925, -0.00025], ddof=1)
        * math.sqrt(252)
    )
    assert "survivorship bias" in result.limitations[0]


def test_last_signal_cannot_change_current_or_earlier_pnl(five_bars):
    target = pd.DataFrame(0.0, index=five_bars["SPY"].index, columns=["SPY"])
    target.iloc[-1, 0] = 1
    result = backtest(five_bars, target, frequency="1day")
    assert (result.net_bar_returns == 0).all()
    assert (result.turnover == 0).all()


def test_intraday_compounds_to_daily_and_preserves_overnight_gap(five_bars):
    frame = five_bars["SPY"].copy()
    frame.index = pd.DatetimeIndex(
        [
            "2024-06-03T19:58Z",
            "2024-06-03T19:59Z",
            "2024-06-04T13:30Z",
            "2024-06-04T13:31Z",
            "2024-06-04T13:32Z",
        ]
    )
    close = [100, 102, 104.04, 103, 105]
    for field in ("open", "high", "low", "close"):
        frame[field] = close
    target = pd.DataFrame(1.0, index=frame.index, columns=["SPY"])
    result = backtest({"SPY": frame}, target, frequency="1min", round_trip_bps=0)
    np.testing.assert_allclose(result.daily_returns, [0.02, 105 / 102 - 1])
    assert result.asset_returns.SPY.iloc[2] == pytest.approx(0.02)
    assert result.metrics.trading_days == 2
    assert result.equity.iloc[-1] == pytest.approx(1.05)
    expected = np.array([0.02, 105 / 102 - 1])
    assert result.metrics.sharpe == pytest.approx(
        expected.mean() / expected.std(ddof=1) * math.sqrt(252)
    )


def test_daily_grouping_uses_new_york_date_and_no_weekend_padding():
    returns = pd.Series(
        [0.02, -0.01, 0.03],
        index=pd.DatetimeIndex(
            [
                "2024-06-07T20:00Z",
                "2024-06-08T00:30Z",
                "2024-06-10T20:00Z",
            ]
        ),
    )
    result = daily_compound(returns)
    np.testing.assert_allclose(result, [1.02 * 0.99 - 1, 0.03])
    assert result.index.strftime("%Y-%m-%d").tolist() == ["2024-06-07", "2024-06-10"]


def test_drawdown_includes_intraday_loss_even_when_recovered_by_close(five_bars):
    frame = five_bars["SPY"].iloc[:3].copy()
    frame.index = pd.date_range("2024-06-03T13:30Z", periods=3, freq="min")
    for field in ("open", "high", "low", "close"):
        frame[field] = [100, 80, 100]
    target = pd.DataFrame(1.0, index=frame.index, columns=["SPY"])
    result = backtest({"SPY": frame}, target, frequency="1min", round_trip_bps=0)
    assert result.daily_returns.iloc[0] == pytest.approx(0)
    assert result.metrics.max_drawdown == pytest.approx(-0.2)


def test_initial_loss_drawdown_annual_return_and_undefined_sharpe():
    daily = pd.Series([-0.1, 0.05])
    metrics = performance_metrics(daily, pd.Series([1, 0.5]))
    assert metrics.max_drawdown == pytest.approx(-0.1)
    assert metrics.total_return == pytest.approx(-0.055)
    assert metrics.annualized_return == pytest.approx(0.945**126 - 1)
    assert metrics.average_daily_turnover == 0.75
    assert performance_metrics(pd.Series([0.0, 0.0]), pd.Series([0, 0])).sharpe is None


def test_missing_price_for_exposure_is_not_silently_zeroed(five_bars):
    bars = {**five_bars, "QQQ": five_bars["SPY"].drop(five_bars["SPY"].index[2])}
    target = pd.DataFrame({"SPY": 0.0, "QQQ": 1.0}, index=bars["SPY"].index)
    with pytest.raises(BacktestError, match="Missing close-to-close price"):
        backtest(bars, target, frequency="1day")


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf")])
def test_invalid_cost_rejected(five_bars, cost):
    target = pd.DataFrame(0.0, index=five_bars["SPY"].index, columns=["SPY"])
    with pytest.raises(BacktestError, match="cost"):
        backtest(five_bars, target, frequency="1day", round_trip_bps=cost)
