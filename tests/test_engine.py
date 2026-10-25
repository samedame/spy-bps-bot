from datetime import date, timedelta
import pytest
from bps_bot.engine import Bar, State, step, lots_for, plan_entry, is_entry_day, equity_mtm, mark_pnl
from bps_bot import calendar_nyse as CAL
from bps_bot.spec import SPEC

def bar(d, S=760.0, vix=19.0, tnx=4.5): return Bar(d, S, vix, tnx)
MON = date(2026,10,26)

def test_entry_day_rule():
    assert is_entry_day(date(2026,10,26), date(2026,10,23))          # Monday after Friday
    assert is_entry_day(date(2026,9,8), date(2026,9,4))              # Tuesday after Labor Day Monday
    assert not is_entry_day(date(2026,10,27), date(2026,10,26))      # Tuesday after Monday
    assert not is_entry_day(date(2026,10,28), date(2026,10,27))

def test_entry_opens_one_position_with_expected_shape():
    st, ev = step(State(cash=200_000.0), bar(MON), CAL.prev_trading_day(MON))
    assert [e["type"] for e in ev] == ["entry"] and st.position is not None
    p = st.position
    assert p.short_k > p.long_k and p.expiry_date == "2026-11-09" and p.n == lots_for(200_000.0, p.maxloss / p.n)
    assert p.entry_cf > 0 and st.cash == pytest.approx(200_000.0 + p.entry_cf)

def test_no_second_position_and_no_entry_midweek():
    st, _ = step(State(cash=200_000.0), bar(MON), date(2026,10,23))
    st2, ev = step(st, bar(date(2026,11,2)), date(2026,10,30))       # next Monday, still holding
    assert ev == [] or all(e["type"] != "entry" for e in ev)
    st3, ev3 = step(State(cash=200_000.0), bar(date(2026,10,27)), MON)
    assert ev3 == [] and st3.position is None

def test_skipped_when_lot_too_big():
    st, ev = step(State(cash=100_000.0), bar(MON), date(2026,10,23))
    assert ev[0]["type"] == "entry_skipped" and st.position is None and st.cash == 100_000.0
    assert ev[0]["budget"] == pytest.approx(2000.0)

def _open():
    st, _ = step(State(cash=200_000.0), bar(MON), date(2026,10,23)); return st

def test_profit_target_when_spot_rallies():
    st = _open()
    st2, ev = step(st, bar(date(2026,10,27), S=790.0, vix=15.0), MON)
    assert ev and ev[0]["reason"] == "profit_target" and ev[0]["pnl"] > 0 and st2.position is None

def test_stop_loss_when_spot_crashes():
    st = _open()
    st2, ev = step(st, bar(date(2026,10,27), S=700.0, vix=40.0), MON)
    assert ev and ev[0]["reason"] == "stop_loss" and ev[0]["pnl"] < 0 and st2.position is None
    assert ev[0]["pnl"] <= -SPEC.stop_mult * st.position.credit0       # fills at the evaluated close, so it can be worse than -2x

def test_hold_in_between():
    st = _open()
    st2, ev = step(st, bar(date(2026,10,27), S=759.0, vix=19.2), MON)
    assert ev == [] and st2.position is not None

def test_expiry_settles_at_intrinsic_and_replaces_same_day():
    st = _open(); exp = date.fromisoformat(st.position.expiry_date)
    assert exp == date(2026,11,9) and exp.weekday() == 0                # a Monday: entry day, so it can re-enter at once
    st2, ev = step(st, bar(exp, S=780.0, vix=16.0), CAL.prev_trading_day(exp))
    assert ev[0]["type"] == "exit" and ev[0]["reason"] == "expiry" and ev[0]["pnl"] == pytest.approx(st.position.entry_cf)
    assert any(e["type"] in ("entry","entry_skipped") for e in ev[1:])

def test_pin_friction_charged_near_short_strike():
    st = _open(); p = st.position; exp = date.fromisoformat(p.expiry_date)
    S = p.short_k + 0.5   # within 0.25% of the short strike, finishes just above it
    st2, ev = step(st, bar(exp, S=S), CAL.prev_trading_day(exp), allow_entry=False)
    assert ev[0]["cash_flow"] == pytest.approx(-25.0 * 2 * p.n)

def test_input_state_not_mutated():
    st = _open(); before = st.to_dict()
    step(st, bar(date(2026,10,27), S=700.0, vix=40.0), MON)
    assert st.to_dict() == before

def test_allow_entry_false_blocks_entry():
    st, ev = step(State(cash=200_000.0), bar(MON), date(2026,10,23), allow_entry=False)
    assert ev == [] and st.position is None

def test_state_roundtrip_json():
    import json
    st = _open(); assert State.from_dict(json.loads(json.dumps(st.to_dict()))).to_dict() == st.to_dict()
