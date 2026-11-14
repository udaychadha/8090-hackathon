# Strategy graveyard

Postmortems below preserve the recorded evaluation results. Run `r_449ef7fd3ae6`
is **VOID** and excluded from the leaderboard and eligible trials. It originally
completed with inactive portfolios: the generated strategies assumed an absent
16:00 endpoint bar, and variant B also derived an incorrect clock conversion.
These failures do not establish whether the paper's economic hypothesis holds.
Its original narratives below are retained as historical evidence, not current
verdicts.

## Market intraday momentum — first-half-hour sign timing | r_449ef7fd3ae6 | A

VOID — excluded; original verdict FAILED_EVAL_2 (1/5).

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

VOID — excluded; original verdict FAILED_EVAL_2 (1/5).

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

VOID — excluded; original verdict FAILED_EVAL_2 (1/5).

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

## Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY) | r_e7094212a558 | A

INACTIVE (0/5)

### Strategy postmortem — Variant A

**Status: INACTIVE; not evaluation-eligible.** This replication attempt did not produce an active strategy, so it provides no measured performance comparison with the paper.

The supplied specification describes SPY intraday momentum using 14-session time-of-day noise bands, current-band/VWAP stops, volatility-scaled fixed daily shares, half-hourly decisions and mandatory session-end liquidation.

| Metric | Paper claim | Run telemetry |
|---|---|---|
| Sharpe ratio | 1.33, May 2007–April 2024 | Unknown |
| Break-even trading cost | Not supplied | Unknown |
| IS activity | No comparable figure supplied | 0 active bars out of 175,446; 0 traded days |
| Evaluations passed | — | 0 |

**Failure observed.** The IS activity check failed: zero traded days against the five-day minimum. Telemetry reports “strategy never trades; check session-time logic.” This identifies an inactivity symptom, not a confirmed root cause. No performance evaluation passed; individual performance-test results were not supplied. Missing Sharpe and break-even-cost values are unknown, not zero.

**Replication limitations.** The paper claim uses IQFeed data, while the specified available source is Alpaca SIP; the run’s date coverage was not supplied. Exact minute-label/execution equivalence remains unresolved. Other material ambiguities include the minute-bar VWAP proxy, entry/stop/reversal precedence, daily-return and adjustment conventions, missing-bar and early-close handling, and conversion of fixed shares into engine weights. Telemetry does not establish how these were implemented or whether the paper’s stated baseline costs—$0.0035 commission plus $0.001 slippage per share per transaction—were applied.

**Conclusion.** The supplied evidence documents an inactive implementation attempt, not a successful replication or a performance-based rejection of the claimed Sharpe. This is a backtesting assessment, not trading advice.

## Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY) | r_e7094212a558 | B

FAILED_EVAL_2 (1/5)

### Strategy postmortem — Variant B

**Recorded status: FAILED_EVAL_2.** One of five evaluations passed. The supplied telemetry does not reproduce the paper’s claimed Sharpe of **1.33**.

#### Claimed versus measured
The paper’s headline result covers **May 2007–April 2024**, using IQFeed minute data and a baseline commission plus slippage of **$0.0045 per share per transaction**. Telemetry reports a verified **OOS Sharpe of −3.07 at 5 bps**, versus **IS Sharpe of −1.41**. These cost conventions are not directly equivalent, and the exact replication sample boundaries are not supplied.

The friction sweep shows substantial cost sensitivity:

| Applied friction | Sharpe |
|---|---:|
| 0 bps | 0.74 |
| 2 bps | −0.14 |
| 5 bps | −1.41 |
| 10 bps | −3.33 |

Reported interpolated break-even friction was **0.55 bps**. The friction evaluation also recorded **−6.54% annualized return**, **−13.26% maximum drawdown**, and **1.59 average daily turnover** across 453 trading days. Activity telemetry recorded nonzero targets on **252 IS dates** and **91 OOS dates**; those counts indicate exposure, not profitability or transaction counts.

#### Evaluation outcomes
- **Lookahead — passed:** prefix-consistency checks passed at five truncation points. This does not establish full point-in-time data integrity or exact paper replication.
- **Friction — failed:** Sharpe at 5 bps was −1.41, below the required 0.50.
- **Sensitivity — failed:** every reported perturbation had negative Sharpe; the worst was **−1.93**. The worst/base ratio was unavailable, and four numeric parameters were not tested.
- **Decay — failed:** OOS Sharpe deteriorated to −3.07. The reported OOS/IS ratio of 2.18 divides two negative values and is not evidence of retained performance. Concentration shares were unavailable, although the concentration check was recorded as failed.
- **Deflated Sharpe — failed:** DSR was **0.0249**, below 0.95. Three trials were counted, but only two trial Sharpes were supplied.

#### Replication limitations
The supplied evidence leaves unresolved differences in **Alpaca SIP versus IQFeed data**, sample coverage, adjusted-price treatment, minute-label/execution timing, VWAP construction, entry/stop precedence, daily-return inputs, fixed-share target conversion, and missing-bar/early-close handling. No implementation trace establishes how these ambiguities were resolved. Holdout performance is not reported and remains unknown.

**Bottom line:** the measured run showed positive zero-friction Sharpe but failed the reported cost, sensitivity, decay, and deflated-Sharpe evaluations. These results document this backtest, not a definitive test of the original paper or trading advice.

## Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY) | r_e7094212a558 | C

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Variant C

**Recorded status: FAILED_EVAL_2.** The supplied telemetry does not reproduce the paper’s claimed performance. One of five evaluations passed.

### Claimed versus measured
The paper claims a **1.33 Sharpe** for SPY from May 2007 through April 2024, using IQFeed minute data and baseline costs of $0.0035 commission plus $0.001 slippage per share per transaction.

Telemetry reports an **OOS Sharpe of −3.05 at 5 bps**, versus **−1.20 IS**. In the friction evaluation, Sharpe fell from **0.73 at zero modeled friction** to **−0.06 at 2 bps**, **−1.20 at 5 bps**, and **−2.96 at 10 bps**. Reported interpolated break-even friction was **0.58 bps**. That evaluation also reported **−6.53% annualized return**, **−12.80% maximum drawdown**, and **1.66 average daily turnover**.

Activity was present: nonzero targets occurred on **245 IS dates** and **91 OOS dates**. These counts include held exposure; they are not trade counts.

### Evaluation results
- **Lookahead — passed:** prefix checks passed at five cut points with tolerance \(10^{-9}\). This does not establish full replication fidelity.
- **Friction — failed:** Sharpe at the required 5 bps was −1.20, below the 0.50 threshold.
- **Sensitivity — failed:** all reported perturbations had negative Sharpe; the worst was **−1.37**. The worst-ratio metric was unavailable.
- **Decay — failed:** OOS Sharpe deteriorated to −3.05. The reported OOS/IS ratio of 2.54 divides two negative values and does not indicate improvement. Concentration checks were marked false, but their window-share metrics were unavailable.
- **Deflated Sharpe — failed:** DSR was **0.0257**, below 0.95. Three trials were counted, but only two trial Sharpes were supplied.

### Limitations
This is not a like-for-like reproduction: the available source is Alpaca SIP rather than IQFeed, full evaluation date bounds are absent, and basis-point friction is not directly equivalent to the paper’s per-share costs. Exact VWAP construction, decision/execution timing, entry-stop precedence, volatility-return definition, fixed-share implementation, adjustment treatment, and missing-bar handling remain unresolved. Sensitivity telemetry also lists a regime-volatility parameter without establishing whether it affected the selected core strategy.

Separate OOS return and drawdown metrics, full implementation details, and holdout results are **unknown**, not zero. The supplied evidence supports failure of this implementation under the recorded tests, not a definitive rejection of the original paper’s result.

*Backtesting analysis, not trading advice.*

## Market intraday momentum | r_17ac8caf8a59 | A

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Variant A

**Recorded status: FAILED_EVAL_2.** One of five evaluations passed. This was a minute-bar **transfer test**, not an exact replication of the paper.

### Claimed versus measured performance

The supplied specification attributes a **1.08 pre-cost Sharpe** to the paper’s SPY first-half-hour sign strategy over February 1993–December 2013. The strategy uses the previous close-to-10:00 return to choose a long or short position for 15:30–16:00.

Telemetry reports substantially weaker results:

| Metric | Measured result |
|---|---:|
| IS Sharpe, 0 bps | 0.121 |
| IS Sharpe, 2 bps | -1.143 |
| IS Sharpe, 5 bps | -3.039 |
| OOS / verified Sharpe, 5 bps | -6.254 |
| Friction-evaluation annualized return | -11.20% |
| Friction-evaluation maximum drawdown | -19.51% |

Even the zero-cost IS result fell below the evaluation’s 0.5 Sharpe threshold. Break-even basis points are **unknown**; the field is null, with telemetry noting that Sharpe was already below 0.5 at zero cost.

### Evaluation outcomes

- **Lookahead passed** at five truncation cuts with tolerance \(10^{-9}\). This supports the tested prefix-consistency check, not complete replication fidelity.
- **Friction failed:** the 5-bps Sharpe was -3.039 against a 0.5 minimum.
- **Sensitivity failed:** available jitter results remained negative. Several perturbations returned no Sharpe, leaving worst-case Sharpe and its ratio unknown.
- **Decay failed:** OOS Sharpe deteriorated from -3.039 to -6.254. The reported ratio of 2.058 divides two negative values and does not indicate improvement. Concentration shares were unavailable; the concentration check was recorded as failed.
- **Deflated Sharpe failed:** DSR was approximately \(2.66\times10^{-10}\), versus a 0.95 requirement, using three supplied trial Sharpes and 152 observations.

Activity telemetry recorded nonzero targets on **441 IS days** and **147 OOS days**, with 30 active bars per traded day. Activity establishes participation, not profitability or correct execution boundaries.

### Limitations

The required exclusion of days with fewer than 500 trades cannot be reproduced from OHLCV. Minute endpoints may differ from TAQ transaction and closing-auction prices; bid/ask execution and the paper’s cost scenarios are also unreproducible from the supplied fields. Prices are retrospectively adjusted, and exact coverage is unspecified, although lookahead cut timestamps fall in 2024–2025, outside the claimed historical sample. Early-close and missing-boundary handling remain implementation assumptions rather than verified replication details.

**Conclusion:** The supplied telemetry does not reproduce the claimed performance and shows materially negative cost-adjusted results. This is a backtest assessment, not trading advice.

## Market intraday momentum | r_17ac8caf8a59 | B

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Market intraday momentum, Variant B

**Recorded status: FAILED_EVAL_2.** One of five reported evaluations passed. This was a one-minute SPY **transfer test**, not an exact replication of the paper’s TAQ-based implementation.

### Claimed versus measured results

The supplied paper specification reports a **1.08 pre-cost Sharpe** for February 1993–December 2013. The tested strategy uses the sign of SPY’s previous-close-to-10:00 return to set directional exposure for 15:30–16:00.

Reported telemetry shows:

| Metric | Measured result |
|---|---:|
| IS Sharpe, zero friction | 0.192 |
| IS Sharpe, 5 bps | −3.505 |
| OOS / verified Sharpe, 5 bps | −6.928 |
| Friction-evaluation annualized return | −10.83% |
| Friction-evaluation maximum drawdown | −18.86% |

Thus, even the zero-friction IS Sharpe was below both the paper’s claim and the evaluation’s 0.5 threshold. The costed OOS result was substantially worse. Break-even friction is **unknown**; the null value does not mean zero.

Activity telemetry records nonzero targets on **441 IS days** and **147 OOS days**, with 13,230 and 4,410 active bars, respectively. Activity establishes that targets were produced, not that the strategy performed successfully.

### Evaluation results

- **Lookahead — passed:** prefix checks passed at the reported \(10^{-9}\) tolerance. This does not establish complete implementation fidelity.
- **Friction — failed:** Sharpe declined from 0.192 at zero bps to −1.286, −3.505 and −7.197 at 2, 5 and 10 bps.
- **Sensitivity — failed:** reported numeric perturbation results remained negative. Numerous perturbations and the aggregate worst-case statistics were unavailable, limiting robustness assessment.
- **Decay — failed:** 5-bps Sharpe deteriorated from −3.505 IS to −6.928 OOS. The positive OOS/IS ratio reflects division of two negative values, not successful retention. Concentration statistics were unavailable; the recorded concentration check failed.
- **Deflated Sharpe — failed:** DSR was approximately \(2.10\times10^{-11}\), versus a 0.95 threshold, using three supplied trials and 152 observations.

### Limitations and conclusion

Comparability is constrained by minute-bar endpoint approximations, retrospective price adjustments, unverified overlap with the paper’s historical sample, and the unavailable trade counts required for its fewer-than-500-trades exclusion. OHLCV cannot reproduce the paper’s bid/ask and closing-auction execution assumptions. The supplied telemetry also does not establish how all missing-boundary and early-close cases were handled. No holdout results are supplied.

On the supplied evidence, this transfer test **did not reproduce the claimed performance** and showed materially negative costed results. These are backtest findings, not trading advice.

## Market intraday momentum | r_17ac8caf8a59 | C

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Market intraday momentum, Variant C

**Recorded status: `FAILED_EVAL_2`.** One evaluation passed. The supplied telemetry does not support the paper’s reported performance in this transfer test.

### Claimed versus measured
The source reports a **1.08 pre-cost Sharpe** for SPY’s first-half-hour sign strategy over February 1993–December 2013. The strategy uses the previous close-to-10:00 return to choose long or short exposure during 15:30–16:00.

Telemetry reports:
- **IS Sharpe:** 0.423 at 0 bps, −0.326 at 2 bps, **−1.444 at 5 bps**, and −3.255 at 10 bps.
- **OOS/verified Sharpe:** **−2.767 at 5 bps**.
- Friction-evaluation annualized return: **−3.82%**; maximum drawdown: **−7.28%**.
- Target activity on **179 IS dates** and **61 OOS dates**, versus 453 and 152 evaluation days respectively. Activity is a bug check, not evidence of profitability.

### Evaluation results
- **Lookahead passed** at five tested truncation points.
- **Friction failed:** Sharpe was below the required 0.5 even without costs, and below it at the designated 5 bps test. Break-even bps is **unknown**, not zero.
- **Sensitivity failed:** all six reported finite perturbation Sharpes were negative. Ten perturbations returned no Sharpe; worst-case Sharpe and ratio are unknown. `trend_sessions` was not jittered.
- **Decay failed:** OOS Sharpe was more negative than IS Sharpe. The reported ratio of 1.916 divides two negative Sharpes and is not evidence of retention. Concentration checks also failed, with window-share metrics unavailable.
- **Deflated Sharpe failed:** DSR was **0.000110**, versus a 0.95 requirement, using three supplied trial Sharpes and 152 observations.

### Limitations
This is a **minute-bar transfer**, not an exact replication of the TAQ-based study. Endpoint closes may differ from the paper’s transaction and market-clearing prices. The required exclusion of days with fewer than 500 trades cannot be reproduced from OHLCV. Quotes, auction prices, borrow costs and execution details are unavailable, so the paper’s cost analysis is not replicated.

Retrospective price adjustments, uncertain boundary-bar and early-close execution handling, and unverified overlap with the original sample further limit comparability. Tested lookahead consistency does not remove these data limitations. HOLDOUT performance is not supplied.

**Bottom line:** the reported transfer results fall short of the claimed Sharpe before costs and are negative at the tested 5 bps cost assumption. This is a backtesting assessment, not trading advice.

## High Frequency and Dynamic Pairs Trading Based on Statistical Arbitrage Using a Two-Stage Correlation and Cointegration Approach | r_b8116b8c72ef | A

INACTIVE (0/5)

### Strategy postmortem — Variant A

**Status: INACTIVE.** The supplied telemetry records no nonzero IS targets across 175,446 minute bars: **0 active bars and 0 traded days**. The strategy failed the minimum-five-day activity check, was not evaluation-eligible, and passed **0 evaluations**. The diagnostic note—“strategy never trades; check session-time logic”—does not establish the root cause.

**Claim versus measurement.** The paper reports an annual Sharpe of **9.25** for August 2012–July 2013 under zero transaction costs. Its conclusion instead cites 9.45, an unresolved source inconsistency. This transfer produced **no verified Sharpe** and **no measured break-even transaction cost**; both are unknown, not zero. The inactive run therefore neither validates nor refutes the paper’s reported performance.

**Scope and limitations.** This was a proposed XOM/CVX transfer, not a replication of the original 177-stock, top-10-pair portfolio. The intended approach aggregates minute data into completed 15-minute observations, applies rolling correlation and cointegration screening, and enters only on a return crossing after a two-standard-deviation excursion. Telemetry does not establish whether those steps were implemented correctly or why no targets became active.

Material unresolved issues include single-pair selection authorization, integration and ADF test details, position sizing, crossing and monthly-transition rules, and execution assumptions. Final adjusted histories are not point-in-time data; short availability, borrow costs, spreads and slippage are unverified. No OOS performance evidence is supplied, and HOLDOUT remains sealed.

**Outcome:** the measured result is an activity-check failure, not a performance result. This is a backtesting assessment, not trading advice.

## High Frequency and Dynamic Pairs Trading Based on Statistical Arbitrage Using a Two-Stage Correlation and Cointegration Approach | r_b8116b8c72ef | B

INACTIVE (0/5)

### Strategy postmortem — Variant B

**Status: INACTIVE; evaluation ineligible.** Supplied IS telemetry reports **0 active target bars out of 175,446** and **0 traded days**, below the five-day activity requirement. No evaluations passed. The recorded diagnostic is “strategy never trades; check session-time logic,” but it does not establish the cause of inactivity.

**Claim versus measurement.** The paper reportedly claims an annual Sharpe of **9.25** for August 2012–July 2013, assuming zero transaction costs. The supplied specification also identifies an unresolved conclusion figure of **9.45**. Neither claim was verified here: measured Sharpe and break-even transaction costs are **unknown**, not zero. The inactive run provides no evidence of realized strategy performance or cost tolerance.

**Scope and limitations.** This was a transfer, not a replication: XOM/CVX offers one candidate pair, versus the paper’s reported 177-stock universe and top-10 pair portfolio. The intended implementation aggregates minute data into completed 15-minute observations, but the supplied telemetry does not verify aggregation, signal timing, screening outcomes or trade-state logic.

Material unresolved details include ADF configuration, residual-band estimation, leg sizing, crossing and execution rules, and treatment of positions across sessions and monthly model changes. Historical adjusted prices are not point-in-time data; borrow availability, execution costs and the original universe are not established.

**Evaluation outcome.** Activity eligibility failed, and **0 evaluations passed**. No individual performance-test results or rejection diagnostics were supplied, so further evaluation failures cannot be identified. The evidence supports an inactive implementation outcome—not confirmation or refutation of the paper’s profitability claim.

*Backtesting assessment only; not trading advice.*

## High Frequency and Dynamic Pairs Trading Based on Statistical Arbitrage Using a Two-Stage Correlation and Cointegration Approach | r_b8116b8c72ef | C

INACTIVE (0/5)

### Variant C postmortem — XOM/CVX pairs-trading transfer

**Outcome:** Telemetry records **INACTIVE**, with evaluation eligibility **false** and **0 evaluations passed**. IS targets were nonzero on **720 of 175,446 bars**, spanning **3 exchange dates**—below the required five-day activity minimum. Active dates measure target exposure, not completed trades.

**Claim versus measurement:** The supplied paper summary claims an annual Sharpe of **9.25** for August 2012–July 2013, assuming zero transaction costs. It also reports an unresolved alternative figure of **9.45** in the conclusion. For this transfer, **verified Sharpe and break-even transaction costs are unknown**; neither metric was supplied. The telemetry therefore provides no measured performance confirmation of the paper’s claim.

**Failed evaluation and diagnostic limits:** The observed activity fails the IS activity requirement. The logged message, “strategy never trades; check session-time logic,” does not literally match the three active dates. It does not establish session-time logic as the cause. No individual performance-evaluation results or failure details were supplied.

**Comparability limits:** This is a transfer, not a replication: one XOM/CVX pair replaces a 177-stock universe and top-10 pair portfolio. Completed 15-minute aggregation from minute data is proposed, but telemetry does not verify its implementation. Position sizing, ADF configuration, residual normalization, execution costs and borrow assumptions remain unresolved. Historical adjusted prices are not point-in-time data, and the platform’s chronological partitions differ from the paper’s rolling evaluation design.

**Bottom line:** The supplied evidence establishes insufficient IS activity, not verified profitability or a measured refutation of the paper’s reported Sharpe. This is a backtesting assessment, not trading advice.

## Statistical Arbitrage in the U.S. Equities Market — 15-PCA Mean-Reversion Strategy | r_d1b6cda53684 | A

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Variant A

**Recorded status: `FAILED_EVAL_2`; 1 of 5 evaluations passed.** This was a transfer of the daily 15-factor PCA residual mean-reversion strategy to 40 fixed equities with a SPY hedge, not a replication of the paper’s historical universe.

### Claimed versus measured performance

The supplied paper summary claims an average annual Sharpe of **1.44 for PCA-based strategies over 1997–2007**, and **0.9 for 2003–2007**. The exact correspondence to the fixed-15-factor variant cannot be checked from the supplied material.

Telemetry reports a **verified OOS Sharpe of 0.249** over 546 daily observations at 5 bps costs. The corresponding IS Sharpe was **−0.214** over 1,639 observations. These results are materially below the headline claim, though the different universe and historical period prevent a like-for-like comparison.

### Evaluation results

- **Lookahead — passed:** prefix-consistency checks passed at five cut points. This does not establish that signals using final daily bars were executable at the same closing price.
- **Friction — failed:** Sharpe was **0.098 at 0 bps**, **−0.027 at 2 bps**, **−0.214 at 5 bps**, and **−0.526 at 10 bps**, below the required 0.5 even without costs. The evaluation also reported annualized return of **−0.224%**, maximum drawdown of **−2.17%**, and average daily turnover of **5.07%**. Break-even bps is **unknown**, not zero.
- **Sensitivity — failed:** tested perturbations produced Sharpes from **−0.813 to 0.708** at 5 bps, indicating substantial dependence on implementation parameters. Several numerical parameters were not tested.
- **Decay — failed:** the OOS Sharpe condition passed, but the reported five-day OOS concentration share was **81.6%**, above the **60%** limit. The OOS/IS ratio is not a conventional retention measure because IS Sharpe was negative.
- **Deflated Sharpe — failed:** the reported statistic was **0.571**, below the **0.95** threshold. Three trials were counted, but only two trial Sharpes were supplied.

### Limitations and conclusion

Current-membership selection introduces survivorship bias. Retaining 15 factors in only 40 stocks materially changes the residual model relative to the paper’s broad universe. The supplied specification also leaves hedge estimation, sizing calibration, financing, borrow costs, and some invalid-fit handling unresolved; implementation fidelity cannot be established from telemetry alone. Final adjusted daily histories are not point-in-time availability records.

The recorded backtest shows active exposure, but weak cost-adjusted performance, parameter sensitivity, and concentrated OOS results. It does **not** substantiate transfer of the paper’s headline Sharpe to this basket. Holdout performance is not supplied. This is a backtesting assessment, not trading advice.

## Statistical Arbitrage in the U.S. Equities Market — 15-PCA Mean-Reversion Strategy | r_d1b6cda53684 | B

BUG_UNRESOLVED (0/5)

### Strategy postmortem — Variant B

**Status: BUG_UNRESOLVED.** Telemetry marks the run as ineligible for evaluation (`eval_eligible: false`), with **0 evaluations passed**. No measured performance is available to assess the strategy’s hypothesis.

| Metric | Source claim | Measured telemetry |
|---|---|---|
| Sharpe ratio | 1.44, a PCA-strategy summary for 1997–2007; 0.9 reported for 2003–2007 | Unknown |
| Break-even transaction cost | Not supplied | Unknown |
| Days traded | Not supplied | Unknown |
| Trading costs | 5 bps per side assumed | Realized cost impact unknown |

The supplied evidence does not identify individual failed evaluations or the underlying bug. Zero passed evaluations does **not** establish zero trades, zero returns, or a negative Sharpe.

**Scope and limitations.** This was a transfer to a fixed 40-stock PCA universe with SPY reserved for hedging, not a replication of the paper’s much broader, changing universe. The claimed 1.44 Sharpe is not a result for this basket, and its exact correspondence to the fixed-15-factor strategy cannot be checked from the supplied table evidence. Telemetry explicitly flags survivorship bias from current index membership.

Material specification gaps remain in the SPY beta hedge, entry-sizing calibration, financing rates, and handling of invalid fits and missing data. Keeping 15 factors in only 40 stocks also changes the residual structure relative to the original universe. Finally, using final daily returns while assuming same-close execution does not establish executable timing; the engine’s one-row return accounting does not resolve that availability limitation.

**Conclusion:** The supplied run provides no verified performance evidence supporting or refuting the reported Sharpe. Its unresolved status and evaluation ineligibility limit this postmortem to implementation and evidence gaps. This is a backtesting assessment, not trading advice.

## Statistical Arbitrage in the U.S. Equities Market — 15-PCA Mean-Reversion Strategy | r_d1b6cda53684 | C

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Variant C

**Recorded status: FAILED_EVAL_2.** One of five evaluations passed. This was a transfer of the 15-factor PCA residual mean-reversion strategy to 40 fixed equities with a SPY hedge, not a replication of the paper’s historical universe.

### Claimed versus measured performance
The supplied paper summary claims an average annual Sharpe of **1.44 for PCA-based strategies over 1997–2007**, with **0.9 for 2003–2007**. Neither figure is a claim for this adapted basket, and the supplied material does not establish the exact fixed-15-factor table correspondence.

Telemetry reports a **verified/OOS Sharpe of 0.0374** over 546 daily rows at 5 bps per side. IS Sharpe was **−0.6972** at the same cost. The friction evaluation also reports annualized return of **−0.70%**, maximum drawdown of **−4.50%**, and average daily turnover of **5.23%** over 1,639 rows. Break-even transaction cost is **unknown**, not zero.

### Evaluation results
- **Lookahead — passed:** Outputs were consistent across five truncated-history checks within a tolerance of \(10^{-9}\). This does not establish that final daily-bar signals were executable at the same close.
- **Friction — failed:** Sharpe was **−0.3676 at zero cost**, **−0.6972 at 5 bps**, and **−1.0262 at 10 bps**, below the required 0.5.
- **Sensitivity — failed:** Tested parameter perturbations produced Sharpes from **−1.0334 to 0.2783**. The worst/base ratio was unavailable, and numerous numeric parameters were not tested.
- **Decay — failed:** OOS Sharpe improved from negative IS performance to near zero, but the concentration check failed: the reported five-day window share was **4.744**, versus a **0.6** limit. The IS concentration metric was unavailable.
- **Deflated Sharpe — failed:** DSR was **0.4472**, below **0.95**. Telemetry lists three trials but only two supplied trial Sharpes, limiting auditability.

### Limitations and conclusion
Current-membership selection introduces survivorship bias, and retaining 15 factors in only 40 stocks materially changes the residual model relative to the paper’s broad, changing universe. Hedge estimation, entry sizing, financing, borrow costs, and invalid-fit handling are incompletely specified; the supplied evidence does not resolve implementation fidelity. Historical adjusted daily bars also do not establish point-in-time availability. No holdout performance is supplied.

The reported transfer did not substantiate the paper-level Sharpe claim: IS performance was negative even before costs, OOS performance was near zero, and four evaluations failed. These are backtest findings, not trading advice.

## Another look at trading costs and short-term reversal profits | r_ffbba23dbcff | A

FAILED_EVAL_2 (1/5)

## Strategy postmortem — Variant A

**Recorded status: FAILED_EVAL_2.** One of five reported evaluations passed. This was a transfer to a fixed 30-stock universe, not a replication of the paper.

### Claim versus measured results
The hypothesis was that five-day reversal portfolios could retain profitability after costs by holding positions until their ranks crossed the median, reducing turnover. The supplied paper summary reports **no Sharpe ratio**, so there is no claimed Sharpe benchmark to verify.

Telemetry reports:
- **IS Sharpe:** 0.438 before costs; **0.244 at 5 bps**.
- **OOS/verified Sharpe:** **−0.451 at 5 bps**, reversing the positive IS result.
- Friction-test annualized return: **2.06%**; maximum drawdown: **−20.96%**; average daily turnover: **32.98%**.

Break-even cost is **unknown**, not zero. The reported note—“below 0.5 at 0 bps”—refers to the evaluation’s Sharpe hurdle, not a measured profitability break-even. No unbuffered comparator was supplied, so the claimed turnover reduction was not directly demonstrated.

### Evaluation outcomes
- **Lookahead — passed:** prefix checks found no inconsistency at the tested cuts. This does not establish point-in-time daily-data availability.
- **Friction — failed:** Sharpe at 5 bps was 0.244 versus the required 0.5; even zero-cost Sharpe was below that hurdle.
- **Sensitivity — failed:** worst perturbed Sharpe was 0.021, only **8.6%** of baseline versus a required 50%. Gross exposure was not jittered.
- **Decay — failed:** OOS/IS Sharpe ratio was **−1.85**. The IS five-day concentration statistic was **95.1%**, above the 60% limit; its OOS counterpart was unavailable.
- **Deflated Sharpe — failed:** reported DSR was **0.223**, below 0.95, using three supplied trials.

### Limitations and conclusion
The fixed, current-membership universe carries survivorship and selection bias and differs materially from the paper’s historical universes. Adjusted daily histories are not point-in-time data; the skipped-day alignment does not guarantee executable close prices. Historical cost models were not replicated, while borrow, financing, eligibility and replacement conventions remain incompletely specified.

Activity was substantial—1,633 IS and 546 OOS target-active days—but activity is not evidence of profitability. The supplied telemetry does **not support robust after-cost performance for this transfer**. These are historical backtest findings, not trading advice.

## Another look at trading costs and short-term reversal profits | r_ffbba23dbcff | B

FAILED_EVAL_2 (1/5)

### Variant B: strategy postmortem

**Recorded status: `FAILED_EVAL_2`; one of five evaluations passed.** This was a transfer of the paper’s buffered short-term reversal strategy to a fixed 30-stock daily universe, not a replication.

**Claim versus measurement.** The source hypothesis is that retaining positions until their ranks cross the median reduces turnover enough to preserve profits after costs. No paper Sharpe was supplied, so a numerical Sharpe comparison is unavailable. Reported telemetry shows an IS Sharpe of **0.525 without friction**, falling to **0.287 at 5 bps**, and an OOS/verified Sharpe of **−0.365**. Average daily turnover was **0.422**. The friction evaluation also reported annualized return of **2.62%** and maximum drawdown of **−22.44%**.

**Evaluation results**
- **Lookahead passed** the reported prefix-consistency checks. This does not establish point-in-time daily-data availability.
- **Friction failed:** Sharpe at 5 bps was **0.287**, below the **0.50** requirement. The reported interpolated “break-even” value of **0.533 bps** appears to describe the evaluation threshold, not zero profitability: Sharpe remained positive at 10 bps.
- **Sensitivity failed:** worst tested Sharpe was **0.026**, only **8.9%** of the base result, versus a required 50%. Several numeric parameters were not jittered.
- **Decay failed:** OOS Sharpe turned negative; IS five-day-window concentration was **87.0%**, above the 60% limit. OOS concentration was unknown.
- **Deflated Sharpe failed:** the reported statistic was **0.263**, below **0.95**, using three supplied trials and 546 observations.

**Limitations.** Current-membership selection creates survivorship and selection bias. Historical constituent membership, exact paper cost models, borrow and financing costs, and point-in-time adjusted histories were unavailable or incompletely modeled. Daily availability, eligibility, tie-breaking, and retained-position sizing also limit replication fidelity. The supplied evidence therefore does not substantiate robust after-cost performance for this adaptation; it does not resolve the paper’s original results.

*Backtesting only—not trading advice.*

## Another look at trading costs and short-term reversal profits | r_ffbba23dbcff | C

FAILED_EVAL_2 (1/5)

### Strategy postmortem — Variant C

**Recorded status: FAILED_EVAL_2.** One of five evaluations passed. This was a transfer to a fixed 30-stock universe, not a replication of the paper.

The strategy buys five-day losers and shorts winners after a one-session skip, retaining positions until their ranks cross the median. The intended six-stock legs use equal weights at 200% gross and zero net exposure.

**Claims versus measured results.** The supplied paper summary argues that exit buffers can preserve reversal profits after transaction costs, but provides no claimed Sharpe ratio. Its historical universes and cost models differ from this adaptation. Telemetry reports an OOS Sharpe of **−0.512** at 5 bps, versus **0.163** in sample. In the friction evaluation, Sharpe declined from **0.390 at zero cost** to **0.163 at 5 bps** and **−0.064 at 10 bps**. That evaluation also reported annualized return of **1.04%**, maximum drawdown of **−20.00%**, and average daily turnover of **0.312**. Break-even cost is unknown; the recorded note says Sharpe was already below the required 0.5 at zero cost.

**Evaluation outcomes**
- **Lookahead: passed** the supplied truncation checks. This does not establish point-in-time availability of historical daily data.
- **Friction: failed** the 0.5 minimum-Sharpe requirement.
- **Sensitivity: failed:** worst perturbed Sharpe was **−0.092**, versus the 0.163 base. Several numeric parameters were not tested.
- **Decay: failed:** OOS Sharpe turned negative. Concentration was also marked failed; the OOS concentration metric is unknown.
- **Deflated Sharpe: failed:** **0.197**, below the **0.95** threshold, using three supplied trials.

**Limitations.** Current-membership selection introduces survivorship bias. Historical constituent membership, exact paper transaction costs, borrow and financing costs, and point-in-time adjusted histories are unavailable or incompletely modeled. Eligibility, tie-breaking, replacement ordering, and retained-position sizing remain partly unspecified. No unbuffered comparison is supplied, so the buffer’s incremental turnover benefit cannot be established.

The supplied evidence does not support robust net profitability for this transfer. This is a backtest assessment, not trading advice.

## Market intraday momentum — first-half-hour sign timing | r_55eebea2c07d | A

FAILED_EVAL_2 (1/5)

Qualitative review questions (model-selected; fixed wording):

- Which observation and execution conventions need reconciliation with the source paper?
- Are the required inputs available when each signal is formed?
- Which transaction-cost assumptions need comparison with the source?

## Market intraday momentum — first-half-hour sign timing | r_55eebea2c07d | B

FAILED_EVAL_2 (1/5)

Qualitative review questions (model-selected; fixed wording):

- Which observation and execution conventions need reconciliation with the source paper?
- Are the required inputs available when each signal is formed?
- How do corporate-action conventions affect comparability with the source?

## Market intraday momentum — first-half-hour sign timing | r_55eebea2c07d | C

FAILED_EVAL_2 (1/5)

Qualitative review questions (model-selected; fixed wording):

- Which observation and execution conventions need reconciliation with the source paper?
- Are the required inputs available when each signal is formed?
- Which transaction-cost assumptions need comparison with the source?

## Congress purchase basket vs SPY | r_a0a8786ea3ff | A

BUG_UNRESOLVED (0/5)

Qualitative review questions (model-selected; fixed wording):

- Are the required inputs available when each signal is formed?
- How does the available asset universe compare with the paper's sample?
- Which observation and execution conventions need reconciliation with the source paper?

## Congress purchase basket vs SPY | r_a0a8786ea3ff | B

BUG_UNRESOLVED (0/5)

Qualitative review questions (model-selected; fixed wording):

- Are the required inputs available when each signal is formed?
- How does the available asset universe compare with the paper's sample?
- Which parameter interpretations remain ambiguous in the specification?

## Congress purchase basket vs SPY | r_a0a8786ea3ff | C

BUG_UNRESOLVED (0/5)

Qualitative review questions (model-selected; fixed wording):

- Are the required inputs available when each signal is formed?
- How does the available asset universe compare with the paper's sample?
- Which parameter interpretations remain ambiguous in the specification?
