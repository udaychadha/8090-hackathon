# Track A execution notes

These modules implement WO-05 through WO-07. Live acceptance is **pending**:
no research PDFs or role model settings were present during implementation.
Offline fixtures and mocked model responses are not a real-paper run.

Required environment dependencies: `pymupdf`, `openai`, `anthropic` in addition
to the existing project dependencies. They have not been installed or added to
the root project manifest because those paths are outside Track A ownership.

Set `EXTRACTOR_MODEL`, `WORKER_MODEL`, and `CRITIC_MODEL` to
`openai:<model-id>` or `anthropic:<model-id>` and supply the matching provider
key through the environment. No model ID is hardcoded. For estimated dollar
costs, supply each role's `<ROLE>_INPUT_USD_PER_MTOK` and
`<ROLE>_OUTPUT_USD_PER_MTOK`. Missing prices or cached usage yield unknown cost,
not zero. Token counts and model identity are retained. Confirm against provider
billing for actual charges.

Owner-supplied research PDFs belong in `papers/`. WO-05 requires two extracted
papers; WO-07 requires only one real paper end to end. No papers are downloaded.

Run one paper from the repository root:

```
.venv/bin/python -m factory.orchestrator papers/<file>.pdf
```

The CLI writes records and events under `runs/`, generated strategies under
`strategies/<source>/<run>/`, and postmortems to `wiki/graveyard.md`. It never
reads HOLDOUT. Only the existing deterministic harness reads OOS.

Run all tests explicitly, since root pytest configuration defaults to `tests/`:

```
.venv/bin/python -m pytest tests factory/agents -q
.venv/bin/ruff check factory/llm.py factory/orchestrator.py factory/agents
```

Self-heal permits three bug repairs, uses IS only, and never receives metric
failures. A real sandbox/Eval 1 test injects lookahead and repairs it using a
mocked model response. The integration test uses stubbed paper extraction and
eval telemetry: it verifies plumbing, **not** real-paper acceptance.

The current implementation stops at WO-07. It does not expose the WO-09 HTTP
API. The SQLite record payloads are internal; the later API must map them to the
fixed public contract. Operational provider/harness failures fail the run.
Unavailable trial accounting forces Eval 5 to fail closed rather than silently
under-counting candidate trials. No eval implementation or threshold was changed.
