"""Runner tests with a fake feed and a fake Discord: alert/reconcile behaviour, idempotency, catch-up, failures."""
import json, os
from datetime import date, datetime, timedelta, timezone
import pytest
from zoneinfo import ZoneInfo
from bps_bot import run as R
from bps_bot import calendar_nyse as CAL
from bps_bot.ledger import Ledger
from bps_bot.engine import State

ET = ZoneInfo("America/New_York")

class FakeFeed:
    """Serves closes for the symbols from dicts; live quote returns the given price."""
    def __init__(self, spy, vix, tnx, live=None, live_age_min=1):
        self.s = {"SPY": spy, "^VIX": vix, "^TNX": tnx}; self.live = live or {}; self.age = live_age_min; self.now = None
    def daily_closes(self, symbol, start, end): return {d: v for d, v in self.s[symbol].items() if start <= d <= end}
    def live_quote(self, symbol):
        if symbol not in self.live: raise R.DataUnavailable("no live " + symbol)
        return self.live[symbol], self.now - timedelta(minutes=self.age)

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

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ACCOUNT_EQUITY", raising=False)
    led = Ledger(str(tmp_path)); led.save_state(State(cash=200_000.0, last_date="2026-10-23"))
    spy = series(date(2026,10,1), date(2026,12,31), lambda d: 760.0); vix = series(date(2026,10,1), date(2026,12,31), lambda d: 19.0)
    tnx = series(date(2026,10,1), date(2026,12,31), lambda d: 4.5)
    return led, FakeFeed(spy, vix, tnx), tmp_path

def run(cmd, env, now, extra=()):
    led, feed, tmp = env; feed.now = now; hook = Hook()
    rc = R.main([cmd, "--ledger", str(tmp), "--retries", "1", *extra], feed=feed, notifier=hook, now_utc=now)
    return rc, hook.sent

def test_alert_posts_entry_on_monday_and_does_not_touch_ledger(env):
    led, feed, tmp = env; now = et(2026,10,26,15,45)
    feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    rc, sent = run("alert", env, now)
    assert rc == 0 and len(sent) == 1 and "ENTRY" in sent[0] and "SELL 1 SPY" in sent[0] and "No order has been placed" in sent[0]
    assert led.load_state().position is None and led.load_state().last_date == "2026-10-23"
    assert led.load_pending()["signatures"][0][0] == "entry"

def test_alert_quiet_midweek_and_outside_window_and_holiday(env):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    # state is as of Fri 10-23; Tue 10-27 would first need Mon 10-26 closed (catch-up in memory), no entry on a Tuesday
    rc, sent = run("alert", env, et(2026,10,27,15,45)); assert rc == 0 and sent == []
    rc, sent = run("alert", env, et(2026,10,26,12,0)); assert rc == 0 and sent == []          # before the window
    rc, sent = run("alert", env, et(2026,10,26,16,20)); assert rc == 0 and sent == []         # after the window
    rc, sent = run("alert", env, et(2026,11,26,15,45)); assert rc == 0 and sent == []         # Thanksgiving

def test_alert_with_stale_or_missing_quote_posts_error_and_fails(env):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}; feed.age = 45
    rc, sent = run("alert", env, et(2026,10,26,15,45))
    assert rc == 1 and "ERROR" in sent[0] and "old" in sent[0]
    feed.live = {}
    rc, sent = run("alert", env, et(2026,10,26,15,45)); assert rc == 1 and "ERROR" in sent[0]

def test_reconcile_updates_ledger_and_is_idempotent(env):
    led, feed, tmp = env
    feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    run("alert", env, et(2026,10,26,15,45))
    rc, sent = run("reconcile", env, et(2026,10,26,16,30))
    assert rc == 0 and "confirms the 3:45 pm alert" in sent[0]
    st = led.load_state(); assert st.last_date == "2026-10-26" and st.position is not None and led.load_pending() is None
    rc, sent = run("reconcile", env, et(2026,10,26,16,45)); assert rc == 0 and sent == []
    assert len(led.equity_dates()) == 1

def test_reconcile_before_final_time_does_nothing_new(env):
    led, feed, tmp = env
    rc, sent = run("reconcile", env, et(2026,10,26,15,0))       # today's close not final: target is Fri 10-23, already done
    assert rc == 0 and sent == [] and led.load_state().last_date == "2026-10-23"

def test_reconcile_catches_up_missed_days_in_order(env):
    led, feed, tmp = env
    rc, sent = run("reconcile", env, et(2026,10,29,16,30))      # Mon-Thu never reconciled
    st = led.load_state(); assert rc == 0 and st.last_date == "2026-10-29" and st.position is not None
    assert st.position.entry_date == "2026-10-26"
    assert any("CATCH-UP" in m for m in sent)

def test_reconcile_missing_final_close_fails_loudly_without_changing_ledger(env):
    led, feed, tmp = env; del feed.s["SPY"][date(2026,10,26)]
    rc, sent = run("reconcile", env, et(2026,10,26,16,30))
    assert rc == 1 and "ERROR" in sent[0] and led.load_state().last_date == "2026-10-23"

def test_difference_between_alert_and_close_is_reported(env):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    run("alert", env, et(2026,10,26,15,45))
    feed.s["SPY"][date(2026,10,26)] = 740.0                      # the official close moves the strikes
    rc, sent = run("reconcile", env, et(2026,10,26,16,30))
    assert rc == 0 and "differs from the 3:45 pm alert" in sent[0]

def test_alert_sizes_for_user_account(env, monkeypatch):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    monkeypatch.setenv("ACCOUNT_EQUITY", "5000")
    rc, sent = run("alert", env, et(2026,10,26,15,45))
    assert "your account $5,000 -> 0 spread(s)" in sent[0] and "paper only" in sent[0]

def test_no_size_message_on_small_paper_account(env):
    led, feed, tmp = env; led.save_state(State(cash=100_000.0, last_date="2026-10-23")); feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    rc, sent = run("alert", env, et(2026,10,26,15,45))
    assert "NO SIZE" in sent[0] and "$2,000" in sent[0]

def test_messages_fit_discord(env):
    from bps_bot import messages as M
    assert len(M.fit_discord("x" * 5000)) <= 2000

def test_spec_hash_guard(monkeypatch):
    monkeypatch.setattr(R, "VERIFIED_SPEC_HASH", "0" * 64); monkeypatch.delenv("ALLOW_UNVERIFIED", raising=False)
    with pytest.raises(SystemExit): R.guard_spec()
    monkeypatch.setenv("ALLOW_UNVERIFIED", "1"); R.guard_spec()

def test_ledger_rejects_other_rule_set(tmp_path):
    led = Ledger(str(tmp_path)); led.save_state(State(cash=1.0, last_date="2026-10-23"))
    d = json.load(open(led.state_path)); d["spec_hash"] = "bad"; json.dump(d, open(led.state_path, "w"))
    with pytest.raises(RuntimeError): led.load_state()

def test_init_command(tmp_path):
    assert R.main(["init", "--ledger", str(tmp_path)]) == 0
    st = Ledger(str(tmp_path)).load_state(); assert st.cash == pytest.approx(161549.82982224415) and st.last_date == "2026-10-23"
    assert R.main(["init", "--ledger", str(tmp_path)]) == 1          # refuses to overwrite

def test_reconcile_on_non_trading_day_as_of_is_a_quiet_noop(env):
    led, feed, tmp = env
    rc, sent = run("reconcile", env, et(2026,10,31,12,0), extra=("--as-of", "2026-10-24"))   # a Saturday
    assert rc == 0 and sent == [] and led.load_state().last_date == "2026-10-23"

def test_stale_yield_is_tolerated_but_stale_spy_is_not(env):
    from bps_bot.data import provisional_bar, DataUnavailable
    led, feed, tmp = env; now = et(2026,10,26,15,45); feed.now = now
    class F:
        def live_quote(self, sym):
            ages = {"SPY": 1, "^VIX": 1, "^TNX": 120}; return {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}[sym], now - timedelta(minutes=ages[sym])
    bar, _ = provisional_bar(F(), date(2026,10,26), now); assert bar.tnx_pct == 4.5
    class G(F):
        def live_quote(self, sym):
            ages = {"SPY": 40, "^VIX": 1, "^TNX": 1}; return {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}[sym], now - timedelta(minutes=ages[sym])
    with pytest.raises(DataUnavailable): provisional_bar(G(), date(2026,10,26), now)


# ---- missed-window notice (scheduled starts outside 15:30-16:00 ET) ----
def run_trig(cmd, env, now, trigger, extra=()):
    led, feed, tmp = env; feed.now = now; hook = Hook()
    os.environ["RUN_TRIGGER"] = trigger
    try:
        rc = R.main([cmd, "--ledger", str(tmp), "--retries", "1", *extra], feed=feed, notifier=hook, now_utc=now)
    finally:
        os.environ.pop("RUN_TRIGGER", None)
    return rc, hook.sent

def test_late_scheduled_start_posts_one_missed_window_notice_per_day(env):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    rc, sent = run_trig("alert", env, et(2026,10,26,17,45), "schedule")
    assert rc == 0 and len(sent) == 1 and "MISSED WINDOW" in sent[0]
    rc, sent = run_trig("alert", env, et(2026,10,26,17,50), "cf-scheduler")      # same day again -> silent
    assert rc == 0 and sent == []
    rc, sent = run_trig("alert", env, et(2026,10,27,17,45), "schedule")          # next day -> one more
    assert rc == 0 and len(sent) == 1

def test_in_window_run_makes_the_other_crons_late_copy_silent(env):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    rc, sent = run_trig("alert", env, et(2026,10,26,15,45), "schedule"); assert rc == 0 and "ENTRY" in sent[0]
    rc, sent = run_trig("alert", env, et(2026,10,26,16,45), "schedule"); assert rc == 0 and sent == []

def test_early_wrong_season_copy_is_silent_and_does_not_block_the_real_run(env):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    rc, sent = run_trig("alert", env, et(2026,10,26,14,45), "schedule"); assert rc == 0 and sent == []
    rc, sent = run_trig("alert", env, et(2026,10,26,15,45), "schedule"); assert rc == 0 and "ENTRY" in sent[0]

def test_manual_and_test_runs_never_post_the_notice(env):
    for trig in ("manual", "test", ""):
        rc, sent = run_trig("alert", env, et(2026,10,26,17,45), trig); assert rc == 0 and sent == []

def test_non_trading_day_and_dry_run_stay_silent(env):
    rc, sent = run_trig("alert", env, et(2026,11,26,17,45), "schedule"); assert rc == 0 and sent == []      # Thanksgiving
    rc, sent = run_trig("alert", env, et(2026,10,26,17,45), "schedule", ("--dry-run",)); assert rc == 0 and sent == []

def test_notice_failure_is_fail_soft(env):
    led, feed, tmp = env; feed.now = et(2026,10,26,17,45)
    class Boom:
        def post(self, text): raise RuntimeError("DISCORD_WEBHOOK_URL is not set")
    os.environ["RUN_TRIGGER"] = "schedule"
    try:
        rc = R.main(["alert", "--ledger", str(tmp)], feed=feed, notifier=Boom(), now_utc=et(2026,10,26,17,45))
    finally:
        os.environ.pop("RUN_TRIGGER", None)
    assert rc == 0                                           # exit code unchanged

def test_window_is_not_widened(env):
    led, feed, tmp = env; feed.live = {"SPY": 760.0, "^VIX": 19.0, "^TNX": 4.5}
    assert (R.ALERT_OPEN.hour, R.ALERT_OPEN.minute, R.ALERT_CLOSE.hour, R.ALERT_CLOSE.minute) == (15, 30, 16, 0)
    rc, sent = run_trig("alert", env, et(2026,10,26,16,1), "manual"); assert sent == []
