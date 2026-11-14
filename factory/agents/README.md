# Paper pipeline execution notes

WO-05 through WO-07 have a real-provider pipeline run recorded in
[WO-07](../../work-orders/WO-07.md). It completed, but all three generated
strategies were inactive because they assumed incompatible clock labels.
That is a pipeline acceptance result, not economic validation of the paper.

Install the project and runtime dependencies with `pip install -e '.[dev]'`.
The manifest includes PyMuPDF and both provider SDKs; `requirements.lock`
captures the validated environment. Default `pytest` includes the agent tests.

Set `EXTRACTOR_MODEL`, `WORKER_MODEL`, and `CRITIC_MODEL` to
`openai:<model-id>` or `anthropic:<model-id>` and export the matching API key.
The debug CLIs load `.env` without overriding exported settings. Model IDs
are configuration, never selected by source code.

For estimated dollar costs, set each role's `<ROLE>_INPUT_USD_PER_MTOK` and
`<ROLE>_OUTPUT_USD_PER_MTOK`. Optional `CACHE_READ`, `CACHE_WRITE`, and
`CACHE_WRITE_LONG` rates price the corresponding reported input-token counts.
Default cache writes mean 30 minutes for OpenAI and 5 minutes for Anthropic;
long writes mean 12 hours and 1 hour respectively. Missing applicable rates
produce unknown cost, never zero. Token categories and model identity are
retained. Use provider billing for actual charges, including account discounts.

Keep owner-approved PDFs in `papers/`. Intake verifies an existing Markdown
cache against the PDF and Markdown SHA-256 fingerprints in `.spec.json`, or
creates a page-labelled full-text Markdown copy on first use. Source URL,
authors, version, and verification metadata are preserved. Changed fingerprints
stop extraction for review; they never silently inherit old provenance.
PDFs, Markdown copies and source/spec sidecars stay local and are gitignored.
Equations and tables may need reference to the original PDF.

```sh
# Prepare or verify Markdown without calling a model.
.venv/bin/python -m factory.agents.extractor papers/<file>.pdf --prepare-only
# Extract and validate a spec; retain it with source provenance.
.venv/bin/python -m factory.agents.extractor papers/<file>.pdf
# Execute one full paper pipeline.
.venv/bin/python -m factory.orchestrator papers/<file>.pdf
# All offline checks.
.venv/bin/python -m pytest -q
.venv/bin/ruff check factory tests
.venv/bin/ruff format --check factory tests
```

Records and events live under `runs/`, generated strategies under
`strategies/<source>/<run>/`, and postmortems in `wiki/graveyard.md`.
Only the trusted harness reads OOS; HOLDOUT is never loaded. Workers get
IS column/dtype information and explicit timestamp/execution conventions.
Self-heal permits at most three IS bug repairs and receives no metric failures.

A provider failure before Eval 2 fails the run operationally without altering
valid sibling results. Missing trial statistics after evaluation begins still
fail Eval 5 closed. Chart-recording failures preserve valid trial statistics
while marking the run operationally failed. Prior completed repair usage is
retained if a later repair call fails; total cost remains unknown when a failed
provider call's billing cannot be determined.

Variant records contain daily gross/net equity, date boundaries and exact UTC
split timestamps. The recording adapter observes the harness's base strategy
executions and checks its reconstructed OOS returns against evaluated returns.
It does not rerun generated strategies. Both IS and OOS start flat, matching
the reference engine. Intraday slices sharing a day compound into one curve
point. Activity counts identify inactive portfolios without changing verdicts.
No eval code or thresholds were modified.

Configured credentials are filtered before provider prompts, generated code,
records, events, CLI output and complete graveyard entries. Regression tests
exercise both real SDKs with offline HTTP transports and fake credentials.
The wrapper still requires the real key for the provider authentication header.

The implementation stops at WO-07. The later API must map these internal
records into the public contract; no HTTP product API or app UI is included.
