"""Layer 3: drive the REAL runner (bps_bot.run.main: JSON ledger, alert + reconcile, catch-up) one trading day at a time.

A fake feed serves the research CSVs and raises if the bot ever asks for a price from after the simulated "now" (look-ahead).
The ledger it leaves behind must equal the research engine's trades and equity curve for the same window.
Scenarios: OOS from $100k, FULL from $100k, OOS again with ~15% of days never run (catch-up path).
"""
from __future__ import annotations
import bisect, csv, os, random, sys, tempfile, time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay as RP
from bps_bot import run as R
from bps_bot import calendar_nyse as CAL
from bps_bot.engine import State
from bps_bot.ledger import Ledger
from bps_bot.spec import SPEC

ET = ZoneInfo("America/New_York")


class LookAhead(AssertionError):
    pass


class RawCsvFeed:
    """Serves raw (not forward-filled) daily closes from the research CSVs; enforces no look-ahead."""
    def __init__(self, data_dir):
        self.series = {}
        for sym, fn in (("SPY", "spy.csv"), ("^VIX", "vix.csv"), ("^TNX", "tnx.csv")):
            rows = [(date.fromisoformat(r["Date"][:10]), float(r["Close"])) for r in csv.DictReader(open(os.path.join(data_dir, fn))) if r["Close"] not in ("", "nan")]
            rows.sort()
            self.series[sym] = ([d for d, _ in rows], [v for _, v in rows])
        self.visible_until = None; self.live = {}; self.live_now = None; self.requests = 0

    def daily_closes(self, symbol, start, end):
        self.requests += 1
        if end > self.visible_until:
            raise LookAhead(f"bot asked for {symbol} through {end}, but the simulated clock only allows {self.visible_until}")
        ds, vs = self.series[symbol]
        lo, hi = bisect.bisect_left(ds, start), bisect.bisect_right(ds, end)
        return {ds[i]: vs[i] for i in range(lo, hi)}

    def live_quote(self, symbol):
        return self.live[symbol], self.live_now - timedelta(minutes=2)


class Hook:
    def __init__(self): self.sent = []
    def post(self, text): self.sent.append(text)


def run_scenario(name, start, end, cash0, skip_frac=0.0, seed=1, with_alerts=True, research=None):
    E = RP.load_research_engine(); df = E.load("SPY"); df._sym = "SPY"
    import verify_parity as VP
    spec = VP.research_engine_spec()
    tr_ref, eq_ref = E.run_spread(df, spec, start, end, risk_frac=SPEC.risk_frac, equity0=cash0)
    feed = RawCsvFeed(os.path.join(RP.RESEARCH, "data"))
    days = [d.date() for d in df.index if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    tmp = tempfile.mkdtemp(prefix="bps_live_"); led = Ledger(tmp)
    led.save_state(State(cash=cash0, last_date=CAL.prev_trading_day(days[0]).isoformat()))
    hook = Hook(); rng = random.Random(seed)
    skipped_days, alerts_posted, diff_notices, errors = 0, 0, 0, 0
    t0 = time.time()
    for d in days:
        if skip_frac and rng.random() < skip_frac and d != days[-1]:
            skipped_days += 1; continue
        if with_alerts:
            feed.visible_until = CAL.prev_trading_day(d)         # at 3:45 pm only yesterday's close is final
            row = df.loc[pd.Timestamp(d)]
            now = datetime(d.year, d.month, d.day, 15, 45, tzinfo=ET).astimezone(timezone.utc)
            feed.live_now = now
            # the 3:45 quote stands in for the close (the research only has closes), so alert and close must agree exactly
            feed.live = {"SPY": float(row["Close"]), "^VIX": float(row["VIX"]), "^TNX": float(row["TNX"])}
            n0 = len(hook.sent)
            rc = R.main(["alert", "--ledger", tmp], feed=feed, notifier=hook, now_utc=now)
            errors += rc != 0; alerts_posted += len(hook.sent) - n0
        feed.visible_until = d                                   # after 4:10 pm today's close is final
        now = datetime(d.year, d.month, d.day, 16, 30, tzinfo=ET).astimezone(timezone.utc)
        n0 = len(hook.sent)
        rc = R.main(["reconcile", "--ledger", tmp, "--retries", "1"], feed=feed, notifier=hook, now_utc=now)
        errors += rc != 0
        diff_notices += sum("differs from the 3:45 pm alert" in m for m in hook.sent[n0:])
    tr_led = pd.DataFrame(led.read_trades())
    cols_cat, cols_num = ["entry", "exit", "reason", "contracts"], ["pnl", "risk", "ror", "vix_entry", "credit", "debit"]
    res = dict(name=name, window=f"{start}..{end}", cash0=cash0, days=len(days), days_never_run=skipped_days, runner_errors=errors,
               trades_ledger=len(tr_led), trades_engine=len(tr_ref), alert_messages=alerts_posted, difference_notices=diff_notices,
               seconds=round(time.time() - t0, 1))
    ok = len(tr_led) == len(tr_ref)
    if ok:
        for c in cols_num: tr_led[c] = tr_led[c].astype(float)
        res["categorical_identical"] = all((tr_led[c].astype(str).values == tr_ref[c].astype(str).values).all() for c in cols_cat)
        res["max_abs_trade_diff"] = float(max(np.abs(tr_led[c].values - tr_ref[c].astype(float).values).max() for c in cols_num))
        ok = res["categorical_identical"] and res["max_abs_trade_diff"] < 1e-6
    eq_led = pd.read_csv(os.path.join(tmp, "equity.csv"), index_col=0, parse_dates=True)["equity_mtm"]
    st = led.load_state()
    # The research engine caps every expiry at its last data bar (2026-10-23). A live run has no such cap, so near the end of the data a
    # NEW entry can differ. Boundary = entry date of a position still open whose real expiry lies beyond the data end (if any).
    data_end = df.index[-1].date()
    boundary = None
    if st.position is not None and date.fromisoformat(st.position.expiry_date) > data_end:
        boundary = date.fromisoformat(st.position.entry_date)
    _, eq_unc, st_unc, _ = RP.replay(df, start, end, cash0=cash0, expiry_cap=False)
    j = pd.concat([eq_led, eq_ref, eq_unc], axis=1, join="outer"); j.columns = ["ledger", "engine", "uncapped_core"]
    res["equity_rows"] = int(eq_led.shape[0]); res["equity_rows_engine"] = int(eq_ref.shape[0])
    res["equity_vs_uncapped_replay_max_abs_diff"] = float((j.ledger - j.uncapped_core).abs().max())
    before = j[j.index < pd.Timestamp(boundary)] if boundary else j
    res["equity_vs_engine_max_abs_diff_before_boundary"] = float((before.ledger - before.engine).abs().max())
    res["engine_end_of_data_expiry_cap_boundary"] = str(boundary) if boundary else None
    res["days_differing_from_engine_after_boundary"] = int(((j.ledger - j.engine).abs() > 1e-6).sum())
    ok = ok and res["equity_vs_uncapped_replay_max_abs_diff"] < 1e-6 and res["equity_vs_engine_max_abs_diff_before_boundary"] < 1e-6
    res["equity_max_abs_diff"] = max(res["equity_vs_uncapped_replay_max_abs_diff"], res["equity_vs_engine_max_abs_diff_before_boundary"])
    res["final_cash_ledger"] = st.cash
    res["final_cash_engine_equity"] = float(eq_ref.iloc[-1])
    res["final_state_last_date"] = st.last_date
    res["open_position_at_end"] = bool(st.position is not None)
    res["pass"] = bool(ok and errors == 0 and diff_notices == 0)
    return res


def run_all(quick=False):
    out = []
    out.append(run_scenario("OOS from $100k, alert+reconcile every day", "2019-01-01", "2026-10-23", 100_000.0))
    out.append(run_scenario("OOS from $100k, 15% of days never run (catch-up)", "2019-01-01", "2026-10-23", 100_000.0, skip_frac=0.15, with_alerts=False))
    if not quick:
        out.append(run_scenario("FULL 2008-2026 from $100k, alert+reconcile every day", "2008-01-01", "2026-10-23", 100_000.0))
    return out


if __name__ == "__main__":
    import json
    r = run_all(quick="--quick" in sys.argv); print(json.dumps(r, indent=1, default=float)); sys.exit(0 if all(x["pass"] for x in r) else 1)
