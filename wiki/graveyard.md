# Strategy graveyard

Postmortems below preserve the recorded evaluation results. Run `r_449ef7fd3ae6`
completed with inactive portfolios: the generated strategies assumed an absent
16:00 endpoint bar, and variant B also derived an incorrect clock conversion.
These failures do not establish whether the paper's economic hypothesis holds.

## Market intraday momentum — first-half-hour sign timing | r_449ef7fd3ae6 | A

FAILED_EVAL_2 (1/5)

### Strategy postmortem — Variant A

**Recorded status: `FAILED_EVAL_2`.** The supplied telemetry records one passed evaluation out of five.

The strategy uses the sign of SPY’s return from the previous close to 10:00 a.m., including overnight movement, to select unit long or short exposure from 3:30 to 4:00 p.m. This test transfers the paper’s transaction-price endpoints to one-minute data; it is not an exact replication.

**Claim versus measured telemetry.** The supplied paper summary reports a **1.08 gross Sharpe** for February 1993–December 2013. The run’s verified Sharpe and break-even transaction cost are **unknown**. Its friction evaluation reports **0.0 annualized return, 0.0 maximum drawdown, and 0.0 average daily turnover over 453 days**. Sharpe is undefined at every tested cost level—0, 2, 5, and 10 basis points. These flat reported results do not reproduce the claimed performance or establish cost resilience; the telemetry does not identify why turnover was zero.

**Evaluation outcomes**
- **Lookahead: passed** at the five recorded truncation cuts. This alone does not validate implementation fidelity.
- **Friction: failed**, with undefined Sharpe at all tested costs, including the required 5-basis-point test.
- **Sensitivity: failed**, with undefined baseline and perturbed Sharpes. Calendar/time constants were among the perturbed parameters; exit time was not perturbed.
- **Decay: failed**, with undefined in-sample and out-of-sample Sharpes, ratios, and concentration measures across 453 and 152 days.
- **Deflated Sharpe: failed**, citing incomplete sibling-trial accounting or undefined trial Sharpe.

**Limitations.** Endpoint-to-bar mapping, adjustment conventions, shortened sessions, execution assumptions, and historical bid/ask data remain unresolved. The paper’s fewer-than-500-trades exclusion also lacks supplied transaction counts and uses full-day information unavailable at entry. Recorded lookahead cuts fall in 2024–2025, rather than the claimed 1993–2013 sample.

The supplied evidence therefore leaves the paper’s claimed performance unverified for this transfer. This is a backtesting assessment, not trading advice.

## Market intraday momentum — first-half-hour sign timing | r_449ef7fd3ae6 | B

FAILED_EVAL_2 (1/5)

### Strategy postmortem — Variant B

**Recorded status: `FAILED_EVAL_2`.** One evaluation passed; four were recorded as failed.

The intended strategy uses SPY’s previous-close-to-10:00 a.m. return, including overnight movement, to choose unit long or short exposure from 3:30 p.m. to 4:00 p.m. The supplied paper specification claims a **gross Sharpe of 1.08** over February 1993–December 2013. This test transfers the endpoint-based strategy to one-minute bars rather than directly reproducing that sample and price construction.

### Claim versus telemetry
- **Verified Sharpe:** unknown. Sharpe was undefined at all tested friction levels: 0, 2, 5 and 10 bps.
- **Break-even costs:** unknown.
- **Recorded activity:** annualized return, maximum drawdown and average daily turnover were each **0.0** across 453 trading days. This is consistent with an inactive evaluated return stream, not evidence of a successfully operating, low-risk strategy. The telemetry does not establish the cause.

### Evaluation results
- **Lookahead — passed:** prefix checks passed at five cut points. This does not establish fidelity to the paper’s endpoint prices or sample rules.
- **Friction — failed:** no defined Sharpe was available to satisfy the 0.5 threshold at 5 bps.
- **Sensitivity — failed:** base Sharpe and robustness ratios were undefined. Most perturbations also had undefined Sharpe; the 11:00 a.m. signal perturbation recorded **−3.95**.
- **Decay — failed:** in-sample and out-of-sample Sharpes, their ratio and concentration statistics were undefined across 453 and 152 days, respectively.
- **Deflated Sharpe — failed:** telemetry cites incomplete sibling-trial accounting or undefined trial Sharpe.

### Limitations and conclusion
Endpoint-to-bar mapping, closing-price availability, the fewer-than-500-trades exclusion, shortened sessions, corporate-action adjustments and execution costs remain unresolved in the supplied specification. Historical coverage matching 1993–2013 is not established. The sensitivity report also lists volatility and exposure parameters not specified for the standalone strategy; their actual use is unknown.

The supplied evidence therefore **does not verify the claimed 1.08 Sharpe or establish a like-for-like rejection of it**. It records an unverified minute-bar transfer with zero reported turnover and largely undefined performance statistics. This is a backtesting assessment, not trading advice.

## Market intraday momentum — first-half-hour sign timing | r_449ef7fd3ae6 | C

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Variant C

**Recorded status: FAILED_EVAL_2.** One of five evaluations passed. This was a transfer backtest using SPY one-minute data, not a reproduction of the paper’s original TAQ endpoint-price implementation.

### Claimed result versus telemetry
The supplied paper specification reports a **gross Sharpe of 1.08** over February 1993–December 2013. The strategy takes the sign of the previous-close-to-10:00 a.m. return, enters that direction at 3:30 p.m., and exits at 4:00 p.m.

The supplied telemetry does **not verify that Sharpe**. Over 453 reported trading days, annualized return, maximum drawdown, and average daily turnover were all recorded as **0.0**. Sharpe was undefined at every tested friction level—0, 2, 5, and 10 bps—and break-even costs were unknown. These flat results provide no evidence of an active strategy return stream; they do not establish that the paper’s effect disappeared.

### Evaluation outcomes
- **Lookahead — passed:** five truncation checks passed at a tolerance of \(10^{-9}\). This supports consistency under those checks, not complete timing correctness.
- **Friction — failed:** Sharpe was undefined, so the required Sharpe of 0.5 at 5 bps was not demonstrated.
- **Sensitivity — failed:** baseline and perturbed Sharpes were undefined. Two perturbations also raised duplicate-label reindexing errors. Several parameters, including entry and exit times, were not jittered.
- **Decay — failed:** in-sample and out-of-sample Sharpes and their ratio were undefined across 453 and 152 days, respectively. Concentration checks were also not established.
- **Deflated Sharpe — failed:** telemetry cites incomplete sibling-trial accounting or undefined trial Sharpe.

### Limitations and conclusion
The transfer leaves unresolved endpoint-bar timing, corporate-action adjustments, shortened sessions, missing prices, and reproduction of the paper’s fewer-than-500-trades exclusion. The supplied inputs also lack the historical quotes needed for the paper’s separate transaction-cost analysis. Telemetry timestamps are from a substantially later period than the claimed paper sample.

The recorded outcome is therefore a **failed validation with undefined performance statistics**, not a measured Sharpe shortfall against 1.08. The evidence does not identify the cause of the zero-turnover result or establish economic robustness. This is a backtesting assessment, not trading advice.
