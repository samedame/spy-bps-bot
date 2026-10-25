"""Layer 6 (needs network): the live data path. (a) Yahoo's SPY / ^VIX / ^TNX daily closes must equal the research CSVs on the
overlapping days (same series the research used); (b) the real runner, with the real Yahoo feed, reconciles a day end to end
(dry run, temp ledger). Reported as NOT RUN (not a failure) if Yahoo is unreachable."""
import csv, os, sys, tempfile
from datetime import date, datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bps_bot import run as R, calendar_nyse as CAL
from bps_bot.data import YahooFeed, DataUnavailable
from bps_bot.engine import State
from bps_bot.ledger import Ledger
RESEARCH = os.environ.get("RESEARCH_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

def run(window_days=60):
    feed = YahooFeed(); end = date.fromisoformat("2026-10-23"); start = end - timedelta(days=window_days)
    out = {}
    try:
        for sym, fn in (("SPY", "spy.csv"), ("^VIX", "vix.csv"), ("^TNX", "tnx.csv")):
            ref = {date.fromisoformat(r["Date"][:10]): float(r["Close"]) for r in csv.DictReader(open(os.path.join(RESEARCH, "data", fn)))}
            got = feed.daily_closes(sym, start, end)
            common = [d for d in got if d in ref]
            maxdiff = max(abs(got[d] - ref[d]) for d in common) if common else None
            out[sym] = dict(days_compared=len(common), max_abs_diff=maxdiff, missing_in_yahoo=len([d for d in ref if start <= d <= end and d not in got]))
        px, t = feed.live_quote("SPY"); out["live_quote_spy"] = dict(price=px, time_utc=t.isoformat())
        tmp = tempfile.mkdtemp(prefix="bps_smoke_"); led = Ledger(tmp); led.save_state(State(cash=161549.829822, last_date="2026-10-22"))
        class Cap:
            sent = []
            def post(self, text): self.sent.append(text)
        cap = Cap()
        rc = R.main(["reconcile", "--ledger", tmp, "--as-of", "2026-10-23", "--retries", "1", "--dry-run"], feed=feed, notifier=cap,
                    now_utc=datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc))
        out["end_to_end_reconcile_dry_run"] = dict(returncode=rc, message=cap.sent[0] if cap.sent else None)
        ok = rc == 0 and all(v["max_abs_diff"] is not None and v["max_abs_diff"] < 1e-6 and v["missing_in_yahoo"] == 0 for k, v in out.items() if k in ("SPY", "^VIX", "^TNX"))
        out["pass"] = bool(ok); out["ran"] = True
    except DataUnavailable as e:
        out = {"ran": False, "pass": True, "reason": str(e)[:200]}
    return out

if __name__ == "__main__":
    import json; r = run(); print(json.dumps(r, indent=1, default=str)); sys.exit(0 if r["pass"] else 1)
