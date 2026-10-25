"""Market data: Yahoo Finance chart API for SPY (unadjusted close), ^VIX and ^TNX - the same series the research used.

The Feed interface is tiny so tests and the verification live-loop can plug in a fake. Nothing here places orders.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Protocol, Tuple

from . import calendar_nyse as CAL
from .engine import Bar

SYMBOLS = {"spy": "SPY", "vix": "^VIX", "tnx": "^TNX"}
MAX_STALE_DAYS = 5   # VIX/TNX may be carried forward this many calendar days (the research forward-filled them)


class DataUnavailable(RuntimeError):
    pass


class Feed(Protocol):
    def daily_closes(self, symbol: str, start: date, end: date) -> Dict[date, float]:
        """Final daily closes in [start, end]. Days without a final close are omitted."""

    def live_quote(self, symbol: str) -> Tuple[float, datetime]:
        """(last price, quote time as an aware datetime)."""


class YahooFeed:
    UA = "Mozilla/5.0 (compatible; bps-bot/1.0)"

    def _get(self, url: str, tries: int = 3) -> dict:
        last = None
        for k in range(tries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.UA})
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
                last = e
                time.sleep(2 * (k + 1))
        raise DataUnavailable(f"Yahoo request failed after {tries} tries: {last}")

    def _chart(self, symbol: str, query: str) -> dict:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
        j = self._get(url)
        res = (j.get("chart") or {}).get("result")
        if not res:
            raise DataUnavailable(f"Yahoo returned no chart result for {symbol}: {(j.get('chart') or {}).get('error')}")
        return res[0]

    def daily_closes(self, symbol: str, start: date, end: date) -> Dict[date, float]:
        p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()) - 86400
        p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 2 * 86400
        r = self._chart(symbol, f"interval=1d&period1={p1}&period2={p2}&includePrePost=false")
        ts = r.get("timestamp") or []
        closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        off = (r.get("meta") or {}).get("gmtoffset", 0)
        out: Dict[date, float] = {}
        for t, c in zip(ts, closes):
            if c is None:
                continue
            d = (datetime.fromtimestamp(t + off, tz=timezone.utc)).date()
            if start <= d <= end:
                out[d] = float(c)
        return out

    def live_quote(self, symbol: str) -> Tuple[float, datetime]:
        r = self._chart(symbol, "interval=1m&range=1d&includePrePost=false")
        m = r.get("meta") or {}
        px, t = m.get("regularMarketPrice"), m.get("regularMarketTime")
        if px is None or t is None:
            raise DataUnavailable(f"no live price for {symbol}")
        return float(px), datetime.fromtimestamp(int(t), tz=timezone.utc)


def _carry(series: Dict[date, float], d: date, what: str) -> Tuple[float, bool]:
    """Value on d, else the latest earlier value within MAX_STALE_DAYS (research forward-fill). Returns (value, was_carried)."""
    if d in series:
        return series[d], False
    earlier = [k for k in series if k < d and (d - k).days <= MAX_STALE_DAYS]
    if not earlier:
        raise DataUnavailable(f"{what} has no value for {d} or the {MAX_STALE_DAYS} days before it")
    return series[max(earlier)], True


def final_bars(feed: Feed, start_exclusive: date, end_inclusive: date) -> Tuple[Dict[date, Bar], Dict[date, str]]:
    """Official-close Bars for every trading day in (start_exclusive, end_inclusive]. Raises DataUnavailable if SPY lacks a
    final close on any of those days. Returns (bars, notes) where notes flags carried-forward VIX/TNX."""
    days = CAL.trading_days_between(start_exclusive, end_inclusive)
    if not days:
        return {}, {}
    lo = start_exclusive - timedelta(days=10)
    spy = feed.daily_closes(SYMBOLS["spy"], days[0], days[-1])
    vix = feed.daily_closes(SYMBOLS["vix"], lo, days[-1])
    tnx = feed.daily_closes(SYMBOLS["tnx"], lo, days[-1])
    bars, notes = {}, {}
    for d in days:
        if d not in spy:
            raise DataUnavailable(f"SPY has no final close for {d} yet")
        v, vc = _carry(vix, d, "VIX")
        t, tc = _carry(tnx, d, "TNX")
        bars[d] = Bar(date=d, close=spy[d], vix=v, tnx_pct=t, provisional=False)
        flags = [n for n, c in (("VIX", vc), ("TNX", tc)) if c]
        if flags:
            notes[d] = "+".join(flags) + " carried forward from an earlier day"
    return bars, notes


MAX_QUOTE_AGE_MIN = {"spy": 20, "vix": 20, "tnx": 240}   # the 10-year yield barely moves the strikes and can lag on Yahoo


def provisional_bar(feed: Feed, today: date, now_utc: datetime, max_age_min: Optional[int] = None) -> Tuple[Bar, str]:
    """Today's bar built from live quotes (the 3:45 pm alert). Raises if SPY or VIX is older than 20 min (yield: 4 h)."""
    vals = {}
    for k, sym in SYMBOLS.items():
        px, t = feed.live_quote(sym)
        age = (now_utc - t).total_seconds() / 60.0
        limit = max_age_min if max_age_min is not None else MAX_QUOTE_AGE_MIN[k]
        if age > limit:
            raise DataUnavailable(f"{sym} quote is {age:.0f} min old (limit {limit})")
        vals[k] = px
    return Bar(date=today, close=vals["spy"], vix=vals["vix"], tnx_pct=vals["tnx"], provisional=True), "live quotes"
