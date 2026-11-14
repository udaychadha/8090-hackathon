# Financial Models In the Arena

A paper goes in, three strategy candidates come out, and deterministic code
judges them. The local application exposes failed runs, repair attempts, all
five evals, source documents, data coverage and logs. No model can change an
evaluation verdict.

The blueprint is [AGENTS.md](AGENTS.md), the generated data definition is
[docs/DATA.md](docs/DATA.md), and the backlog is in [work-orders/](work-orders/).

## Start the local application

Python 3.11+ and Node 20.19+ or 22.12+ are required. Development uses Python 3.12
and Node 22. Credentials, market data, PDFs and runtime records are ignored by
Git. Existing records stay in `runs/factory.db` and `runs/events.jsonl`.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
# First setup only; preserve an existing .env.
cp -n .env.example .env
```

`requirements.lock` captures the installed Python dependencies. To reproduce
that environment, install it first, then install the project with
`python -m pip install -e '.[dev]' --no-deps`.

For a legacy record store, audit and migrate before starting the API. Migration
backs up the database and event mirror, reports every change and preserves
historical evidence. It does not rerun strategies or change verdicts.

```sh
python -m factory.record_migration audit --root runs --report report/record-audit.json
python -m factory.record_migration migrate --root runs --report report/record-migration.json
```

Start the API in one terminal and the interface in another:

```sh
# Repository root
.venv/bin/uvicorn factory.api.app:app --host 127.0.0.1 --port 8000
```

```sh
cd web
npm ci
npm run dev -- --port 5173
```

Open <http://127.0.0.1:5173>. Vite proxies `/api` to port 8000. API documentation
is at <http://127.0.0.1:8000/docs>. Run one API process: it owns the local paper
queue and recovers interrupted submissions on restart. This is a local,
single-user application; hosted deployment and authentication are out of scope.
The web `.npmrc` retains the lockfile's legacy-peer-deps setting for npm 10.

## Use the application

- **Run:** reopen retained runs, inspect specs and data needs, switch lanes,
  inspect steps and logs, and follow a new run live. An explicit audit toggle
  exposes void records; normal views exclude them.
- **Leaderboard and Tearsheet:** compare actual results, inspect equity, evals,
  strategy code and repairs. Missing evidence stays unavailable. Only VERIFIED
  receives positive result styling.
- **Graveyard:** browse structured causes and deterministic summaries.
  Historical model narratives are labelled unverified and cannot change facts.
- **New run:** choose a text-based PDF and select **Test in arena**. This starts
  a real model-backed pipeline and opens its live Run screen.
- **Evals:** inspect the five evals, actual thresholds and source. Threshold
  editing and custom profiles remain unavailable.
- **Data:** inspect local datasets, validated IS/OOS previews, coverage, fills,
  ingest history, audits, canonical fields and artifacts. HOLDOUT stays sealed.

PDF intake works. Spec editing, described strategies, provider-key entry, event
uploads and external-source approval are visibly disabled until their backends
exist. No control fabricates data or pretends to save a change.

## Models and data

Paper runs read `EXTRACTOR_MODEL`, `WORKER_MODEL` and `CRITIC_MODEL` as
`provider:model-id`, with the appropriate `OPENAI_API_KEY` or
`ANTHROPIC_API_KEY`. Set pricing as described in the
[agent execution notes](factory/agents/README.md) for complete dollar estimates.
The API loads `.env` and optional `runs/secrets.env`; existing environment
variables take precedence. Keys never appear in responses.

The Alpaca provider reads `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` for explicit
ingestion. Existing local data can be viewed and used without downloading it
again. Writes and loads validate the generated canonical contract; see
[docs/DATA.md](docs/DATA.md) for timestamps, sessions, adjustments, fill markers,
units and splits. The daily universe uses current index membership, so daily
results visibly retain the survivorship-bias limitation.

```sh
# Explicit data acquisition, only when needed and authorized.
python -m factory.ingest_alpaca --through 2026-11-12
python -m factory.audit_data
```

Generated strategies run in a separate process with a temporary working
directory and timeout. This is crash isolation, not a security boundary for
hostile Python. The application never places brokerage orders.

## Checks and evidence

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check factory tests
cd web
npm test
npm run build
npm run format:check
```

With both services running, the real-browser acceptance script reads all seven
screens and every retained run, verifies audit visibility and mobile layout,
and writes screenshots/proof under `report/wo08-browser/`:

```sh
# Repository root. Default is read-only.
node scripts/verify_interface.mjs
# Optional: starts one real run using configured, billable models.
node scripts/verify_interface.mjs --submit papers/gao_han_li_zhou_intraday_momentum.pdf
```

The script uses installed Google Chrome on macOS; set `ARENA_CHROME` to another
Chromium executable and `ARENA_UI_URL` to another local UI URL.

Record migration evidence: [docs/RECORDS.md](docs/RECORDS.md).
Artifact reachability: [docs/RECORD_INVENTORY.md](docs/RECORD_INVENTORY.md).
API behavior and verification: [docs/API.md](docs/API.md).
