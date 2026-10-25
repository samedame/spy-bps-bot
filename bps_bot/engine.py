"""The decision engine: one trading day in, state + events out.

`step()` is a line-for-line port of the code path that `run_spread()` in research/code/01_engine.py takes for the spec
BP_d40_D14_W5_PT50_SL2 (manage the open position, then consider an entry, all at today's close). It is pure: it never
reads a clock, a file or the network, so the live runner and the verification replay call exactly the same function.
"""
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Callable, List, Optional, Tuple

from . import calendar_nyse as CAL
from .pricing import (fill_cashflow, intrinsic_cashflow, max_loss_with_credit, strike_for_delta)
from .spec import SPEC, Spec


@dataclass(frozen=True)
class Bar:
    """One trading day's closing marks. tnx_pct is the 10y yield in percent (^TNX), exactly as in the research data."""
    date: date
    close: float          # SPY unadjusted close
    vix: float
    tnx_pct: float
    provisional: bool = False


@dataclass
class Position:
    entry_date: str
    expiry_date: str
    short_k: int
    long_k: int
    n: int
    entry_cf: float       # total cash flow at entry, dollars, after modeled slippage and fees
    credit0: float
    debit0: float
    maxloss: float        # max loss of the whole position, dollars
    vix0: float
    entry_spot: float


@dataclass
class State:
    cash: float
    position: Optional[Position] = None
    last_date: Optional[str] = None   # last trading day this state has processed

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "State":
        p = d.get("position")
        return State(cash=float(d["cash"]), position=Position(**p) if p else None, last_date=d.get("last_date"))


@dataclass
class EntryPlan:
    short_k: int
    long_k: int
    expiry: date
    days: int
    credit_per_lot: float   # cash flow for 1 spread after modeled slippage and fees (dollars)
    max_loss_per_lot: float  # dollars, includes the credit
    spot: float
    vix: float
    rate: float


def rate_from(bar: Bar, sp: Spec = SPEC) -> float:
    return max(float(bar.tnx_pct) / 100.0, sp.rate_floor)


def plan_entry(bar: Bar, expiry_cap: Optional[date] = None, sp: Spec = SPEC) -> Optional[EntryPlan]:
    """Strikes, expiry, modeled credit and max loss for a spread opened at this bar (no sizing)."""
    S, vix, r, q, today = bar.close, bar.vix, rate_from(bar, sp), sp.div_yield, bar.date
    e = CAL.on_or_after(today + timedelta(days=sp.dte))
    e = max(e, CAL.next_trading_day(today))
    if expiry_cap is not None:
        e = min(e, expiry_cap)   # replay-only: the research engine caps expiry at the last bar of its data
    if e <= today:
        return None
    ks = strike_for_delta(S, sp.dte, r, q, vix, sp.delta, sp)
    kl = max(round(ks - sp.width_frac * S), 1)
    days = (e - today).days
    legs = [(-1, ks), (1, kl)]
    cf1 = fill_cashflow(legs, S, r, q, vix, [days, days], sp, opening=True)
    ml = max_loss_with_credit(legs, cf1)
    return EntryPlan(ks, kl, e, days, cf1, ml, S, vix, r)


def lots_for(equity: float, max_loss_per_lot: float, sp: Spec = SPEC) -> int:
    if not (max_loss_per_lot > 0):
        return 0
    return int((sp.risk_frac * equity) // max_loss_per_lot)


def is_entry_day(today: date, prev_trading_day: date) -> bool:
    """First trading day of the week: today's weekday is not after the previous trading day's weekday."""
    return today.weekday() <= prev_trading_day.weekday()


def position_legs(pos: Position):
    return [(-pos.n, pos.short_k), (pos.n, pos.long_k)]


def mark_pnl(pos: Position, bar: Bar, sp: Spec = SPEC) -> float:
    """Open P&L if the whole position were closed now at modeled bid/ask (what the exit rules look at)."""
    exp = date.fromisoformat(pos.expiry_date)
    dd = max((exp - bar.date).days, 0)
    close_cf = fill_cashflow(position_legs(pos), bar.close, rate_from(bar, sp), sp.div_yield, bar.vix, [dd, dd], sp, opening=False)
    return pos.entry_cf + close_cf


def equity_mtm(state: State, bar: Bar, sp: Spec = SPEC) -> float:
    """Cash plus the modeled liquidation value of any open position (the research's daily equity curve)."""
    if state.position is None:
        return state.cash
    pos = state.position
    exp = date.fromisoformat(pos.expiry_date)
    dd = max((exp - bar.date).days, 0)
    liq = fill_cashflow(position_legs(pos), bar.close, rate_from(bar, sp), sp.div_yield, bar.vix, [dd, dd], sp, opening=False)
    return state.cash + liq


def step(state: State, bar: Bar, prev_trading_day: date, *, allow_entry: bool = True,
         expiry_cap: Optional[date] = None, sp: Spec = SPEC) -> Tuple[State, List[dict]]:
    """Process one trading day. Returns (new_state, events); the input state is not modified.

    Order, as in the research engine: (1) if a position is open, settle it at expiry, else test profit target then stop at
    today's modeled close; (2) if flat, and today is the first trading day of the week, open a new spread sized by
    floor(risk_frac x cash / max_loss). A position closed today can be replaced today.
    """
    cash = state.cash
    pos = copy.copy(state.position) if state.position is not None else None
    events: List[dict] = []
    S, vix, r, q, today = bar.close, bar.vix, rate_from(bar, sp), sp.div_yield, bar.date

    if pos is not None:
        exp = date.fromisoformat(pos.expiry_date)
        legs = position_legs(pos)
        close_now, reason = False, ""
        if today >= exp:
            close_now, reason = True, "expiry"
        else:
            dd = max((exp - today).days, 0)
            close_cf = fill_cashflow(legs, S, r, q, vix, [dd, dd], sp, opening=False)
            pnl_now = pos.entry_cf + close_cf
            c0, d0 = pos.credit0, pos.debit0
            pt, sl = sp.profit_target, sp.stop_mult
            if c0 > 0 and pt is not None and pnl_now >= pt * c0:
                close_now, reason = True, "profit_target"
            elif c0 > 0 and sl is not None and pnl_now <= -sl * c0:
                close_now, reason = True, "stop_loss"
            elif d0 > 0 and pt is not None and pnl_now >= pt * d0:
                close_now, reason = True, "profit_target"
            elif d0 > 0 and sl is not None and pnl_now <= -sl * d0:
                close_now, reason = True, "stop_loss"
        if close_now:
            if reason == "expiry":
                cf = intrinsic_cashflow(legs, S)
                if any(abs(S - K) / S < sp.pin_pct and qty < 0 for qty, K in legs):
                    cf -= sp.pin_fee * sum(abs(qty) for qty, _ in legs)
            else:
                dd = max((exp - today).days, 0)
                cf = fill_cashflow(legs, S, r, q, vix, [dd, dd], sp, opening=False)
            pnl = pos.entry_cf + cf
            cash += cf
            trade = dict(entry=pos.entry_date, exit=today.isoformat(), pnl=pnl, risk=pos.maxloss,
                         ror=pnl / pos.maxloss if pos.maxloss > 0 else float("nan"), reason=reason, vix_entry=pos.vix0,
                         credit=pos.credit0, debit=pos.debit0, contracts=pos.n,
                         short_k=pos.short_k, long_k=pos.long_k, expiry=pos.expiry_date)
            events.append(dict(type="exit", reason=reason, trade=trade, short_k=pos.short_k, long_k=pos.long_k,
                               expiry=pos.expiry_date, n=pos.n, pnl=pnl, cash_flow=cf, spot=S))
            pos = None

    if pos is None and allow_entry and is_entry_day(today, prev_trading_day):
        plan = plan_entry(bar, expiry_cap, sp)
        if plan is not None and plan.max_loss_per_lot > 0:
            sizing_equity = cash
            n = lots_for(cash, plan.max_loss_per_lot, sp)
            if n >= 1:
                ecf = plan.credit_per_lot * n
                cash += ecf
                pos = Position(entry_date=today.isoformat(), expiry_date=plan.expiry.isoformat(), short_k=plan.short_k,
                               long_k=plan.long_k, n=n, entry_cf=ecf, credit0=max(ecf, 0.0), debit0=max(-ecf, 0.0),
                               maxloss=plan.max_loss_per_lot * n, vix0=vix, entry_spot=S)
                events.append(dict(type="entry", n=n, plan=plan, short_k=plan.short_k, long_k=plan.long_k,
                                   expiry=plan.expiry.isoformat(), spot=S, vix=vix, cash_flow=ecf,
                                   sizing_equity=sizing_equity))
            else:
                events.append(dict(type="entry_skipped", why="lot_size", plan=plan, short_k=plan.short_k,
                                   long_k=plan.long_k, expiry=plan.expiry.isoformat(),
                                   sizing_equity=sizing_equity, budget=sp.risk_frac * sizing_equity, spot=S, vix=vix))

    return State(cash=cash, position=pos, last_date=today.isoformat()), events
