"""Fixture: thresholded minute momentum on SPY/QQQ. Used to time a five-eval pass."""

import numpy as np
import pandas as pd

FREQUENCY = "1min"
UNIVERSE = ["SPY", "QQQ"]
PARAMS = {"lookback": 30, "entry": 0.002, "weight": 0.5}


def generate_signals(bars, params):
    close = pd.concat({symbol: bars[symbol].close for symbol in UNIVERSE}, axis=1)
    momentum = close / close.shift(params["lookback"]) - 1
    signal = np.sign(momentum).where(momentum.abs() > params["entry"], 0.0)
    return (signal * params["weight"]).fillna(0.0)
