"""NYSE trading calendar from rules (no network, no dependencies).

The engine finds the expiry as the first trading day on/after entry+14 calendar days and the "first trading day of the week"
from the previous trading day, so the bot needs the same trading-day set. verification/calendar_check.py compares this
calendar with every SPY trading day in the research data (2007-2026).
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from typing import FrozenSet

# Unscheduled closures (national days of mourning, storms). Add new ones via env EXTRA_MARKET_CLOSURES=YYYY-MM-DD,YYYY-MM-DD
SPECIAL_CLOSURES = {
    date(2007, 1, 2),    # Ford funeral
    date(2012, 10, 29),  # Hurricane Sandy
    date(2012, 10, 30),
    date(2018, 12, 5),   # Bush funeral
    date(2025, 1, 9),    # Carter funeral
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date | None:
    """Saturday holidays are observed Friday, Sunday holidays Monday (except New Year's on Saturday: no Friday closure)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def holidays(year: int) -> FrozenSet[date]:
    h = set()
    ny = date(year, 1, 1)
    if ny.weekday() != 5:  # Saturday Jan 1: market open the prior Friday
        h.add(_observed(ny))
    h.add(_nth_weekday(year, 1, 0, 3))                 # Martin Luther King Jr. Day
    h.add(_nth_weekday(year, 2, 0, 3))                 # Washington's Birthday
    h.add(_easter(year) - timedelta(days=2))           # Good Friday
    h.add(_last_weekday(year, 5, 0))                   # Memorial Day
    if year >= 2022:
        h.add(_observed(date(year, 6, 19)))            # Juneteenth
    h.add(_observed(date(year, 7, 4)))                 # Independence Day
    h.add(_nth_weekday(year, 9, 0, 1))                 # Labor Day
    h.add(_nth_weekday(year, 11, 3, 4))                # Thanksgiving
    h.add(_observed(date(year, 12, 25)))               # Christmas
    return frozenset(h)


def _extra() -> set:
    out = set()
    for tok in os.environ.get("EXTRA_MARKET_CLOSURES", "").split(","):
        tok = tok.strip()
        if tok:
            out.add(date.fromisoformat(tok))
    return out


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    if d in holidays(d.year) or d in SPECIAL_CLOSURES or d in _extra():
        return False
    return True


def next_trading_day(d: date) -> date:
    """First trading day strictly after d."""
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def prev_trading_day(d: date) -> date:
    """Last trading day strictly before d."""
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def on_or_after(d: date) -> date:
    """First trading day on or after d."""
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def trading_days_between(start_exclusive: date, end_inclusive: date):
    d = start_exclusive
    out = []
    while True:
        d = next_trading_day(d)
        if d > end_inclusive:
            return out
        out.append(d)
