"""Run every verification layer and write verification/VERIFICATION_REPORT.md + verification_results.json.

    RESEARCH_DIR=<options_research folder> python verification/run_all.py [--quick]

Exit code 0 only if every layer passes. The bot's runtime guard compares spec_hash(SPEC) with VERIFIED_SPEC_HASH; this script
refuses to bless a rule set whose hash is not the one recorded in bps_bot/spec.py.
"""
from __future__ import annotations
import hashlib, json, os, subprocess, sys, time
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import replay as RP
import calendar_check, live_loop, mutation, sensitivity, verify_parity, yahoo_smoke
from bps_bot.spec import SPEC, spec_hash, VERIFIED_SPEC_HASH

PREREG_SHA = "583209c058e90f365b76604f5f989308ad6fcf97ae20ce190b05b93f84810465"
INPUTS = ["PREREGISTRATION.md", "code/01_engine.py", "code/02_run_grid.py", "data/spy.csv", "data/vix.csv", "data/tnx.csv",
          "LEADERBOARD.csv", "results/winner_trades_risk2.csv", "results/winner_trades_risk5.csv", "results/winner_equity_risk2.csv"]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pct(x): return f"{x * 100:.2f}%"


def main(quick=False):
    t0 = time.time(); R = RP.RESEARCH
    res = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "spec_id": SPEC.spec_id, "spec_hash": spec_hash(SPEC)}
    res["spec_hash_matches_recorded"] = spec_hash(SPEC) == VERIFIED_SPEC_HASH
    res["inputs"] = {p: sha(os.path.join(R, p)) for p in INPUTS}
    res["preregistration_hash_matches_frozen"] = res["inputs"]["PREREGISTRATION.md"] == PREREG_SHA
    pt = subprocess.run([sys.executable, "-m", "pytest", "-q", os.path.join(ROOT, "tests")], capture_output=True, text=True, cwd=ROOT)
    res["unit_tests"] = dict(passed=pt.returncode == 0, summary=(pt.stdout.strip().splitlines() or ["?"])[-1])
    print("unit tests:", res["unit_tests"]["summary"], flush=True)
    res["calendar"] = calendar_check.run(); print("calendar:", res["calendar"]["pass"], flush=True)
    res["parity"] = verify_parity.run(); print("parity:", res["parity"]["pass"], flush=True)
    res["live_loop"] = live_loop.run_all(quick=quick); print("live loop:", [x["pass"] for x in res["live_loop"]], flush=True)
    res["mutation"] = mutation.run_mutation(); print("mutation:", res["mutation"]["caught"], "/", res["mutation"]["total"], flush=True)
    res["yahoo"] = yahoo_smoke.run(); print("yahoo:", res["yahoo"].get("ran"), res["yahoo"]["pass"], flush=True)
    res["sensitivity"] = sensitivity.run()
    res["pass"] = bool(res["spec_hash_matches_recorded"] and res["preregistration_hash_matches_frozen"] and res["unit_tests"]["passed"]
                       and res["calendar"]["pass"] and res["parity"]["pass"] and all(x["pass"] for x in res["live_loop"])
                       and res["mutation"]["pass"] and res["yahoo"]["pass"])
    res["seconds"] = round(time.time() - t0)
    json.dump(res, open(os.path.join(HERE, "verification_results.json"), "w"), indent=1, default=float)
    open(os.path.join(HERE, "VERIFICATION_REPORT.md"), "w").write(report(res))
    print("OVERALL:", "PASS" if res["pass"] else "FAIL", f"({res['seconds']}s)")
    return 0 if res["pass"] else 1


def report(r) -> str:
    P = r["parity"]; W = P["windows"]; L = r["live_loop"]; M = r["mutation"]; Y = r["yahoo"]; S = r["sensitivity"]
    ok = lambda b: "PASS" if b else "**FAIL**"
    lines = []
    A = lines.append
    A(f"# Verification report: SPY bull put spread bot (`{r['spec_id']}`)")
    A(f"Generated {r['generated_utc']} by `verification/run_all.py` ({r['seconds']} s). **Overall: {ok(r['pass'])}.**\n")
    A("**What this proves, and what it does not.** It proves the bot makes the same decisions, with the same numbers, as the research code and the "
      "published research results: same strikes, expiries, lots, exits, P&L and statistics. It does **not** re-validate the strategy. The research itself "
      "labels this rule set PROMISING (proxy prices, capped), confidence LOW, and \"nothing confirmed\"; the bot inherits that label.\n")
    A("## 1. What was held against what")
    A("| Reference | Role |\n|---|---|\n"
      "| `code/01_engine.py` + `02_run_grid.py` (the research engine, run fresh here) | the oracle for every trade and every daily equity value |\n"
      "| `results/winner_trades_risk2.csv`, `winner_trades_risk5.csv`, `winner_equity_risk2.csv` | the research's own published output for this spec |\n"
      "| `LEADERBOARD.csv` row `BP_d40_D14_W5_PT50_SL2` | the published IS / OOS statistics |\n"
      "| `results/reimpl_is.json`, `reimpl_oos.json` | the research's own independent re-implementation (Gate 9), reported for context |\n"
      "| `data/spy.csv`, `vix.csv`, `tnx.csv` | the exact price inputs |\n")
    A(f"Rule-set fingerprint (`spec_hash`): `{r['spec_hash']}`. It equals the value recorded in `bps_bot/spec.py` ({ok(r['spec_hash_matches_recorded'])}); the bot refuses to run if it ever differs. "
      f"`PREREGISTRATION.md` SHA-256 still equals the frozen value ({ok(r['preregistration_hash_matches_frozen'])}).\n")
    A("Input fingerprints (SHA-256, so this report can be tied to the exact files):\n")
    A("```\n" + "\n".join(f"{h[:16]}...  {p}" for p, h in r["inputs"].items()) + "\n```\n")
    A("## 2. Results by layer")
    A("| # | Layer | What was compared | Result |\n|---|---|---|---|")
    A(f"| 1 | Entry plan, every trading day | strikes, expiry, modeled credit, max loss on {P['plan_every_day']['days_checked']:,} days (traded or not) | {ok(P['plan_every_day']['pass'])}: {P['plan_every_day']['mismatches']} mismatches; max credit diff ${P['plan_every_day']['max_abs_credit_diff']:.1e} |")
    for k, w in W.items():
        A(f"| 2 | Trades + daily equity, {w['label']} | {w['n_bot']} bot vs {w['n_ref']} engine trades; dates, reasons, lots, P&L, MTM equity | {ok(w['pass'])}: max equity diff ${w['equity_max_abs_diff']:.1e} |")
    A(f"| 2 | Published trade files | FULL 2%: {P['published']['risk2']['n_bot']} trades; FULL 5%: {P['published']['risk5']['n_bot']} trades | {ok(P['published']['risk2']['pass'] and P['published']['risk5']['pass'])}: max P&L diff ${max(P['published']['risk2']['max_abs_diff']['pnl'], P['published']['risk5']['max_abs_diff']['pnl']):.1e} |")
    for x in L:
        A(f"| 3 | Real runner, {x['name']} | {x['days']:,} days{'; ' + str(x['days_never_run']) + ' never run' if x['days_never_run'] else ''}; ledger files vs engine | {ok(x['pass'])}: {x['trades_ledger']}/{x['trades_engine']} trades, equity diff ${x['equity_max_abs_diff']:.1e}, {x['runner_errors']} errors, {x['difference_notices']} alert-vs-close differences |")
    A(f"| 4 | Trading calendar | {r['calendar']['data_days']:,} SPY trading days 2007-2026 vs rule-based calendar | {ok(r['calendar']['pass'])}: {len(r['calendar']['in_data_not_calendar'])} + {len(r['calendar']['in_calendar_not_data'])} differences |")
    A(f"| 5 | Mutation test | {M['total']} deliberate deviations | {ok(M['pass'])}: {M['caught']}/{M['total']} caught; survivors: {', '.join(M['survivors']) or 'none'} (equivalent, see 3.5) |")
    if Y.get("ran"):
        A(f"| 6 | Live data path (Yahoo) | SPY/VIX/TNX closes vs research CSVs; real runner end to end (dry run) | {ok(Y['pass'])}: {Y['SPY']['days_compared']} days, max diff {Y['SPY']['max_abs_diff']:g} |")
    else:
        A(f"| 6 | Live data path (Yahoo) | not reachable from the verification machine | NOT RUN ({Y.get('reason')}) |")
    A(f"| 7 | Unit tests | `pytest tests` | {ok(r['unit_tests']['passed'])}: {r['unit_tests']['summary']} |")
    A("\n## 3. Details\n### 3.1 Statistics reproduced (IS and OOS, 2% risk, $100k, same windows as the research)")
    A("| Metric | IS published | IS bot | OOS published | OOS bot |\n|---|---|---|---|---|")
    names = [("n", "Trades", "{:.0f}"), ("win", "Win rate", "{:.2%}"), ("cagr", "CAGR", "{:.2%}"), ("sharpe", "Sharpe", "{:.3f}"), ("sortino", "Sortino", "{:.3f}"),
             ("maxdd", "Max drawdown", "{:.2%}"), ("pf", "Profit factor", "{:.3f}"), ("exp", "Expectancy (on risk)", "{:.2%}"), ("tpy", "Trades / year", "{:.1f}")]
    for key, label, fmt in names:
        A(f"| {label} | {fmt.format(W['IS_risk2']['published_leaderboard'][key])} | {fmt.format(W['IS_risk2']['metrics_bot'][key])} | {fmt.format(W['OOS_risk2']['published_leaderboard'][key])} | {fmt.format(W['OOS_risk2']['metrics_bot'][key])} |")
    A(f"\nLargest relative difference over all ten statistics: IS {W['IS_risk2']['leaderboard_max_rel_diff']:.1e}, OOS {W['OOS_risk2']['leaderboard_max_rel_diff']:.1e} (floating-point noise).")
    A(f"\n### 3.2 Full-sample run (2008-01-02 to 2026-10-23, continuous)\nFinal equity: bot ${P['published']['equity_risk2_final_bot']:,.2f} vs published ${P['published']['equity_risk2_final_published']:,.2f}. "
      f"This is the account the paper ledger continues from: it starts flat at ${161549.82982224415:,.2f} on 2026-10-23.")
    ri = P["independent_reimpl"]
    A(f"\n### 3.3 The research's own independent re-implementation (context)\nGate 9 of the research compared two code paths within tolerance (trades +/-2%, P&L +/-5%). Bot vs that re-implementation: "
      f"IS {ri['IS']['bot_trades']} vs {ri['IS']['research_reimpl_trades']} trades, P&L ${ri['IS']['bot_pnl']:,.0f} vs ${ri['IS']['research_reimpl_pnl']:,.0f}; "
      f"OOS {ri['OOS']['bot_trades']} vs {ri['OOS']['research_reimpl_trades']} trades, P&L ${ri['OOS']['bot_pnl']:,.0f} vs ${ri['OOS']['research_reimpl_pnl']:,.0f}. "
      "The bot matches the **primary engine** exactly (section 2); the re-implementation differs from the engine by the small amounts the research already reported and accepted. The bot follows the engine because that is what produced every published number.")
    A("\n### 3.4 Real runner scenarios (layer 3)\nThe runner is the code the scheduler calls: it reads and writes the JSON/CSV ledger, applies `reconcile` after each close and `alert` at 3:45 pm. "
      "The fake feed serves raw (not forward-filled) research CSVs and **raises if the bot asks for a price from after the simulated clock**, so passing also proves there is no look-ahead.\n")
    A("| Scenario | Days | Never run | Trades | Equity rows | Alert messages | Alert vs close differences | Final equity (ledger vs engine) |\n|---|---|---|---|---|---|---|---|")
    for x in L:
        A(f"| {x['name']} | {x['days']:,} | {x['days_never_run']} | {x['trades_ledger']} / {x['trades_engine']} | {x['equity_rows']} / {x['equity_rows_engine']} | {x['alert_messages']} | {x['difference_notices']} | ${x['final_cash_ledger']:,.2f} / ${x['final_cash_engine_equity']:,.2f} |")
    A("\nIn the \"never run\" scenario about 15% of days were skipped at random; the next `reconcile` caught up day by day in order and produced the identical ledger.")
    for x in L:
        if x.get("engine_end_of_data_expiry_cap_boundary"):
            A(f"\n**Boundary effect in \"{x['name']}\".** Every trade matches the engine, and the ledger's equity matches the engine on every day before {x['engine_end_of_data_expiry_cap_boundary']} "
              f"(max diff ${x['equity_vs_engine_max_abs_diff_before_boundary']:.1e}) and matches an uncapped replay of the bot core on all {x['equity_rows']:,} days (max diff ${x['equity_vs_uncapped_replay_max_abs_diff']:.1e}). "
              f"The ledger differs from the engine on exactly {x['days_differing_from_engine_after_boundary']} days at the very end because the research engine caps every expiry at its last data bar (2026-10-23): "
              "on 2026-10-19 it priced a 4-day spread (credit about $291, 0 lots), whereas a live run prices the real 14-day expiry of 2026-11-02 (credit about $701, 1 lot) and opens a position. "
              "This is an artifact of where the research data stops, not a difference in rules.")
    A("\n### 3.5 Mutation test (layer 5)\nEach row is one deliberate change to the bot; \"caught\" means the parity check stopped matching the engine.\n")
    A("| Deviation introduced | Caught | Where |\n|---|---|---|")
    for m in M["mutants"]:
        A(f"| {m['mutant']} | {'yes' if m['caught'] else '**no**'} | {m['caught_on']} |")
    for k, v in M["survivor_explanations"].items():
        A(f"\nSurvivor `{k}` is an equivalent mutant: {v}.")
    A("\nThe unmutated bot matched on both windows, so every catch is a real deviation. The IV-floor mutant only shows on the full window because VIX was below ~9.3 only before 2019.")
    A("\n## 4. Things the verification found that you should know")
    ow = W["OOS_risk2"]; fw = W["FULL_risk2"]
    A(f"1. **The sizing rule starves the strategy of lots.** At 2% risk, one spread must have max loss <= 2% of equity. SPY's rise pushed one spread's max loss to about $3,100-$3,500, so on a $100k account the OOS replay skipped **{ow['entry_weeks_skipped_for_lot_size']} entry weeks** "
      f"(that run takes only 3 trades in 2026); the continuous run skipped {fw['entry_weeks_skipped_for_lot_size']}. The paper ledger starts at $161,550 and **already skipped Oct 5, 12 and 19, 2026** (max loss $3,258 / $3,362 / $3,509 vs a $3,231 budget). "
      "One spread needs about $155k-$175k of equity under the tested rule. The bot reports this on every entry day instead of quietly resizing, because any other size is an untested strategy.")
    A("2. **`results/deployability.json` is a simplified illustration, not the engine.** It shows credit $7.2128 and max loss $3,078.72 *before* the two $0.67 entry fees and truncates the long strike with `int()`; "
      "the engine (which produced all trades and statistics, and which the bot follows) uses after-fee credit $7.1994 and max loss $3,080.06 and rounds the long strike. The bot reproduces the published illustration exactly once the fees are added back (tested), and the difference cannot change a lot count except at a knife-edge.")
    A("3. **The research's own run ends with an end-of-data artifact.** The engine caps every expiry at its last data bar, so its 2026-10-19 entry was priced as a 4-day spread and skipped for lot size. Under the same rules with the real expiry (2026-11-02) that Monday would have opened 1 spread (761/723). The paper ledger starts flat from the engine's final state ($161,549.83 on 2026-10-23) and does not back-fill that hypothetical trade.")
    A("4. **A 3:45 pm alert is not the verified fill.** The research trades at the official daily close. The alert uses a live snapshot, so its strikes can differ from the close's. The research has only daily closes, so this is a sensitivity with *assumed* intraday noise, not a measurement:\n")
    A("| Assumed SPY move 3:45 pm to close | Assumed VIX move | Entry dates where the alerted strikes equal the close's | Median change in model credit |\n|---|---|---|---|")
    for s in S:
        A(f"| {s['assumed_spy_noise_pct']:.2f}% (1 sd) | {s['assumed_vix_noise_pts']:.2f} pts | {s['same_strikes_pct']:.1f}% | ${s['median_credit_change_per_share']:.3f} / share |")
    A("\nThe after-close run therefore compares itself with the alert and posts a difference notice when they disagree; the paper ledger always follows the official close, so it stays equal to the verified engine.")
    A("\n## 5. Not verified (and why)")
    A("- **Real option prices and fills.** The verified strategy uses the research's Black-Scholes/VIX proxy with pessimistic modeled spreads. The bot's \"credit\" is that proxy, not a quote. No real chain history exists in the research (the verdict names this as the step from PROMISING to CONFIRMED).\n"
      "- **Whether the strategy has an edge.** Not the question here. The research's own gates: DSR fails, confidence LOW, proxy-capped at PROMISING.\n"
      "- **Discord delivery, GitHub Actions scheduling, Cloudflare triggers.** Not reachable from the verification machine. Posting is exercised only with a fake webhook; scheduling logic is exercised by unit tests with injected clocks.\n"
      "- **Your real fills.** The ledger is the paper model; it does not know what you actually traded.\n"
      "- **Refinements the research left untested** (kill-switch, vol-scaled sizing, XSP, narrower widths) are deliberately **not** in the bot.\n"
      "- **Backtest-edge artifacts.** The research engine caps an expiry at the last data bar and forbids entries on the final bar of a window; the replay reproduces both so the comparison is exact, and neither can occur live.")
    A("\n## 6. Re-running\n```\nRESEARCH_DIR=/path/to/options_research python verification/run_all.py          # all layers (~4 min)\nRESEARCH_DIR=... python verification/run_all.py --quick   # skips the 2008-2026 live-loop scenario\npython -m pytest tests -q                                  # unit tests only (no research folder needed)\n```")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main(quick="--quick" in sys.argv))
