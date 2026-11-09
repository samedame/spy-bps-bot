"""Scenarios for the assignment-guard differential test: positions that are in the money at the 3:45 pm alert.
Returns every Discord message and every ledger file, so a run with the guard OFF can be compared byte-for-byte with the baseline golden file."""
import json, os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from bps_bot import run as R
from bps_bot import calendar_nyse as CAL
from bps_bot.engine import Position, State
from bps_bot.ledger import Ledger

ET = ZoneInfo("America/New_York")


class FakeFeed:
    def __init__(self, spy, vix, tnx, live):
        self.s = {"SPY": spy, "^VIX": vix, "^TNX": tnx}; self.live = live; self.now = None
    def daily_closes(self, symbol, start, end): return {d: v for d, v in self.s[symbol].items() if start <= d <= end}
    def live_quote(self, symbol):
        if symbol not in self.live: raise R.DataUnavailable("no live " + symbol)
        return self.live[symbol], self.now - timedelta(minutes=1)


class Hook:
    def __init__(self): self.sent = []
    def post(self, text): self.sent.append(text)


def et(y, m, d, hh, mm): return datetime(y, m, d, hh, mm, tzinfo=ET).astimezone(timezone.utc)


def series(start, end, f):
    out, d = {}, start
    while d <= end:
        if CAL.is_trading_day(d): out[d] = f(d)
        d += timedelta(days=1)
    return out


def position(expiry):
    return Position(entry_date="2026-10-26", expiry_date=expiry, short_k=700, long_k=665, n=3, entry_cf=1200.0, credit0=1200.0, debit0=0.0,
                    maxloss=9300.0, vix0=19.0, entry_spot=760.0)


SCENARIOS = {
    "itm_on_expiry_day": dict(expiry="2026-11-06", last="2026-11-05", live=650.0, now=(2026, 11, 6, 15, 45), spy_prev=690.0),
    "deep_itm_midlife": dict(expiry="2026-11-20", last="2026-11-05", live=650.0, now=(2026, 11, 6, 15, 45), spy_prev=655.0),
    "itm_day_before_expiry": dict(expiry="2026-11-09", last="2026-11-05", live=698.5, now=(2026, 11, 6, 15, 45), spy_prev=699.0),
    "otm_midlife": dict(expiry="2026-11-20", last="2026-11-05", live=750.0, now=(2026, 11, 6, 15, 45), spy_prev=752.0),
    "shallow_itm_midlife": dict(expiry="2026-11-20", last="2026-11-05", live=698.0, now=(2026, 11, 6, 15, 45), spy_prev=699.0),
}


def read_files(d):
    out = {}
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p) and not name.startswith(".tmp_"):
            out[name] = open(p).read()
    return out


def run_all(tmp_root, guard_env=None):
    """guard_env: None (variable unset), '0' (explicitly off) or '1'. Returns {scenario: {'alert': [...], 'reconcile': [...], 'files': {...}}}"""
    res = {}
    for name, sc in SCENARIOS.items():
        d = os.path.join(str(tmp_root), name); os.makedirs(d)
        led = Ledger(d)
        led.save_state(State(cash=200_000.0, position=position(sc["expiry"]), last_date=sc["last"]))
        y, m, dd, hh, mm = sc["now"]; today = date(y, m, dd)
        spy = series(date(2026, 10, 1), date(2026, 12, 31), lambda x: sc["spy_prev"]); spy[today] = sc["live"]
        vix = series(date(2026, 10, 1), date(2026, 12, 31), lambda x: 19.0); tnx = series(date(2026, 10, 1), date(2026, 12, 31), lambda x: 4.5)
        feed = FakeFeed(spy, vix, tnx, {"SPY": sc["live"], "^VIX": 19.0, "^TNX": 4.5})
        if guard_env is None: os.environ.pop("ASSIGNMENT_GUARD", None)
        else: os.environ["ASSIGNMENT_GUARD"] = guard_env
        out = {}
        for cmd, when in [("alert", et(y, m, dd, 15, 45)), ("reconcile", et(y, m, dd, 16, 30))]:
            feed.now = when; hook = Hook()
            rc = R.main([cmd, "--ledger", d, "--retries", "1"], feed=feed, notifier=hook, now_utc=when)
            out[cmd] = hook.sent; out[cmd + "_rc"] = rc
        out["files"] = read_files(d)
        res[name] = out
    os.environ.pop("ASSIGNMENT_GUARD", None)
    return res
