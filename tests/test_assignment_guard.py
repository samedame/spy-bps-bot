"""Assignment guard: unit tests + differential tests against the unguarded baseline (tests/golden_baseline.json, produced by running
tests/scenario_common.py on the commit before the guard existed)."""
import json, os, sys
from datetime import date
import pytest
sys.path.insert(0, os.path.dirname(__file__))
import scenario_common as S
from bps_bot import assignment_guard as AG
from bps_bot import calendar_nyse as CAL
from bps_bot.engine import Bar
from bps_bot.spec import SPEC, VERIFIED_SPEC_HASH, spec_hash

GOLDEN = json.load(open(os.path.join(os.path.dirname(__file__), "golden_baseline.json")))
POS = S.position("2026-11-20")


def test_third_friday_and_exdiv_estimate():
    assert AG._third_friday(2026, 12) == date(2026, 12, 18) and AG._third_friday(2026, 3) == date(2026, 3, 20)
    assert AG.next_exdiv_estimate(date(2026, 11, 6)) == date(2026, 12, 18)
    assert AG.next_exdiv_estimate(date(2026, 12, 18)) == date(2026, 12, 18)
    assert AG.next_exdiv_estimate(date(2026, 12, 19)) == date(2027, 3, 19)


def test_assess_none_when_otm_or_flat():
    assert AG.assess(None, Bar(date(2026, 11, 6), 650.0, 19.0, 4.5), date(2026, 11, 6), date(2026, 11, 9), 0.045) is None
    assert AG.assess(POS, Bar(date(2026, 11, 6), 701.0, 19.0, 4.5), date(2026, 11, 6), date(2026, 11, 9), 0.045) is None   # OTM


def test_assess_fires_for_deep_itm_and_reports_modeled_extrinsic():
    a = AG.assess(POS, Bar(date(2026, 11, 6), 650.0, 19.0, 4.5), date(2026, 11, 6), date(2026, 11, 9), 0.045)
    assert a and a["extrinsic"] < AG.EXTRINSIC_MAX and a["itm_by"] == pytest.approx(50.0) and "almost no time value left" in a["reasons"]
    msg = AG.message(a)
    assert msg.startswith("ASSIGNMENT RISK: short leg ITM, extrinsic $") and "ex-div in 42 days (est.)" in msg and "close/roll before 15:55 ET today" in msg


def test_assess_quiet_for_shallow_itm_with_time_value():
    # $2 ITM, 14 days, normal vol: still has well over 5 cents of time value, expiry not near, ex-div far -> no line
    assert AG.assess(POS, Bar(date(2026, 11, 6), 698.0, 19.0, 4.5), date(2026, 11, 6), date(2026, 11, 9), 0.045) is None


def test_assess_expiry_next_session_and_exdiv_triggers():
    a = AG.assess(S.position("2026-11-09"), Bar(date(2026, 11, 6), 698.5, 19.0, 4.5), date(2026, 11, 6), date(2026, 11, 9), 0.045)
    assert a and "expires today or next session" in a["reasons"]
    b = AG.assess(POS, Bar(date(2026, 12, 17), 698.0, 19.0, 4.5), date(2026, 12, 17), date(2026, 12, 18), 0.045)
    assert b and "ex-dividend is near" in b["reasons"]


def test_env_switch(monkeypatch):
    monkeypatch.delenv("ASSIGNMENT_GUARD", raising=False); assert AG.enabled()
    for v in ("0", "false", "off", "no"):
        monkeypatch.setenv("ASSIGNMENT_GUARD", v); assert not AG.enabled()
    monkeypatch.setenv("ASSIGNMENT_GUARD", "1"); assert AG.enabled()


def test_guard_off_is_byte_identical_to_baseline(tmp_path):
    got = json.loads(json.dumps(S.run_all(tmp_path, guard_env="0"), sort_keys=True))
    assert got == GOLDEN


def test_guard_on_changes_nothing_but_adds_advisory_messages(tmp_path):
    got = json.loads(json.dumps(S.run_all(tmp_path, guard_env="1"), sort_keys=True))
    fired = []
    for name, base in GOLDEN.items():
        g = got[name]
        assert g["files"] == base["files"], name                       # ledger, state, pending signatures: identical
        assert g["reconcile"] == base["reconcile"] and g["alert_rc"] == base["alert_rc"] and g["reconcile_rc"] == base["reconcile_rc"]
        extra = [m for m in g["alert"] if m not in base["alert"]]
        assert [m for m in g["alert"] if m in base["alert"]] == base["alert"]        # every baseline alert still present, same text, same order
        assert all(m.startswith("ASSIGNMENT RISK:") for m in extra), name
        if extra: fired.append(name)
    assert set(fired) == {"itm_on_expiry_day", "deep_itm_midlife", "itm_day_before_expiry"}   # fires on ITM + low time value; quiet on OTM / shallow ITM


def test_default_is_on_when_variable_unset(tmp_path):
    got = json.loads(json.dumps(S.run_all(tmp_path, guard_env=None), sort_keys=True))
    assert any(m.startswith("ASSIGNMENT RISK:") for m in got["itm_on_expiry_day"]["alert"])


def test_spec_hash_and_rules_untouched():
    assert spec_hash(SPEC) == VERIFIED_SPEC_HASH
