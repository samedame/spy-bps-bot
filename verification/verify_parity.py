"""Layers 1-2: the bot core against the research engine, the published result files and the published leaderboard.

Everything is compared to the ORIGINAL research code (01_engine.py + 02_run_grid.py run fresh here) and to the artifacts the
research published (results/winner_trades_risk{2,5}.csv, LEADERBOARD.csv, results/reimpl_*.json).
"""
from __future__ import annotations
import math, os, sys, importlib.util
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as RP
from bps_bot import calendar_nyse as CAL
from bps_bot.engine import Bar, plan_entry
from bps_bot.spec import SPEC

RES = os.path.join(RP.RESEARCH, "results")
WINDOWS = {"IS": ("2008-01-01", "2018-12-31", 11.0), "OOS": ("2019-01-01", "2026-10-23", 7.81), "FULL": ("2008-01-01", "2026-10-23", 18.81)}
CATEGORICAL = ["entry", "exit", "reason", "contracts"]
NUMERIC = ["pnl", "risk", "ror", "vix_entry", "credit", "debit"]
TOL_USD = 1e-6


def research_engine_spec():
    spec = importlib.util.spec_from_file_location("grid", os.path.join(RP.RESEARCH, "code", "02_run_grid.py"))
    G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
    return {s["id"]: s for s in G.build_grid()}["BP_d40_D14_W5_PT50_SL2"]


def compare_trades(bot: pd.DataFrame, ref: pd.DataFrame, label: str) -> dict:
    out = {"label": label, "n_bot": len(bot), "n_ref": len(ref)}
    if len(bot) != len(ref):
        out["pass"] = False; return out
    bot = bot.reset_index(drop=True); ref = ref.reset_index(drop=True)
    cat_ok = all((bot[c].astype(str).values == ref[c].astype(str).values).all() for c in CATEGORICAL)
    max_diff = {c: float(np.nanmax(np.abs(bot[c].astype(float).values - ref[c].astype(float).values))) for c in NUMERIC}
    out.update(categorical_identical=bool(cat_ok), max_abs_diff=max_diff, pass_=bool(cat_ok and max(max_diff.values()) < TOL_USD))
    out["pass"] = out.pop("pass_")
    return out


def lb_row():
    lb = pd.read_csv(os.path.join(RP.RESEARCH, "LEADERBOARD.csv"))
    return lb[lb.id == "BP_d40_D14_W5_PT50_SL2"].iloc[0]


def run() -> dict:
    E = RP.load_research_engine()
    df = RP.load_bars(E); df._sym = "SPY"
    spec = research_engine_spec()
    row = lb_row()
    results = {"windows": {}, "plan_every_day": None, "published": {}, "independent_reimpl": {}}
    cols = {"IS": ("n_is", "cagr_is", "sharpe_is", "sortino_is", "maxdd_is", "calmar_is", "pf_is", "win_is", "exp_ror_is", "tpy_is"),
            "OOS": ("n_oos", "cagr_oos", "sharpe_oos", "sortino_oos", "maxdd_oos", "calmar_oos", "pf_oos", "win_oos", "exp_ror_oos", "tpy_oos")}
    keys = ("n", "cagr", "sharpe", "sortino", "maxdd", "calmar", "pf", "win", "exp", "tpy")
    for name, (a, b, yrs) in WINDOWS.items():
        for risk in (0.02, 0.05):
            if name != "FULL" and risk != 0.02:
                continue
            tr_ref, eq_ref = E.run_spread(df, spec, a, b, risk_frac=risk)
            tr_bot, eq_bot, st, skipped = RP.replay(df, a, b, risk_frac=risk, sp=type(SPEC)(**{**SPEC.__dict__, "risk_frac": risk}))
            r = compare_trades(tr_bot, tr_ref, f"{name} risk={risk:.0%}")
            r["equity_max_abs_diff"] = float((eq_bot - eq_ref).abs().max())
            r["final_equity_bot"], r["final_equity_ref"] = float(eq_bot.iloc[-1]), float(eq_ref.iloc[-1])
            r["entry_weeks_skipped_for_lot_size"] = skipped
            m_bot, m_ref = E.metrics(tr_bot, eq_bot, yrs), E.metrics(tr_ref, eq_ref, yrs)
            r["metrics_bot"] = {k: float(m_bot[k]) for k in keys}
            r["metrics_max_rel_diff_vs_engine"] = float(max(abs(m_bot[k] - m_ref[k]) / (abs(m_ref[k]) + 1e-12) for k in keys))
            r["pass"] = bool(r["pass"] and r["equity_max_abs_diff"] < TOL_USD and r["metrics_max_rel_diff_vs_engine"] < 1e-9)
            if name in cols and risk == 0.02:
                pub = {k: float(row[c]) for k, c in zip(keys, cols[name])}
                diffs = {k: abs(m_bot[k] - pub[k]) / (abs(pub[k]) + 1e-12) for k in keys}
                r["published_leaderboard"] = pub
                r["leaderboard_max_rel_diff"] = float(max(diffs.values()))
                r["pass"] = bool(r["pass"] and r["leaderboard_max_rel_diff"] < 1e-9)
            if name == "FULL":
                pubf = os.path.join(RES, f"winner_trades_risk{int(risk * 100)}.csv")
                pub_tr = pd.read_csv(pubf)
                cmp_pub = compare_trades(tr_bot, pub_tr, f"FULL risk={risk:.0%} vs published {os.path.basename(pubf)}")
                results["published"][f"risk{int(risk * 100)}"] = cmp_pub
                r["pass"] = bool(r["pass"] and cmp_pub["pass"])
                if risk == 0.02:
                    pub_eq = pd.read_csv(os.path.join(RES, "winner_equity_risk2.csv"), index_col=0, parse_dates=True).iloc[:, 0]
                    results["published"]["equity_risk2_max_abs_diff"] = float((eq_bot - pub_eq).abs().max())
                    results["published"]["equity_risk2_final_bot"] = float(eq_bot.iloc[-1])
                    results["published"]["equity_risk2_final_published"] = float(pub_eq.iloc[-1])
            results["windows"][f"{name}_risk{int(risk * 100)}"] = r
            if name == "OOS":
                import json
                ri = json.load(open(os.path.join(RES, "reimpl_oos.json")))
                results["independent_reimpl"]["OOS"] = dict(research_reimpl_trades=ri["n"], research_reimpl_pnl=ri["pnl"], bot_trades=len(tr_bot), bot_pnl=float(tr_bot.pnl.sum()))
            if name == "IS":
                import json
                ri = json.load(open(os.path.join(RES, "reimpl_is.json")))
                results["independent_reimpl"]["IS"] = dict(research_reimpl_trades=ri["n"], research_reimpl_pnl=ri["pnl"], bot_trades=len(tr_bot), bot_pnl=float(tr_bot.pnl.sum()))

    # Layer 1b: the entry plan on EVERY trading day (strikes, expiry, modeled credit, max loss), traded or not.
    idx = df.index
    n_days = n_bad = 0
    max_cf = max_ml = 0.0
    last = idx[-1].date()
    for i in range(1, len(idx) - 1):
        if idx[i] < pd.Timestamp("2008-01-01"):
            continue
        row_ = df.iloc[i]; S = float(row_["Close"]); vix = float(row_["VIX"]); r_ = max(float(row_["TNX"]) / 100, 0)
        e = E.find_exp_i(idx, i, 14)
        ks = E.strike_for_delta(S, 14, r_, 0.015, vix, 0.40, "P"); kl = max(round(ks - 0.05 * S), 1)
        legs = [E.Leg(-1, ks, e, "P"), E.Leg(1, kl, e, "P")]
        dl = [max((idx[e] - idx[i]).days, 0)] * 2
        cf1 = E.trade_fill(legs, S, r_, 0.015, vix, dl, 1.0, E.FEE_LEG, True); ml = E.max_loss_credit(legs, cf1)
        p = plan_entry(Bar(idx[i].date(), S, vix, float(row_["TNX"])), expiry_cap=last)
        n_days += 1
        ok = (p.short_k, p.long_k, p.expiry) == (ks, kl, idx[e].date()) and abs(p.credit_per_lot - cf1) < 1e-8 and abs(p.max_loss_per_lot - ml) < 1e-8
        n_bad += 0 if ok else 1
        max_cf = max(max_cf, abs(p.credit_per_lot - cf1)); max_ml = max(max_ml, abs(p.max_loss_per_lot - ml))
    results["plan_every_day"] = dict(days_checked=n_days, mismatches=n_bad, max_abs_credit_diff=max_cf, max_abs_maxloss_diff=max_ml, **{"pass": n_bad == 0})
    results["pass"] = bool(all(w["pass"] for w in results["windows"].values()) and results["plan_every_day"]["pass"])
    return results


if __name__ == "__main__":
    import json
    r = run(); print(json.dumps(r, indent=1, default=float)); sys.exit(0 if r["pass"] else 1)
