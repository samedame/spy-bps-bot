"""Layer 5: does the parity check have teeth? Introduce one small deviation at a time (a changed rule number, or a changed code
path) and confirm the replay no longer matches the research engine. A mutant is tried on the out-of-sample window first and, if it
survives there, on the full 2008-2026 window. Any mutant that still survives must be explainable as equivalent (cannot change
behaviour on this data), and the explanation is itself checked against the data."""
from __future__ import annotations
import math, os, sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as RP
from bps_bot import engine as ENG, pricing as PR
from bps_bot.spec import SPEC

OOS = ("2019-01-01", "2026-10-23")
FULL = ("2008-01-01", "2026-10-23")


@contextmanager
def patched(obj, name, value):
    had = name in obj.__dict__; old = obj.__dict__.get(name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if had: setattr(obj, name, old)
        else: delattr(obj, name)


def spec_mutants():
    s = SPEC
    return [
        ("delta 0.40 -> 0.30", replace(s, delta=0.30)), ("delta 0.40 -> 0.41", replace(s, delta=0.41)),
        ("dte 14 -> 15", replace(s, dte=15)), ("width 5% -> 4%", replace(s, width_frac=0.04)),
        ("profit target 50% -> 49%", replace(s, profit_target=0.49)), ("stop 2.0x -> 2.1x", replace(s, stop_mult=2.1)),
        ("stop removed", replace(s, stop_mult=None)), ("risk 2% -> 2.1%", replace(s, risk_frac=0.021)),
        ("slippage 100% -> 99%", replace(s, slip_frac=0.99)), ("commission 0.65 -> 0.64", replace(s, fee_commission=0.64)),
        ("div yield 1.5% -> 1.51%", replace(s, div_yield=0.0151)), ("skew_down 0.35 -> 0.36", replace(s, skew_down=0.36)),
        ("skew_up 0.10 -> 0.11", replace(s, skew_up=0.11)), ("pin fee 25 -> 0", replace(s, pin_fee=0.0)),
        ("pin zone 0.25% -> 0.30%", replace(s, pin_pct=0.003)),
        ("half-spread pct 2% -> 2.1%", replace(s, hs_pct=0.021)), ("IV term slope 0.04 -> 0.041", replace(s, iv_term_slope=0.041)),
        ("IV floor 8% -> 9%", replace(s, iv_floor=0.09)), ("far-OTM spread mult 1.5 -> 1.0", replace(s, hs_far_mult=1.0)),
    ]


def equivalence_notes(df):
    idx = [d.date() for d in df.index]
    same_weekday_gaps = sum(1 for a, b in zip(idx, idx[1:]) if (b - a).days % 7 == 0)
    note = ("differs only if two consecutive trading days fall on the same weekday (a gap of exactly 7 days); "
            f"number of such gaps in the 2007-2026 SPY data = {same_weekday_gaps}")
    return {"entry-day rule '<=' -> '<'": note}, same_weekday_gaps


def run_mutation():
    E = RP.load_research_engine(); df = E.load("SPY"); df._sym = "SPY"
    import verify_parity as VP
    spec = VP.research_engine_spec()
    refs = {OOS: E.run_spread(df, spec, *OOS, risk_frac=0.02), FULL: E.run_spread(df, spec, *FULL, risk_frac=0.02)}

    def differs(tr, eq, w):
        tr_ref, eq_ref = refs[w]
        if len(tr) != len(tr_ref): return True
        for c in ("entry", "exit", "reason", "contracts"):
            if (tr[c].astype(str).values != tr_ref[c].astype(str).values).any(): return True
        if np.abs(tr.pnl.values - tr_ref.pnl.values).max() > 1e-6: return True
        return bool((eq - eq_ref).abs().max() > 1e-6)

    def evaluate(make):
        for w, wl in ((OOS, "OOS"), (FULL, "FULL")):
            tr, eq = make(w)
            if differs(tr, eq, w):
                return True, wl
        return False, "-"

    def spec_runner(sp):
        return lambda w: RP.replay(df, *w, sp=sp)[:2]

    def patch_runner(obj, name, val):
        def f(w):
            with patched(obj, name, val):
                return RP.replay(df, *w)[:2]
        return f

    def wrap_runner(step_fn):
        return lambda w: RP.replay(df, *w, step_fn=step_fn)[:2]

    baseline_differs = any(differs(*RP.replay(df, *w)[:2], w) for w in (OOS, FULL))

    def lt_rule(today, prev): return today.weekday() < prev.weekday()
    def monday_only(today, prev): return today.weekday() == 0
    def no_same_day_reentry(st, bar, prev, **kw):
        kw = dict(kw); kw["allow_entry"] = kw.get("allow_entry", True) and st.position is None
        return ENG.step(st, bar, prev, **kw)
    def late_settle(st, bar, prev, **kw):
        if st.position is not None and bar.date.isoformat() == st.position.expiry_date:
            st2 = ENG.State(cash=st.cash, position=replace(st.position, expiry_date=(bar.date + timedelta(days=1)).isoformat()), last_date=st.last_date)
            return ENG.step(st2, bar, prev, **kw)
        return ENG.step(st, bar, prev, **kw)

    plan = [(l, spec_runner(sp)) for l, sp in spec_mutants()]
    plan += [
        ("entry-day rule '<=' -> '<'", patch_runner(ENG, "is_entry_day", lt_rule)),
        ("entry only on Mondays (holiday weeks skipped)", patch_runner(ENG, "is_entry_day", monday_only)),
        ("long strike truncated with int() instead of round()", patch_runner(ENG, "round", lambda x: int(x))),
        ("short strike floored instead of rounded", patch_runner(PR, "round", lambda x: math.floor(x))),
        ("lots: ceil instead of floor", patch_runner(ENG, "lots_for", lambda eq, ml, sp=SPEC: int(math.ceil((sp.risk_frac * eq) / ml)) if ml > 0 else 0)),
        ("no same-day re-entry after an exit", wrap_runner(no_same_day_reentry)),
        ("expiry settled one day late", wrap_runner(late_settle)),
    ]
    results = []
    for label, make in plan:
        caught, where = evaluate(make)
        results.append(dict(mutant=label, caught=bool(caught), caught_on=where))
    notes, gaps = equivalence_notes(df)
    survivors = [r["mutant"] for r in results if not r["caught"]]
    unexplained = [m for m in survivors if m not in notes or gaps != 0]
    return dict(baseline_unmutated_differs=bool(baseline_differs), mutants=results, total=len(results),
                caught=sum(r["caught"] for r in results), survivors=survivors,
                survivor_explanations={m: notes[m] for m in survivors if m in notes},
                **{"pass": bool((not baseline_differs) and not unexplained)})


if __name__ == "__main__":
    import json
    r = run_mutation(); print(json.dumps(r, indent=1)); sys.exit(0 if r["pass"] else 1)
