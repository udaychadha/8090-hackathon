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


def main() -> int:
    try:
        request = json.loads(Path("request.json").read_text())
        bars = {symbol: pd.read_parquet(f"{symbol}.parquet") for symbol in request["symbols"]}
        definition = read_strategy("strategy.py", available_universe=list(bars))
        index = validate_bars(bars)
        strategy = load_strategy(definition)

        def generate():
            output = strategy.generate_signals(
                {symbol: frame.copy(deep=True) for symbol, frame in bars.items()},
                copy.deepcopy(request["params"]),
            )
            return validate_weights(output, index, definition.universe)

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
