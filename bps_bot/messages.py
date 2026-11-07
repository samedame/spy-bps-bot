"""Discord message text. Every message says what happened, what (if anything) to do, and by when. Alert-only: no orders are placed."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from .engine import EntryPlan, Position, lots_for, mark_pnl
from .spec import SPEC

DISCORD_LIMIT = 2000
LABEL = ("`BP_d40_D14_W5_PT50_SL2` - research label PROMISING (proxy prices, capped), confidence LOW. "
         "Educational, not financial advice; options can lose more than the credit received.")


def fit_discord(text: str, limit: int = DISCORD_LIMIT) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 40].rstrip()
    return cut + "\n... (message shortened to fit Discord)"


def _d(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%a %b %d")


def _money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def entry_alert(plan: EntryPlan, n_paper: int, paper_equity: float, user_equity: Optional[float], provisional: bool) -> str:
    ps = plan.credit_per_lot / 100.0
    tp_cost = ps * (1 - SPEC.profit_target)
    sl_cost = ps * (1 + SPEC.stop_mult)
    n_user = lots_for(user_equity, plan.max_loss_per_lot) if user_equity else None
    when = "provisional read, about 3:45 pm ET - send before the 4:00 pm close (SPY options trade to 4:15)" if provisional else "official close"
    lines = [
        f"**SPY BULL PUT SPREAD - ENTRY** ({when})",
        f"**Per spread: SELL 1 SPY {_d(plan.expiry.isoformat())} {plan.short_k}P / BUY 1 SPY {_d(plan.expiry.isoformat())} {plan.long_k}P** (one credit-spread order; spreads per the sizing line)",
        f"SPY {plan.spot:,.2f} | VIX {plan.vix:.2f} | {plan.days} days to expiry | width ${plan.short_k - plan.long_k}",
        f"Model credit about ${ps:.2f}/share (after the research's pessimistic fills) | max loss about {_money(plan.max_loss_per_lot)} per spread",
    ]
    sizing = f"Sizing rule (2% of equity / max loss, whole spreads): paper ledger {_money(paper_equity)} -> {n_paper} spread(s)"
    if n_user is not None:
        sizing += f"; your account {_money(user_equity)} -> {n_user} spread(s)"
        if n_user == 0:
            sizing += ". **0 = the tested rule cannot hold even one spread at your size - follow on paper only.**"
    lines.append(sizing)
    lines += [
        f"Once filled: close if you can buy it back for about ${tp_cost:.2f} or less (+50% of credit) or if buy-back reaches about ${sl_cost:.2f} (-200%); otherwise hold to expiry. The bot checks every close.",
        "Compare live bid/ask first: the credit above is a Black-Scholes proxy, not a quote. No order has been placed by the bot.",
        LABEL,
    ]
    return fit_discord("\n".join(lines))


def entry_skipped_alert(plan: EntryPlan, paper_equity: float, budget: float, user_equity: Optional[float], provisional: bool) -> str:
    when = "provisional 3:45 pm ET read" if provisional else "official close"
    lines = [
        f"**SPY BULL PUT SPREAD - entry day, NO SIZE** ({when})",
        f"The rule set would sell the {plan.short_k}P / buy the {plan.long_k}P expiring {_d(plan.expiry.isoformat())} (SPY {plan.spot:,.2f}, VIX {plan.vix:.2f}), "
        f"but one spread risks about {_money(plan.max_loss_per_lot)} and the 2% budget on the paper ledger ({_money(paper_equity)}) is {_money(budget)}. "
        "Whole spreads only, so the tested rule skips this week.",
    ]
    if user_equity:
        lines.append(f"Your account {_money(user_equity)} -> {lots_for(user_equity, plan.max_loss_per_lot)} spread(s) under the same rule.")
    lines.append("Nothing to do. (The tested out-of-sample run skipped 66 such weeks at $100k.)")
    return fit_discord("\n".join(lines))


def exit_alert(ev: dict, provisional: bool) -> str:
    reason = ev["reason"]
    head = {"profit_target": "CLOSE - profit target hit", "stop_loss": "CLOSE - stop hit", "expiry": "EXPIRY DAY"}[reason]
    when = "provisional 3:45 pm ET read" if provisional else "official close"
    t = ev["trade"]
    lines = [f"**SPY BULL PUT SPREAD - {head}** ({when})",
             f"Model position: {ev['n']} x {ev['short_k']}P/{ev['long_k']}P, expiry {_d(ev['expiry'])}, opened {_d(t['entry'])}. SPY {ev['spot']:,.2f}."]
    if reason == "expiry":
        lines.append("Model settles at the cash intrinsic value today. If you hold the real spread and SPY is below your short strike, "
                     "close it as one order before 4:00 pm ET (SPY is American-style: a short put in the money can be assigned).")
    else:
        lines.append("If you hold this spread: buy back the short put and sell the long put as ONE order before the close.")
    lines.append(f"Model result: {_money(ev['pnl'])} on this trade ({t['ror'] * 100:+.1f}% of max risk).")
    return fit_discord("\n".join(lines))


def status_line(d: date, pos: Optional[Position], bar, paper_equity: float, next_entry: date) -> str:
    if pos is None:
        return fit_discord(f"SPY-BPS {d:%a %b %d} close: no action. Flat, paper ledger {_money(paper_equity)}. Next entry check: {next_entry:%a %b %d}.")
    pnl = mark_pnl(pos, bar)
    ps = pos.credit0 / (pos.n * 100)
    return fit_discord(f"SPY-BPS {d:%a %b %d} close: no action. Holding {pos.n} x {pos.short_k}P/{pos.long_k}P exp {_d(pos.expiry_date)}; "
                       f"open P&L {_money(pnl)}; exits at +{_money(SPEC.profit_target * pos.credit0)} (target) or {_money(-SPEC.stop_mult * pos.credit0)} (stop); "
                       f"paper cash {_money(paper_equity)}.")


def difference_notice(alert_said: str, final_says: str) -> str:
    return fit_discord("**SPY-BPS: after-close check differs from the 3:45 pm alert.**\n"
                       f"3:45 pm alert: {alert_said}\nOfficial close: {final_says}\n"
                       "The paper ledger follows the official close. If you traded the alert, compare your fill with the official-close strikes.")


def error_notice(what: str, how_to_fix: str) -> str:
    return fit_discord(f"**SPY-BPS ERROR - {what}**\n{how_to_fix}\nThe paper ledger was NOT changed by this failed step.")


def missed_window_notice(started_et: str, window: str) -> str:
    return fit_discord(
        f"**SPY-BPS - MISSED WINDOW, no alert sent today.** The alert run started at {started_et} ET, after the "
        f"{window} ET window it needs, and no earlier run covered today. If the rules might act at today's close "
        f"(an entry or exit day), check SPY, VIX and the 10-year yield by hand. The after-close run still updates the "
        f"paper ledger. (One notice per day.)")
