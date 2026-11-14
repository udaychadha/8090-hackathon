# Arena API and interface — final acceptance

All phases are complete on `wo09-wo08-api-interface`. The application is running
locally at <http://127.0.0.1:5173> with the API at <http://127.0.0.1:8000>.
Startup and reproducible verification commands are in the root README.

## Delivered

- Eight typed record models, lossless backed-up migration, indexed query fields,
  model-validated writers and explicit void audit access.
- FastAPI `/api` serving recorded results, deterministic summaries, ordered
  stages and logs, safe artifact previews, dataset coverage, ingest/audits,
  canonical field descriptions, read-only eval rules and replayable SSE.
- Seven mock-up-based React screens, shared tokens and evidence components,
  visible limitations, neutral missing/failed states and disabled future controls.
- Real PDF submission, durable run IDs and a live Run view through completion.

Model and inventory reports: [records](../docs/RECORDS.md),
[inventory](../docs/RECORD_INVENTORY.md), [API](../docs/API.md),
[interface and design differences](../docs/INTERFACE.md).

## Real paper started through the interface

The browser selected the approved local `gao_han_li_zhou_intraday_momentum.pdf`,
clicked **Test in arena**, navigated to `r_55eebea2c07d` and received **41 live
SSE events**, including the final `done` event. The pipeline completed in
**167.7059 seconds**. Estimated model cost was **$0.6992345** with all model
usage priced. No new market data was downloaded.

| Variant | Test type | Final status | Evals passed | IS days traded | OOS days traded |
| --- | --- | --- | --- | --- | --- |
| A | transfer | FAILED_EVAL_2 | 1/5 | 441 | 147 |
| B | transfer | FAILED_EVAL_2 | 1/5 | 441 | 147 |
| C | transfer | FAILED_EVAL_2 | 1/5 | 179 | 61 |

The run completed successfully as software; its three research variants failed
the deterministic friction eval. No variant is VERIFIED. Later eval results and
critic questions remain recorded and reachable.

The final screenshot revealed a stale selector label inherited from the run
list loaded before extraction. The current selection now uses fresh run detail,
with the uploaded filename as its pre-extraction fallback. Two regression tests
reproduced the original cases, then passed. A read-only browser recheck confirmed
the corrected completed record; no second paid run was started.

[Live-run proof](wo08-browser/real-run-proof.json) ·
[Completed-record recheck](wo08-browser/completed-run-recheck.json)

## Verification

- **375 Python tests passed:** main suite 374 passed in 85.04s; the one explicitly
  opt-in full-data test then passed in 15.59s. That scan validates all 560 stored
  Parquet datasets and derived sessions. Existing dependency deprecation warnings
  remain visible.
- **17 frontend tests passed**, TypeScript/production build and Prettier passed.
  Ruff, whitespace and Python dependency consistency checks passed.
- Chrome verified all seven screens and the original eight runs, including the
  explicit void view, every variant's pipeline detail, real status/type/n/5,
  visible notes, filters, all eval selections, artifact preview and Data subtabs.
  New run, Data and Run were also checked at 390px with no page overflow.
- The browser proof finished with **zero console, page or API errors**. Initial
  Evals duplicate IDs/keys, a missing favicon and mobile selector overflow were
  fixed before acceptance. Screenshots wait for real data to load.
- Post-run schema audit: **477 SQLite records and 311 JSONL lines**, zero
  mismatches. Nine runs are retained; eight are visible by default. Eighteen
  nonvoid variants remain visible; three old void variants stay excluded.
- All ten protected strategy/eval files retain their pre-implementation hashes.
  Eval logic, eval configuration and the strategy contract were not changed.

[Read-only browser proof](wo08-browser/read-only-proof.json) ·
[Final record audit](wo09-record-audit-final.json) ·
[Protected-file proof](wo08-protected-files.json)

## Screenshots

These seven screens were captured against the original eight runs, before the
new paper was submitted. Their counts therefore describe that baseline.

| Screen | Capture |
| --- | --- |
| Run | [Run](wo08-browser/1-run.png) |
| Leaderboard | [Leaderboard](wo08-browser/2-leaderboard.png) |
| Tearsheet | [Tearsheet](wo08-browser/3-tearsheet.png) |
| Graveyard | [Graveyard](wo08-browser/4-graveyard.png) |
| New run | [New run](wo08-browser/5-new-run.png) |
| Evals | [Evals](wo08-browser/6-evals.png) |
| Data | [Loaded catalog and preview](wo08-browser/7-data.png) |

[Evidence browser](wo08-browser/data-evidence.png) ·
[New run started](wo08-browser/8-new-run-started.png) ·
[New run completed](wo08-browser/10-new-run-completed.png) ·
[Mobile Run](wo08-browser/mobile-runs.png) ·
[Mobile Data](wo08-browser/mobile-data.png) ·
[Mobile New run](wo08-browser/mobile-new.png)

Individual captures for all eight historical run IDs are retained beside these
screenshots and indexed in the browser proof. PDFs, market data, credentials,
SQLite and runtime event files remain local and uncommitted.

No owner questions remain pending. Implementation choices made while the owner
was away are recorded in [the handoff notes](../docs/IMPLEMENTATION_NOTES.md).
