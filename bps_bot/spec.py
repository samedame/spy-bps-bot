"""The frozen rule set. Every number here comes from the research (PREREGISTRATION.md sections 2, 4, 5 and
VERDICT.md). Nothing in this file was tuned for the bot.

Spec id: BP_d40_D14_W5_PT50_SL2  (SPY 40-delta / 14-DTE bull put spread, 5% wide, PT 50%, SL 2x credit).

SPEC_HASH is a fingerprint of every field. VERIFIED_SPEC_HASH is the fingerprint that the verification suite
(verification/VERIFICATION_REPORT.md) was run against. The bot refuses to run if they differ, so a parameter cannot
drift away from what was verified without someone noticing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Spec:
    spec_id: str = "BP_d40_D14_W5_PT50_SL2"
    underlying: str = "SPY"
    # --- structure (VERDICT.md "Exact rules as tested") ---
    delta: float = 0.40              # short put target |delta|
    dte: int = 14                    # calendar days to expiry at entry
    width_frac: float = 0.05         # long put = short strike - 5% of spot, $1 strike increments
    cadence: str = "first_trading_day_of_week_if_flat"
    # --- exits, checked at each daily close ---
    profit_target: float = 0.50      # close at +50% of net credit
    stop_mult: float = 2.0           # close at -200% of net credit (fills at the evaluated close, never at the stop)
    time_exit: str = "none"          # hold to expiry settlement; no rolls
    # --- sizing ---
    risk_frac: float = 0.02          # whole lots = floor(2% x equity / max loss); one position at a time
    # --- pricing proxy (PREREGISTRATION section 4) ---
    div_yield: float = 0.015
    vix_floor: float = 0.05
    iv_term_slope: float = 0.04
    iv_floor: float = 0.08
    skew_down: float = 0.35
    skew_up: float = 0.10
    rate_floor: float = 0.0          # r = max(TNX/100, 0)
    bisect_iters: int = 48
    bisect_lo: float = 0.3
    bisect_hi: float = 1.7
    # --- costs (PREREGISTRATION section 5, primary = pessimistic) ---
    slip_frac: float = 1.0           # 100% of the modeled half-spread: sell at bid, buy at ask
    hs_floor: float = 0.02
    hs_pct: float = 0.02
    hs_add: float = 0.01
    hs_far_mult: float = 1.5
    far_log_moneyness: float = 0.10
    fee_commission: float = 0.65     # per contract per leg
    fee_regulatory: float = 0.02
    pin_pct: float = 0.0025          # expiry within 0.25% of a short strike ...
    pin_fee: float = 25.0            # ... costs $25 per contract-leg (conservative friction)

    @property
    def fee_per_leg(self) -> float:
        return self.fee_commission + self.fee_regulatory


SPEC = Spec()


def spec_hash(spec: Spec = SPEC) -> str:
    return hashlib.sha256(json.dumps(asdict(spec), sort_keys=True).encode()).hexdigest()


# Fingerprint the verification suite ran against (set by verification/run_all.py when it passes; see the report).
VERIFIED_SPEC_HASH = "40a007e6d8b8eb17c0d2076d78f837a93a926ede18e7f09357c92f807d10c196"

# Equity of the research's continuous 2008-01 .. 2026-10-23 run at the primary 2% sizing (results/winner_equity_risk2.csv,
# last row). The paper ledger continues that exact run, flat, from 2026-10-23.
RESEARCH_FULL_RUN_FINAL_EQUITY = 161549.82982224415
RESEARCH_DATA_END = "2026-10-23"
