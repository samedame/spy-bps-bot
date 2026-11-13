"""Command line / scheduler entry points.

    python -m bps_bot.run init        [--cash X] [--as-of YYYY-MM-DD] [--force]   create the paper ledger
    python -m bps_bot.run alert       [--dry-run]    ~3:45 pm ET: read live prices, say what the rules would do at today's close
    python -m bps_bot.run reconcile   [--dry-run]    after the close: apply the official close to the paper ledger, post a status
    python -m bps_bot.run status

The bot never places orders. `alert` never changes the ledger; `reconcile` is the only command that does.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import calendar_nyse as CAL
from . import messages as MSG
from .data import DataUnavailable, Feed, YahooFeed, final_bars, provisional_bar
from .engine import Bar, State, equity_mtm, step
from .ledger import Ledger
from .spec import RESEARCH_DATA_END, RESEARCH_FULL_RUN_FINAL_EQUITY, SPEC, VERIFIED_SPEC_HASH, spec_hash

ET = ZoneInfo("America/New_York")
ALERT_OPEN, ALERT_CLOSE = dtime(15, 30), dtime(16, 0)   # the alert only makes sense in the last half hour
FINAL_AFTER = dtime(16, 10)                              # the official daily close is trusted after this
MAX_CATCHUP_DAYS = 40


class Notifier:
    def __init__(self, webhook: Optional[str], dry_run: bool = False):
        self.webhook, self.dry_run, self.sent = webhook, dry_run, []

    def post(self, text: str) -> None:
        self.sent.append(text)
        if self.dry_run:
            print("---- DISCORD (dry run) ----\n" + text + "\n---------------------------")
            return
        if not self.webhook:
            raise RuntimeError("DISCORD_WEBHOOK_URL is not set")
        body = json.dumps({"content": text}).encode()
        last = None
        for k in range(3):
            try:
                req = urllib.request.Request(self.webhook, data=body, headers={"Content-Type": "application/json", "User-Agent": "bps-bot/1.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    if 200 <= r.status < 300:
                        return
                    last = f"HTTP {r.status}"
            except (urllib.error.URLError, OSError) as e:
                last = str(e)
            time.sleep(2 * (k + 1))
        raise RuntimeError(f"Discord post failed after 3 tries: {last}")


@dataclass
class DayResult:
    day: date
    events: list
    equity: float
    cash: float
    has_position: bool
    bar: Bar
    note: Optional[str]


def sig(ev: dict) -> list:
    if ev["type"] == "exit":
        return ["exit", ev["reason"], ev["short_k"], ev["long_k"], ev["expiry"]]
    if ev["type"] == "entry":
        return ["entry", ev["short_k"], ev["long_k"], ev["expiry"], ev["n"]]
    return ["entry_skipped", ev["short_k"], ev["long_k"], ev["expiry"]]


def describe(events: list) -> str:
    if not events:
        return "no action"
    out = []
    for e in events:
        if e["type"] == "exit":
            out.append(f"close {e['short_k']}P/{e['long_k']}P ({e['reason'].replace('_', ' ')}, model {MSG._money(e['pnl'])})")
        elif e["type"] == "entry":
            out.append(f"enter {e['n']} x {e['short_k']}P/{e['long_k']}P exp {e['expiry']}")
        else:
            out.append(f"entry day but no size ({e['short_k']}P/{e['long_k']}P)")
    return "; ".join(out)


def guard_spec() -> None:
    if spec_hash(SPEC) != VERIFIED_SPEC_HASH and os.environ.get("ALLOW_UNVERIFIED") != "1":
        raise SystemExit("REFUSING TO RUN: the rule set in bps_bot/spec.py is not the one the verification report covers "
                         f"(spec hash {spec_hash(SPEC)[:12]} vs verified {VERIFIED_SPEC_HASH[:12]}). "
                         "Re-run verification/run_all.py, or set ALLOW_UNVERIFIED=1 to run an unverified variant knowingly.")


def user_equity() -> Optional[float]:
    v = os.environ.get("ACCOUNT_EQUITY", "").strip().replace(",", "").replace("$", "")
    return float(v) if v else None


def target_close_date(now: datetime) -> date:
    """The latest trading day whose official close can be trusted at this moment."""
    today = now.date()
    if CAL.is_trading_day(today) and now.time() >= FINAL_AFTER:
        return today
    return CAL.prev_trading_day(today)


def next_entry_day(after: date) -> date:
    d = CAL.next_trading_day(after)
    while not (d.weekday() <= CAL.prev_trading_day(d).weekday()):
        d = CAL.next_trading_day(d)
    return d


def catch_up(state: State, feed: Feed, through: date, retries: int = 1, wait: float = 0.0) -> Tuple[State, List[DayResult]]:
    """Apply official closes for every trading day in (state.last_date, through], in order."""
    start = date.fromisoformat(state.last_date)
    days = CAL.trading_days_between(start, through)
    if len(days) > MAX_CATCHUP_DAYS:
        raise DataUnavailable(f"ledger is {len(days)} trading days behind (limit {MAX_CATCHUP_DAYS}); re-initialize it deliberately")
    if not days:
        return state, []
    err: Optional[Exception] = None
    bars = notes = None
    for attempt in range(max(retries, 1)):
        try:
            bars, notes = final_bars(feed, start, through)
            err = None
            break
        except DataUnavailable as e:
            err = e
            if attempt + 1 < max(retries, 1):
                time.sleep(wait)
    if err is not None:
        raise err
    results = []
    for d in days:
        state, events = step(state, bars[d], CAL.prev_trading_day(d))
        results.append(DayResult(d, events, equity_mtm(state, bars[d]), state.cash, state.position is not None, bars[d], notes.get(d)))
    return state, results


def cmd_init(a, led: Ledger) -> int:
    if led.exists() and not a.force:
        print("ledger already exists; use --force to overwrite")
        return 1
    st = led.init_continuing_research(cash=a.cash, as_of=a.as_of)
    print(f"ledger created: flat, paper cash ${st.cash:,.2f}, last processed day {st.last_date}")
    return 0


def cmd_status(a, led: Ledger) -> int:
    print(json.dumps(led.load_state().to_dict(), indent=1))
    return 0


WINDOW_GUARD_FILE = "alert_window.json"        # lives in the ledger dir, which the workflow commits back
SCHEDULED_TRIGGERS = {"schedule", "cf-scheduler"}   # a human's "Run workflow" click (manual / test) never raises the notice


def _guard_path(led: Ledger) -> str:
    return os.path.join(led.dir, WINDOW_GUARD_FILE)


def _guard_read(led: Ledger, today: date) -> dict:
    try:
        with open(_guard_path(led)) as f:
            d = json.load(f)
        return d if d.get("date") == today.isoformat() else {}
    except (OSError, ValueError):
        return {}


def _guard_write(led: Ledger, today: date, **fields) -> None:
    """Best effort: a failed marker write must never break the alert."""
    try:
        cur = _guard_read(led, today)
        cur.update(fields, date=today.isoformat())
        os.makedirs(led.dir, exist_ok=True)
        with open(_guard_path(led), "w") as f:
            json.dump(cur, f, sort_keys=True)
    except OSError as e:
        print(f"[window guard] could not write marker: {e}", file=sys.stderr)


def missed_window_check(a, led: Ledger, notifier: Notifier, now: datetime, env=None) -> bool:
    """Run only when the alert is OUTSIDE its window on a scheduled trigger (the run_guard.py pattern).

    * before the window: silent (the wrong-DST-season copy of the cron, or an early start);
    * after the window, and an in-window run already happened today: silent (the other cron's duplicate);
    * after the window and NO run covered today: post ONE 'missed window' notice for the day.
    Fail-soft: never raises and never changes the exit code. The window itself is NOT widened. Returns True if posted.
    """
    env = os.environ if env is None else env
    try:
        if (env.get("RUN_TRIGGER") or "") not in SCHEDULED_TRIGGERS or a.dry_run:
            return False
        if now.time() < ALERT_OPEN:
            return False
        today = now.date()
        g = _guard_read(led, today)
        if g.get("in_window_run") or g.get("missed_notified"):
            return False
        notifier.post(MSG.missed_window_notice(f"{now:%H:%M}", f"{ALERT_OPEN:%H:%M}-{ALERT_CLOSE:%H:%M}"))
        _guard_write(led, today, missed_notified=True)
        return True
    except Exception as e:  # noqa: BLE001 - Discord down, no webhook, anything: the notice is best effort
        print(f"[window guard] notice failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def cmd_alert(a, led: Ledger, feed: Feed, notifier: Notifier, now_utc: datetime) -> int:
    now = now_utc.astimezone(ET)
    today = now.date()
    if not CAL.is_trading_day(today):
        print(f"{today} is not a trading day; nothing to do")
        return 0
    if not (ALERT_OPEN <= now.time() < ALERT_CLOSE) and not a.force_window:
        print(f"{now:%H:%M} ET is outside the {ALERT_OPEN:%H:%M}-{ALERT_CLOSE:%H:%M} alert window; nothing sent")
        missed_window_check(a, led, notifier, now)
        return 0
    if not a.dry_run:
        _guard_write(led, today, in_window_run=True)
    state = led.load_state()
    if state.last_date and date.fromisoformat(state.last_date) >= today:
        print(f"ledger already includes {state.last_date}; nothing to alert")
        return 0
    prev = CAL.prev_trading_day(today)
    try:
        if state.last_date is not None and date.fromisoformat(state.last_date) < prev:
            state, _ = catch_up(state, feed, prev)           # in memory only; the ledger file is untouched
        bar, _ = provisional_bar(feed, today, now_utc)
    except DataUnavailable as e:
        notifier.post(MSG.error_notice(f"no usable prices at the {now:%H:%M} ET alert ({e})",
                                       "Check SPY, VIX and the 10-year yield by hand against the rules, or re-run this workflow."))
        return 1
    _, events = step(copy.deepcopy(state), bar, prev)
    ue = user_equity()
    for ev in events:
        if ev["type"] == "exit":
            notifier.post(MSG.exit_alert(ev, True))
        elif ev["type"] == "entry":
            notifier.post(MSG.entry_alert(ev["plan"], ev["n"], ev["sizing_equity"], ue, True))
        else:
            notifier.post(MSG.entry_skipped_alert(ev["plan"], ev["sizing_equity"], ev["budget"], ue, True))
    if not a.dry_run:
        led.save_pending({"date": today.isoformat(), "signatures": [sig(e) for e in events]})
    return 0


def cmd_reconcile(a, led: Ledger, feed: Feed, notifier: Notifier, now_utc: datetime) -> int:
    now = now_utc.astimezone(ET)
    target = date.fromisoformat(a.as_of) if a.as_of else target_close_date(now)
    state = led.load_state()
    if state.last_date and date.fromisoformat(state.last_date) >= target:
        print(f"ledger already processed {state.last_date} (target {target}); nothing to do")
        return 0
    try:
        new_state, results = catch_up(state, feed, target, retries=a.retries, wait=a.retry_wait)
    except DataUnavailable as e:
        notifier.post(MSG.error_notice(f"official close for {target} not available ({e})",
                                       "Re-run this workflow later, or check by hand: SPY close, VIX close, 10-year yield, and the open spread."))
        return 1
    if not results:
        print(f"{target} is not a trading day with new data; nothing to do")
        return 0
    last = results[-1]
    msgs: List[str] = []
    earlier = [r for r in results[:-1] if r.events]
    if earlier:
        msgs.append(MSG.fit_discord("**SPY-BPS CATCH-UP:** the ledger processed missed day(s) in order.\n" +
                                    "\n".join(f"{r.day:%a %b %d}: {describe(r.events)}" for r in earlier)))
    pending = led.load_pending()
    final_sigs = [sig(e) for e in last.events]
    if pending and pending.get("date") == target.isoformat():
        if pending.get("signatures", []) == json.loads(json.dumps(final_sigs)):
            if last.events:
                msgs.append(MSG.fit_discord(f"SPY-BPS {target:%a %b %d}: the official close confirms the 3:45 pm alert - {describe(last.events)}. "
                                            f"Paper ledger {MSG._money(last.equity)}."))
            else:
                msgs.append(MSG.status_line(target, new_state.position, last.bar, last.equity, next_entry_day(target)))
        else:
            msgs.append(MSG.difference_notice(describe_sigs(pending.get("signatures", [])), describe(last.events)))
    else:
        late = " (No 3:45 pm alert ran for this day, so this is the ledger record, not a live signal.)"
        for e in last.events:
            if e["type"] == "exit":
                msgs.append(MSG.exit_alert(e, False) + late)
            elif e["type"] == "entry":
                msgs.append(MSG.entry_alert(e["plan"], e["n"], e["sizing_equity"], user_equity(), False) + late)
            else:
                msgs.append(MSG.entry_skipped_alert(e["plan"], e["sizing_equity"], e["budget"], user_equity(), False))
        if not last.events:
            msgs.append(MSG.status_line(target, new_state.position, last.bar, last.equity, next_entry_day(target)))
    notes = [f"{r.day}: {r.note}" for r in results if r.note]
    if notes:
        msgs[-1] = MSG.fit_discord(msgs[-1] + "\nData note (the research forward-filled the same way): " + "; ".join(notes))
    for m in msgs:
        notifier.post(m)
    if a.dry_run:
        return 0
    have = {(t["entry"], t["exit"]) for t in led.read_trades()}
    have_eq = led.equity_dates()
    for r in results:
        for e in r.events:
            if e["type"] == "exit" and (e["trade"]["entry"], e["trade"]["exit"]) not in have:
                led.append_trade(e["trade"])
        if r.day.isoformat() not in have_eq:
            led.append_equity(r.day.isoformat(), r.equity, r.cash, r.has_position)
    led.save_state(new_state)
    led.clear_pending()
    return 0


def describe_sigs(sigs: list) -> str:
    if not sigs:
        return "no action"
    out = []
    for s in sigs:
        if s[0] == "exit":
            out.append(f"close {s[2]}P/{s[3]}P ({s[1].replace('_', ' ')})")
        elif s[0] == "entry":
            out.append(f"enter {s[4]} x {s[1]}P/{s[2]}P exp {s[3]}")
        else:
            out.append(f"entry day but no size ({s[1]}P/{s[2]}P)")
    return "; ".join(out)


def main(argv=None, feed: Optional[Feed] = None, notifier: Optional[Notifier] = None, now_utc: Optional[datetime] = None) -> int:
    p = argparse.ArgumentParser(prog="bps_bot.run")
    p.add_argument("command", choices=["init", "alert", "reconcile", "status"])
    p.add_argument("--ledger", default=os.environ.get("BPS_LEDGER_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ledger")))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--cash", type=float, default=RESEARCH_FULL_RUN_FINAL_EQUITY)
    p.add_argument("--as-of", default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-window", action="store_true", help="alert outside 15:30-16:00 ET (testing only)")
    p.add_argument("--retries", type=int, default=6, help="reconcile: tries while Yahoo has not published the final close")
    p.add_argument("--retry-wait", type=float, default=60.0)
    a = p.parse_args(argv)
    if a.command == "init" and a.as_of is None:
        a.as_of = RESEARCH_DATA_END
    guard_spec()
    led = Ledger(a.ledger)
    if a.command == "init":
        return cmd_init(a, led)
    if not led.exists():
        print("no ledger found. Run: python -m bps_bot.run init", file=sys.stderr)
        return 1
    if a.command == "status":
        return cmd_status(a, led)
    feed = feed or YahooFeed()
    notifier = notifier or Notifier(os.environ.get("DISCORD_WEBHOOK_URL"), dry_run=a.dry_run or os.environ.get("DRY_RUN") == "1")
    now_utc = now_utc or datetime.now(timezone.utc)
    try:
        if a.command == "alert":
            return cmd_alert(a, led, feed, notifier, now_utc)
        return cmd_reconcile(a, led, feed, notifier, now_utc)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
