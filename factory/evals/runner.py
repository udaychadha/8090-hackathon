"""Trusted harness glue: bind a strategy file to the sandbox and run the evals."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from factory.evals.common import StrategyRunner
from factory.sandbox import run_strategy


def sandbox_runner(path: str | Path, *, timeout: float = 60.0) -> StrategyRunner:
    def run(bars: dict[str, pd.DataFrame], params: dict | None = None) -> pd.DataFrame:
        return run_strategy(path, bars, params=params, timeout=timeout)

    return run
