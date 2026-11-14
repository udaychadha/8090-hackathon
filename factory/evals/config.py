"""Every eval threshold lives here. The owner may change these; agents may not.

Values are the proposed thresholds from AGENTS.md ("Strategy evals"). Do not
tune them to make a strategy or a fixture pass.
"""

# Shared
BASE_COST_BPS = 5.0  # round-trip cost used by Evals 2 (pass rule), 3, 4, 5

# Eval 1 — lookahead
LOOKAHEAD_CUT_FRACTIONS = (0.30, 0.45, 0.60, 0.75, 0.90)  # of IS timestamps
LOOKAHEAD_TOLERANCE = 1e-9  # max abs weight difference

# Eval 2 — friction
FRICTION_BPS_GRID = (0.0, 2.0, 5.0, 10.0)  # round trip
FRICTION_MIN_SHARPE = 0.5  # net annualised Sharpe required at BASE_COST_BPS

# Eval 3 — sensitivity
SENSITIVITY_JITTERS = (-0.20, -0.10, 0.10, 0.20)
SENSITIVITY_MAX_PARAMS = 4
SENSITIVITY_MIN_RATIO = 0.5  # worst jittered Sharpe / base Sharpe

# Eval 4 — decay
DECAY_MIN_RATIO = 0.5  # OOS Sharpe / IS Sharpe
CONCENTRATION_WINDOW_DAYS = 5
CONCENTRATION_MAX_SHARE = 0.60  # of total PnL in any one window

# Eval 5 — deflated Sharpe
DSR_MIN = 0.95
DSR_MIN_TRIALS = 3  # floor on N
