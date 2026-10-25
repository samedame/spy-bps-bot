"""NOT a pass/fail check. How different could a ~3:45 pm snapshot be from the official close? The research only has daily closes, so
the intraday noise below is an ASSUMPTION used to size the effect, not data. For each of the research's 695 real entry dates, perturb
SPY and VIX by random noise and see how often the strikes the bot would alert are the same as at the close."""
import os, sys, random, math
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as RP
from bps_bot.engine import Bar, plan_entry

def run(seed=7):
    E = RP.load_research_engine(); df = E.load("SPY")
    entries = pd.read_csv(os.path.join(RP.RESEARCH, "results", "winner_trades_risk2.csv"))["entry"].tolist()
    out = []
    for sig_s, sig_v in ((0.0005, 0.10), (0.0010, 0.20), (0.0020, 0.40)):
        rng = random.Random(seed); same = same_short = n = 0; credit_diffs = []
        for d in entries:
            row = df.loc[pd.Timestamp(d)]; S, v, t = float(row.Close), float(row.VIX), float(row.TNX)
            base = plan_entry(Bar(pd.Timestamp(d).date(), S, v, t))
            alt = plan_entry(Bar(pd.Timestamp(d).date(), S * (1 + rng.gauss(0, sig_s)), max(v + rng.gauss(0, sig_v), 5.0), t))
            n += 1; same += (base.short_k, base.long_k) == (alt.short_k, alt.long_k); same_short += base.short_k == alt.short_k
            credit_diffs.append(abs(alt.credit_per_lot - base.credit_per_lot) / 100)
        out.append(dict(assumed_spy_noise_pct=sig_s * 100, assumed_vix_noise_pts=sig_v, entry_dates=n, same_strikes_pct=round(100 * same / n, 1),
                        same_short_strike_pct=round(100 * same_short / n, 1), median_credit_change_per_share=round(sorted(credit_diffs)[len(credit_diffs) // 2], 3)))
    return out

if __name__ == "__main__":
    import json; print(json.dumps(run(), indent=1))
