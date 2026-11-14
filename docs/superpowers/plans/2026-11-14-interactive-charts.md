# Interactive charts implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation and one independent review.

**Goal:** Inspect exact recorded equity/price points with crosshairs, values and deltas, and enlarge either chart.

**Architecture:** Keep the existing SVG rendering and API payloads. A shared interactive plot handles pointer/keyboard selection, responsive geometry, crosshairs and a native modal. Equity and dataset adapters supply truthful labels and recorded values.

**Tech stack:** Existing React, TypeScript, SVG and CSS tokens; no dependencies or backend changes.

**Spec:** Owner's November 14 request for hover guides, values/deltas, dataset interactivity and larger graphs. Continued autonomous implementation is already authorized.

## Design and approaches

Extend the existing SVG components: retains the mock-up's style and makes exact point selection explicit. A charting dependency would replace working rendering and add unnecessary surface area; browser fullscreen alone would enlarge the existing static graph without adding the requested inspection.

Chosen implementation: hover/touch selects the nearest actual timestamp, never an interpolated value. Dotted vertical/horizontal guides and solid point markers show the location. Equity displays gross/net indices, net change from the first recorded point, previous-point change, and the gross/net gap. Dataset displays close USD, changes from the first/previous shown observations, volume in shares and fill provenance. Downsampled comparisons are labelled as shown observations. UTC labels stay explicit. Missing values remain unavailable.

Both charts have an Expand button with a large, responsive dialog. Escape/Close restores focus; keyboard arrows and Home/End inspect points. Maintain IS/OOS markers, sealed HOLDOUT notes, existing theme tokens and neutral result styling. Increase the dataset chart's default height. No pan/zoom, raw data downloads, model calls or financial evaluation changes.

## Global constraints

- API access remains solely in the existing data-access module; interaction requires no API calls.
- Existing eval logic, thresholds, strategy/data contracts and stored results stay untouched.
- Native modal focus containment and focus restoration; touch must retain page scrolling.
- Read-only charts must not imply a dollar account balance for normalized equity.

## Review focus

- Sparse/irregular timestamps select the closest actual point, not an array-index approximation.
- Single/flat series and absent/zero values avoid NaN or invented observations.
- Changing dataset/split resets selection, so old details cannot survive under a new title.
- Pointer mapping remains correct when resized or expanded; tooltip stays within narrow screens.
- Downsampling, gaps and sealed HOLDOUT never yield synthetic hover values.

## Task 1: Shared interaction and adapters

Files: `web/src/components/Charts.tsx`, new `web/src/components/InteractiveChart.tsx`, `web/src/styles.css`, `web/src/tokens.css`, `web/tests/charts.test.tsx`, and the two chart callers.

- [x] Add failing tests for exact point values/deltas, pointer/keyboard selection, flat/single-point data, missing volume, dataset changes, dialog close/focus, and sealed HOLDOUT.
- [x] Run `cd web && npm test -- tests/charts.test.tsx`; confirm missing interaction failures.
- [x] Implement the shared plot, modal, domain adapters and responsive token-based styling.
- [x] Run all frontend tests, TypeScript/build and formatting; fix failures.
- [x] Verify real API charts in desktop/mobile browsers, keyboard, mouse and touch; save screenshots to `report/`.
- [x] Independent review; fix material findings and verify affected behavior.
- [x] Commit on the existing branch and report the outcome.

Verification: 26 frontend tests passed; build and formatting passed. Real-record Chrome checks cover pointer values, keyboard navigation, expanded sizing, focus restoration, split switching, mobile touch and both themes. Independent review found one boundary-day classification issue; its regression test failed before the fix and now passes. Protected eval/contract hashes remain unchanged.
