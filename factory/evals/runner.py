"""Trusted harness glue: bind a strategy file to the sandbox and run the five evals.

Only this side of the sandbox ever holds OOS bars. Bug-class failures
(LookaheadBiasError, ContractViolation, StrategyExecutionError) on the
strategy's own parameters propagate to the caller, which owns self-heal.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd

from factory.contract import read_strategy
from factory.data import load_bars
from factory.engine import backtest
from factory.evals import config
from factory.evals.common import EvalError, EvalResult, StrategyRunner, daily_sharpe
from factory.evals.decay import decay_eval
from factory.evals.deflated import deflated_eval
from factory.evals.friction import friction_eval
from factory.evals.lookahead import LookaheadBiasError, lookahead_eval
from factory.evals.sensitivity import sensitivity_eval
from factory.sandbox import run_strategy


def sandbox_runner(path: str | Path, *, timeout: float = 60.0, extra=None) -> StrategyRunner:
    def run(bars: dict[str, pd.DataFrame], params: dict | None = None) -> pd.DataFrame:
        options = {"extra": extra} if extra is not None else {}
        return run_strategy(path, bars, params=params, timeout=timeout, **options)

    return run


@dataclass(frozen=True)
class EvalReport:
    results: dict[int, EvalResult]
    seconds: dict[str, float]
    oos_daily_returns: pd.Series = field(repr=False)
    oos_daily_sharpe: float | None  # this variant's entry in the Eval 5 trial set

    @property
    def status(self) -> str:
        for number in sorted(self.results):
            if not self.results[number].passed:
                return f"FAILED_EVAL_{number}"
        return "VERIFIED" if len(self.results) == 5 else "INCOMPLETE"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "evals": [self.results[number].to_dict() for number in sorted(self.results)],
            "seconds": self.seconds,
            "oos_daily_sharpe": self.oos_daily_sharpe,
        }


def with_deflated(
    report: EvalReport,
    trial_sharpes: Sequence[float | None],
    *,
    trial_variant_ids: Sequence[str] | None = None,
) -> EvalReport:
    """(Re)score Eval 5 against the complete retained trial cohort."""
    started = time.perf_counter()
    result = deflated_eval(
        report.oos_daily_returns, trial_sharpes, trial_variant_ids=trial_variant_ids
    )
    seconds = {**report.seconds, "eval_5": time.perf_counter() - started}
    seconds["total"] = sum(value for key, value in seconds.items() if key != "total")
    return replace(report, results={**report.results, 5: result}, seconds=seconds)


def evaluate(
    run: StrategyRunner,
    params: dict,
    frequency: str,
    is_bars: dict[str, pd.DataFrame],
    oos_bars: dict[str, pd.DataFrame],
    *,
    trial_sharpes: Sequence[float | None] | None = None,
    on_eval2_started: Callable[[], None] | None = None,
) -> EvalReport:
    """Run Evals 1–5. Later evals still run after a failure, for the tearsheet.

    OOS weights come from one run over IS followed by OOS bars, so indicators
    are warm at the first OOS bar; only the OOS portion is scored.
    """
    results, seconds = {}, {}
    clock = time.perf_counter()

    def lap(name):
        nonlocal clock
        now = time.perf_counter()
        seconds[name], clock = now - clock, now

    results[1], is_weights = lookahead_eval(run, is_bars)
    lap("eval_1")
    if on_eval2_started is not None:
        on_eval2_started()
    results[2] = friction_eval(is_bars, is_weights, frequency)
    lap("eval_2")
    is_base = backtest(
        is_bars, is_weights, frequency=frequency, round_trip_bps=config.BASE_COST_BPS
    )
    results[3] = sensitivity_eval(run, is_bars, params, frequency, is_base.metrics.sharpe)
    lap("eval_3")
    joined = type(is_bars)()
    for symbol, frame in is_bars.items():
        if (
            not frame.empty
            and not oos_bars[symbol].empty
            and not frame.index[-1] < oos_bars[symbol].index[0]
        ):
            raise EvalError(f"{symbol}: OOS bars must start after IS bars end")
        joined[symbol] = pd.concat([frame, oos_bars[symbol]])
    oos_weights = run(joined, None).loc[lambda weights: weights.index > is_weights.index[-1]]
    oos_base = backtest(
        oos_bars, oos_weights, frequency=frequency, round_trip_bps=config.BASE_COST_BPS
    )
    results[4] = decay_eval(is_base.daily_returns, oos_base.daily_returns)
    lap("eval_4")
    own = daily_sharpe(oos_base.daily_returns)
    report = EvalReport(results, seconds, oos_base.daily_returns, own)
    return with_deflated(report, [own] if trial_sharpes is None else trial_sharpes)


def evaluate_file(
    path: str | Path,
    data_root: str | Path = "data",
    *,
    trial_sharpes: Sequence[float | None] | None = None,
    on_eval2_started: Callable[[], None] | None = None,
    timeout: float | None = None,
) -> EvalReport:
    """Load the strategy's tier (IS and OOS only; HOLDOUT stays sealed) and evaluate."""
    definition = read_strategy(path)
    timeout = (600 if definition.extra else 60) if timeout is None else timeout
    symbols = list(definition.universe)
    options = {"allow_empty_symbols": True} if definition.extra else {}
    is_bars = load_bars(data_root, definition.frequency, symbols, split="IS", **options)
    oos_bars = load_bars(data_root, definition.frequency, symbols, split="OOS", **options)
    extra = None
    if definition.extra:
        from factory.event_execution import decision_times
        from factory.events import load_extra

        extra = load_extra(
            data_root, definition.extra, as_of=decision_times(oos_bars, definition.frequency).max()
        )
    return evaluate(
        sandbox_runner(path, timeout=timeout, extra=extra),
        definition.params,
        definition.frequency,
        is_bars,
        oos_bars,
        trial_sharpes=trial_sharpes,
        on_eval2_started=on_eval2_started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the five strategy evals on one file")
    parser.add_argument("strategy")
    parser.add_argument("--data", default="data")
    parser.add_argument(
        "--trial-sharpes",
        type=float,
        nargs="*",
        help="per-day OOS Sharpes of all other variants that reached Eval 2",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        report = evaluate_file(args.strategy, args.data)
        if args.trial_sharpes:
            report = with_deflated(report, [report.oos_daily_sharpe, *args.trial_sharpes])
        output = report.to_dict()
    except LookaheadBiasError as error:
        output = {"status": "BUG", "eval": 1, "error": str(error)}
    output["wall_seconds"] = time.perf_counter() - started
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
