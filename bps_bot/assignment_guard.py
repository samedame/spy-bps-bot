"""ADVISORY-ONLY assignment-risk line.

SPY options are American-style and physically settled. A short put that is in the money and has almost no time value can be
exercised at any time; if the long put is out of the money, the assignment leaves an unhedged share position (a weekend gap
then lands on shares, not on a capped spread). This module only *describes* that risk in one extra Discord message.

It never changes entry, exit, sizing, the paper ledger, pending-alert signatures or the spec fingerprint (`spec_hash`).
Turn it off with ASSIGNMENT_GUARD=0. With it off, alerts and ledger files are byte-identical to the unguarded bot
(tests/test_assignment_guard.py::test_guard_off_is_byte_identical_to_baseline).

Inputs are the bot's own modeled prices (Black-Scholes proxy), so the extrinsic value is a MODEL number, labelled as such.
The ex-dividend date is an ESTIMATE (third Friday of Mar/Jun/Sep/Dec), labelled as such.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Optional

from . import calendar_nyse as CAL
from .pricing import leg_mid
from .spec import SPEC

ENV = "ASSIGNMENT_GUARD"
EXTRINSIC_MAX = 0.05        # dollars per share: below this, an in-the-money short put has no reason to be held by its owner
EXDIV_WINDOW_DAYS = 3       # flag when an estimated ex-dividend date is this close
CLOSE_BY = "15:55 ET"


def enabled() -> bool:
    return os.environ.get(ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def _third_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(days=14)


def next_exdiv_estimate(today: date) -> date:
    """SPY pays quarterly; ex-dates fall around the third Friday of Mar/Jun/Sep/Dec. Estimate only."""
    for y in (today.year, today.year + 1):
        for m in (3, 6, 9, 12):
            d = _third_friday(y, m)
            if d >= today:
                return d
    raise AssertionError("unreachable")


def assess(position, bar, today: date, next_session: date, rate: float) -> Optional[dict]:
    """None unless the short put is in the money AND (extrinsic < $0.05, or expiry is today/next session, or ex-div is near)."""
    if position is None or not bar.close < position.short_k:
        return None
    exp = date.fromisoformat(position.expiry_date)
    dte = max((exp - today).days, 0)
    intrinsic = position.short_k - bar.close
    extrinsic = max(leg_mid(position.short_k, bar.close, rate, SPEC.div_yield, bar.vix, dte) - intrinsic, 0.0)
    exdiv_days = (next_exdiv_estimate(today) - today).days
    reasons = []
    if extrinsic < EXTRINSIC_MAX:
        reasons.append("almost no time value left")
    if exp <= next_session:
        reasons.append("expires today or next session")
    if exdiv_days <= EXDIV_WINDOW_DAYS:
        reasons.append("ex-dividend is near")
    if not reasons:
        return None
    return dict(short_k=position.short_k, long_k=position.long_k, n=position.n, spot=bar.close, itm_by=intrinsic, extrinsic=extrinsic,
                exdiv_days=exdiv_days, dte=dte, reasons=reasons)


def message(a: dict) -> str:
    shares = int(a["n"] * 100)
    return (f"ASSIGNMENT RISK: short leg ITM, extrinsic ${a['extrinsic']:.2f} (modeled), ex-div in {a['exdiv_days']} days (est.), "
            f"close/roll before {CLOSE_BY} today\n"
            f"SPY {a['spot']:,.2f} is {a['itm_by']:.2f} below the {a['short_k']}P short ({a['reasons'][0]}; {a['dte']} days to expiry). "
            f"SPY options are American-style: if the {a['short_k']}P is assigned while the {a['long_k']}P is out of the money, you hold up to "
            f"{shares:,} shares with no cap on a gap. Advisory only: the paper ledger and the rules are unchanged.")
