"""Fixture: volatility-scaled trend following on four ETFs. Parameters are untuned."""

import numpy as np
import pandas as pd

FREQUENCY = "1day"
UNIVERSE = ["SPY", "QQQ", "TLT", "GLD"]
PARAMS = {"lookback": 126, "vol_window": 20}


def generate_signals(bars, params):
    close = pd.concat({symbol: bars[symbol].close for symbol in UNIVERSE}, axis=1)
    returns = close.pct_change(fill_method=None)
    trend = np.sign(close / close.shift(params["lookback"]) - 1)
    vol = returns.rolling(params["vol_window"]).std()
    raw = (trend / vol).replace([np.inf, -np.inf], np.nan)
    gross = raw.abs().sum(axis=1)
    weights = raw.div(gross.where(gross > 0), axis=0)
    return weights.fillna(0.0)
