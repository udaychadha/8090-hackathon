"""Private subprocess entry point. This module is never an eval judge."""

from __future__ import annotations

import copy
import json
import traceback
from pathlib import Path

import pandas as pd

from factory.contract import (
    ContractViolation,
    load_strategy,
    read_strategy,
    validate_bars,
    validate_weights,
)
from factory.data import EventBars
from factory.data_contract.sessions import protected_session_columns, validate_session_columns


def main() -> int:
    try:
        request = json.loads(Path("request.json").read_text())
        bars = {symbol: pd.read_parquet(f"{symbol}.parquet") for symbol in request["symbols"]}
        definition = read_strategy("strategy.py", available_universe=list(bars))
        if definition.extra:
            bars = EventBars(bars)
        index = validate_bars(bars)
        for symbol, frame in bars.items():
            validate_session_columns(frame, definition.frequency, symbol)
        strategy = load_strategy(definition)

        def generate():
            inputs = {symbol: frame.copy(deep=True) for symbol, frame in bars.items()}
            output = strategy.generate_signals(inputs, copy.deepcopy(request["params"]))
            for symbol, original in bars.items():
                columns = list(protected_session_columns())
                if "is_filled" in original:
                    columns.append("is_filled")
                try:
                    pd.testing.assert_frame_equal(
                        original[columns], inputs[symbol][columns], check_exact=True
                    )
                except (AssertionError, KeyError, TypeError) as error:
                    raise ContractViolation(
                        f"{symbol}: session/provenance fields are read-only"
                    ) from error
            return validate_weights(output, index, definition.universe)

        if definition.extra:
            from factory.event_execution import generate_event_weights

            extra = {name: pd.read_parquet(f"extra-{name}.parquet") for name in request["extra"]}
            first = generate_event_weights(strategy, definition, bars, request["params"], extra)
            second = generate_event_weights(strategy, definition, bars, request["params"], extra)
        else:
            first, second = generate(), generate()
        try:
            pd.testing.assert_frame_equal(first, second, check_exact=True)
        except AssertionError as error:
            raise ContractViolation("Strategy is nondeterministic on identical inputs") from error
        first.to_parquet("weights.parquet", index=True)
        Path("result.json").write_text(json.dumps({"ok": True}))
        return 0
    except BaseException as error:
        Path("result.json").write_text(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "traceback": traceback.format_exc(),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
