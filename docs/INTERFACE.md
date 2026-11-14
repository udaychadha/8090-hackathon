# Interface — Phase 3 acceptance

The React/Vite/TypeScript interface implements Run, Leaderboard, Tearsheet,
Graveyard, New run, Evals and Data using only the live `/api` module. Shared
tokens and evidence components follow the seven supplied boards. Failure,
inactivity and missing evidence are first-class states; VERIFIED alone receives
positive result styling. Daily survivorship notes remain visible.

Run lanes expose horizontal pipeline stages with recorded detail and step logs.
Leaderboard filters/sorts actual rows. Tearsheet retains every eval, repair,
source, code and equity curve when available. Data includes validated previews,
sealed HOLDOUT boundaries, ingest/audit/contract/universe views and a searchable
artifact browser. Historical narrative is labelled unverified; factual summaries
come from deterministic API templates.

PDF intake is connected to the real run endpoint and live event stream. Future
controls remain disabled and labelled “Not available yet”. Phase 4 separately
proves one real model-backed submission; unit submission tests do not claim it.

## Gate passed

- 15 frontend tests: real-vs-missing values, eval positions and neutral status
  styling; escaped notes; PDF validation/submission/failure; stream cursor,
  deduplication and termination; absent equity/sealed HOLDOUT; duplicate eval
  constants with distinct rule controls and accessible IDs.
- TypeScript and production build passed; formatting, whitespace and dependency
  consistency checks passed. All ten protected strategy/eval files are unchanged.
- Real Chrome opened all seven screens and all eight historical runs. It checked
  each variant lane and every step's actual detail lines, status, test type, n/5,
  visible notes, the void audit toggle, leaderboard filters, all eval selections,
  artifact previews and Data subtabs. No browser console/page/API errors remained.
- At 390px, New run, Data and Run fit the viewport. Tables and pipeline stages
  scroll within their containers. The loaded Data screenshot includes actual
  catalog rows and preview observations, not a loading state.

`scripts/verify_interface.mjs` repeats these checks against the retained local
records. Local proof is `report/wo08-browser/read-only-proof.json`. See the root
README for startup and test commands; `web/README.md` describes the frontend.

## Intentional differences from the mock-ups

- Actual records contain no VERIFIED result at this gate. The invented green
  success, paper names, returns, fixture counts and capacity eval are absent.
- Long real titles, visible data limitations and fifteen retained variants make
  some pages longer. Long metric arrays and log history have bounded disclosure
  views so they remain reachable without overwhelming the main result.
- Filters use labelled selects. Run history and explicit audit toggles expose
  extraction failures and retained void evidence that the boards did not show.
- Data has subtabs for the existing evidence inventory, ingest log, audits,
  canonical contract and universe. Its preview never draws held-out prices.
- New run goes directly from the real PDF submission to the live run. Spec
  approval/editing and described-strategy steps are disabled, not simulated.
- Evals displays the actual five read-only rules and source. Draft authoring,
  threshold editing and unimplemented providers/uploads remain unavailable.
- Light theme and accent choices persist; default dark matches the boards.

## Phase 4 complete

The approved Gao paper was submitted through the interface and completed as
`r_55eebea2c07d` in 167.7059 seconds, at an estimated model cost of $0.6992345.
The browser received 41 live events including completion. A/B/C all traded and
ended FAILED_EVAL_2 with 1/5 evals passed; IS days traded were 441/441/179.
The full Python checks (375 including the explicit stored-data scan) and final
frontend suite (17) passed. The record audit has zero mismatches.

Live acceptance also caught a stale run-selector title after extraction. The
selector now uses current run detail, with two regression cases and a real
completed-record browser recheck. No additional paid run was needed.

See the [final report and screenshot index](../report/wo08-acceptance.md) for
evidence, final counts, limitations and deliberate differences from the boards.
