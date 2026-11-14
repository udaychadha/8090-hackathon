# Eval 4/5 recorded-metric rejudgment

Revision: `2026-11-14-eval45-global-v2`. Selected global trials: **13**.
No strategy executions, backtests, data downloads or model calls.

| Variant | Before status | Before passed | After status | After passed |
| --- | --- | --- | --- | --- |
| r_17ac8caf8a59_A | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_17ac8caf8a59_B | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_17ac8caf8a59_C | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_449ef7fd3ae6_A | VOID | 0/5 | VOID | 0/5 |
| r_449ef7fd3ae6_B | VOID | 0/5 | VOID | 0/5 |
| r_449ef7fd3ae6_C | VOID | 0/5 | VOID | 0/5 |
| r_55eebea2c07d_A | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_55eebea2c07d_B | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_55eebea2c07d_C | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_b8116b8c72ef_A | INACTIVE | 0/5 | INACTIVE | 0/5 |
| r_b8116b8c72ef_B | INACTIVE | 0/5 | INACTIVE | 0/5 |
| r_b8116b8c72ef_C | INACTIVE | 0/5 | INACTIVE | 0/5 |
| r_d1b6cda53684_A | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_d1b6cda53684_B | BUG_UNRESOLVED | 0/5 | BUG_UNRESOLVED | 0/5 |
| r_d1b6cda53684_C | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_e7094212a558_A | INACTIVE | 0/5 | INACTIVE | 0/5 |
| r_e7094212a558_B | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_e7094212a558_C | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_ffbba23dbcff_A | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_ffbba23dbcff_B | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |
| r_ffbba23dbcff_C | FAILED_EVAL_2 | 1/5 | FAILED_EVAL_2 | 1/5 |

Voided variants remain VOID and excluded. Inactive/bug variants with no
recorded Eval 4/5 remain unevaluated; no missing metric was invented.

Concentration uses the sum of daily net returns. A positive-total share
can exceed one when other windows lose money; it remains a failure.
Nonpositive/unknown total PnL is not applicable (null), never a pass.

Backup: `runs/rejudge-backup-2026-11-14T191511422929Z`.
Original event lines are retained; explicit rejudgment events follow them.

## Findings and verification

- All 21 variants are listed above. Aggregate results did not change: 13
  FAILED_EVAL_2 (1/5), 4 INACTIVE (0/5), 1 BUG_UNRESOLVED (0/5), and 3 VOID (0/5).
- Avellaneda variants `r_d1b6cda53684_A` and `r_d1b6cda53684_C` had
  `sharpe_ok=true` despite negative IS Sharpe. Both now record false; their
  overall Eval 4 was already failed. Nonpositive IS also makes the OOS/IS
  ratio not applicable.
- Every retained Eval 5 now records N=13, the exact same 13 eligible variant
  IDs and daily OOS Sharpe sample variance **0.030124678266460633**. Prior
  judgments used N=3. Repeat runs remain distinct trials. VOID/control trials
  are excluded. The unchanged configured minimum N still applies.
- C's OOS concentration share **4.744168460532077** has a positive period
  total. It is retained and fails the 0.6 cap. It is not evidence of a
  nonpositive denominator. Legacy Sharpe establishes a period's PnL sign;
  no unrecorded PnL amount was reconstructed or invented. Future runs store
  summed daily net returns explicitly.
- Updated 16 variants with recorded Evals 4/5 and 32 eval records. Five
  variants have no such metrics; their inactivity/bug outcomes stay unchanged.
  Original events, critic narratives and all other research evidence remain
  intact. Historical model narratives can contain the earlier metrics; the
  interface labels them unverified and shows current deterministic metrics above.
- 409 Python tests passed, including all stored-data checks; 18 frontend
  tests, the production build, Ruff and Prettier passed. Existing dependency
  deprecation warnings remain.
- Record/mirror audit: **0 mismatches**. **146** checks against the backup
  passed, including unchanged Evals 1–3, code, equity, activity, source data,
  costs, original VOID evidence and the original 311 event lines. There are
  now 343 event lines, with 32 explicit revision events. Repeating the plan
  produces zero changes.
- All 21 variant API responses match the revised records. Browser checks
  confirmed the positive-IS rule, global trial count, retained concentration
  and audit-report access with no browser errors. Screenshots:
  [tearsheet](eval45-tearsheet.png), [rules](eval45-rules.png).
- `factory/evals/config.py` and the strategy contract are byte-for-byte
  unchanged. The protected hash report retains the old hashes and records
  the three authorized changes: decay, deflated Sharpe and eval runner.

Machine-readable evidence: [rejudgment](eval45-rejudgment.json),
[checks](eval45-proof.json), [record audit](eval45-record-audit.json), and
[protected hashes](wo08-protected-files.json). The Data screen exposes this
revision and its backups in explicit audit mode.
