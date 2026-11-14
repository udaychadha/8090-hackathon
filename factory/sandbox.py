"""Subprocess crash isolation, not a security boundary.

Only caller-supplied bars are staged. No data-root path or provider credentials
are sent to generated code. A temporary cwd does NOT restrict OS file access.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

from factory.contract import (
    ContractViolation,
    read_strategy,
    validate_bars,
    validate_params,
    validate_weights,
)
from factory.data import EventBars
from factory.data_contract import DataError
from factory.data_contract.sessions import (
    add_session_columns,
    protected_session_columns,
    validate_session_columns,
)


class StrategyExecutionError(RuntimeError):
    """A bug in generated code, with the child traceback for self-heal."""

    def __init__(self, message: str, *, remote_traceback: str = ""):
        super().__init__(message)
        self.remote_traceback = remote_traceback


class StrategyTimeoutError(StrategyExecutionError):
    pass


def run_strategy(
    path: str | Path,
    bars: dict[str, pd.DataFrame],
    *,
    params: dict | None = None,
    extra: dict[str, pd.DataFrame] | None = None,
    timeout: float = 60.0,
) -> pd.DataFrame:
    """Validate, run twice to detect nondeterminism, return validated weights.

    The 60-second default covers child startup and both calls. Later lookahead
    evals must still compare truncated inputs; determinism alone proves no
    absence of lookahead. Event strategies execute at every decision and may
    explicitly request up to 600 seconds; legacy strategies retain the 60s cap.
    """
    definition = read_strategy(path, available_universe=list(bars))
    maximum = 600 if definition.extra else 60
    if not 0 < timeout <= maximum:
        raise ValueError(f"timeout must be greater than zero and at most {maximum} seconds")
    selected = {symbol: bars[symbol] for symbol in definition.universe}
    if definition.extra:
        selected = EventBars(selected)
    index = validate_bars(selected)
    try:
        for symbol, frame in selected.items():
            if set(protected_session_columns()) & set(frame.columns):
                validate_session_columns(frame, definition.frequency, symbol)
            else:
                selected[symbol] = add_session_columns(frame, definition.frequency)
    except DataError as error:
        raise ContractViolation(str(error)) from error
    staged_extra = {}
    if definition.extra:
        from factory.event_execution import decision_times, truncate_extra, validate_extra

        validated_extra = validate_extra(extra, definition.extra)
        staged_extra = truncate_extra(
            validated_extra, decision_times(selected, definition.frequency).max()
        )
    parameters = validate_params(definition.params if params is None else params, definition.params)
    with tempfile.TemporaryDirectory(prefix="arena-strategy-") as directory:
        cwd = Path(directory)
        (cwd / "strategy.py").write_text(definition.source)
        for symbol, frame in selected.items():
            frame.to_parquet(cwd / f"{symbol}.parquet", index=True)
        for name, frame in staged_extra.items():
            frame.to_parquet(cwd / f"extra-{name}.parquet", index=False)
        (cwd / "request.json").write_text(
            json.dumps(
                {
                    "symbols": list(selected),
                    "params": parameters,
                    "extra": list(staged_extra),
                },
                allow_nan=False,
            )
        )
        # Start from an allowlist, not a copy of the parent's credential-bearing env.
        environment = {
            key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR") if key in os.environ
        }
        environment.update(
            PYTHONHASHSEED="0",
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            NUMEXPR_NUM_THREADS="1",
        )
        with (cwd / "stderr.log").open("w+") as stderr:
            process = subprocess.Popen(
                # -I also ignores PYTHONHASHSEED. Use safe-path/no-user-site
                # flags with our minimal environment so hash order stays fixed.
                [sys.executable, "-s", "-P", "-m", "factory._sandbox_child"],
                cwd=cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The child can exit between the timeout and kill.
                process.wait()
                raise StrategyTimeoutError(
                    f"Strategy exceeded {timeout:g}s wall-clock limit"
                ) from None
            result_path = cwd / "result.json"
            if not result_path.exists():
                stderr.seek(0)
                detail = stderr.read(8000)
                raise StrategyExecutionError(
                    f"Strategy child exited {process.returncode} without a result",
                    remote_traceback=detail,
                )
            result = json.loads(result_path.read_text())
        if not result.get("ok") or process.returncode:
            message = result.get("message", "Strategy failed")
            trace = result.get("traceback", "")
            if result.get("error_type") == "ContractViolation":
                error = ContractViolation(message)
                error.remote_traceback = trace
                raise error
            raise StrategyExecutionError(message, remote_traceback=trace)
        weights = pd.read_parquet(cwd / "weights.parquet")
        # Validate again in the trusted parent; child output is not authoritative.
        weights = validate_weights(weights, index, definition.universe)
        if definition.extra:
            from factory.event_execution import validate_observed_weights

            validate_observed_weights(weights, selected)
        return weights
