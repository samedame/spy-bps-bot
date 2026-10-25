"""Layer 4: the rule-based NYSE calendar must reproduce every SPY trading day in the research data (expiry dates and the
'first trading day of the week' rule depend on it)."""
import csv, os, sys
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bps_bot import calendar_nyse as C
RESEARCH = os.environ.get("RESEARCH_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

def run():
    days = [date.fromisoformat(r["Date"][:10]) for r in csv.DictReader(open(os.path.join(RESEARCH, "data", "spy.csv")))]
    s = set(days); lo, hi = min(s), max(s); cal = set(); d = lo
    while d <= hi:
        if C.is_trading_day(d): cal.add(d)
        d += timedelta(days=1)
    return dict(first=str(lo), last=str(hi), data_days=len(s), calendar_days=len(cal), in_data_not_calendar=[str(x) for x in sorted(s - cal)],
                in_calendar_not_data=[str(x) for x in sorted(cal - s)], **{"pass": s == cal})

if __name__ == "__main__":
    import json; r = run(); print(json.dumps(r, indent=1)); sys.exit(0 if r["pass"] else 1)
