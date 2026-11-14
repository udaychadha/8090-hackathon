# Local research API — Phase 2 report

The implemented contract is in [AGENTS.md](../AGENTS.md). Start the API from the
repository root with:

```sh
.venv/bin/uvicorn factory.api.app:app --host 127.0.0.1 --port 8000
```

OpenAPI is available at `/openapi.json`, interactive API documentation at `/docs`,
and application endpoints under `/api`. Configuration loads from the local
`.env` and optional `runs/secrets.env`, without overriding existing environment
variables. This is the local, single-user application; deployment and auth are
outside this work order.

## Implemented behavior

- Typed run/source/leaderboard/variant reads, structured graveyard entries,
  exact recorded metrics, deterministic one-sentence summaries and ordered
  code/repair/eval/critic steps. Preliminary bug checks cannot masquerade as
  completed performance evals. Missing evidence remains visibly unknown.
- Read-only database connections for requests. Void runs and children return
  404 or disappear from collections unless `include_voided=true` is supplied.
- Multipart PDF intake with a 30 MB limit, real parser checks, durable run ID,
  one local background job, and isolation from original paper sidecars. Matching
  local PDFs reuse verified Markdown/provenance without modifying the originals.
- Replayable SSE with global sequence IDs, cursor reconnects, keepalives,
  terminal closure and explicit recovery of interrupted API-owned runs.
  A historical terminal record lacking a completion event closes after a short
  grace period with an explanatory comment, without fabricating old events.
- Dataset catalog/detail/preview from existing manifests and canonical validated
  loads. Default preview joins IS/OOS and stops before sealed HOLDOUT. It includes
  split boundaries, fill/coverage facts, gaps and canonical field descriptions.
- Actual ingest history, audits, current universe provenance, data-contract
  documentation and a safe artifact inventory. Registered artifacts include
  source PDFs/Markdown, strategies, reports, metadata and migration/recovery
  evidence. Database bytes and raw HOLDOUT prices are never downloaded.
- Read-only eval schema generated from actual config values and existing eval
  source. Relative comparisons explicitly represent multiplication by another
  metric; the decay rule is not misrepresented when IS Sharpe is negative.
- Provider status reports configured-key presence only. English intake, saved
  spec starts, event upload, key writes, source approval and custom profiles
  remain unavailable and return 501. No fake feature state is persisted.

New critic calls can only select qualitative topic identifiers. Application code
renders fixed review questions; no model prose can introduce factual result
claims. Historical critic prose remains separately labelled, unverified evidence.
The generated data-contract section is still supplied to every agent role.

## Evidence

The full suite passed **375 tests in 97.49 seconds**, including the stored-data
checks. Ruff, whitespace and installed-dependency checks passed. Known upstream
NumPy/calendar/SWIG and Starlette/httpx deprecation warnings remain visible.
Protected strategy/eval files retain all ten pre-implementation fingerprints.

An additional **84 requests** exercised the actual local records and documented
shapes: all eight historical run details and streams, all eighteen tearsheets,
five sources, catalog/data endpoints, artifact access, read-only evals, provider
presence and unavailable writes. Normal views show seven runs and fifteen
variants; none is VERIFIED. Catalog contains 557 main datasets plus three smoke
datasets in an explicit separate scope. The measured default artifact inventory
contained 1,189 entries; later reports/uploads legitimately add entries.

Local proof artifacts are `report/wo09-api-proof.json` and
`report/wo09-openapi.json`. Tests cover submission/restart/failure behavior using
an injected external-run boundary; the new real paper launched through the UI
is the separate Phase 4 acceptance check, not claimed here.

Review fixes include safe validation errors, read-only mirror behavior, strict
source identity, absence of false live critic failures, visibility-checked run
artifact links, replay after terminal events, crash recovery and readable
sanitized torn-backup evidence. No eval logic, strategy contract, market data
or stored strategy verdict was changed.
