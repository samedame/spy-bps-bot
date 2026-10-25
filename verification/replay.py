"""Replay harness: feed the bot's step() the research data one day at a time and collect trades + the MTM equity curve.
Used by verify_parity.py and mutation.py. Needs pandas (not needed by the bot itself)."""
from __future__ import annotations
import os, sys, importlib.util
from datetime import date
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from bps_bot import calendar_nyse as CAL
from bps_bot.engine import Bar, State, step, equity_mtm
from bps_bot.spec import SPEC

RESEARCH = os.environ.get("RESEARCH_DIR", os.path.join(ROOT, ".."))

def load_research_engine():
    spec = importlib.util.spec_from_file_location("research_engine", os.path.join(RESEARCH, "code", "01_engine.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.DATA = os.path.join(RESEARCH, "data")
    return m

def load_bars(E):
    df = E.load("SPY")
    return df

def replay(df, start, end, risk_frac=0.02, cash0=100_000.0, sp=SPEC, use_calendar_prev=True, expiry_cap=True, step_fn=step):
    idx = df.index
    ii = [i for i, d in enumerate(idx) if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    i0, i1 = ii[0], ii[-1]
    cap = idx[-1].date() if expiry_cap else None
    state = State(cash=cash0)
    trades, eq, skipped = [], {}, 0
    for i in range(i0, i1 + 1):
        row = df.iloc[i]
        d = idx[i].date()
        bar = Bar(date=d, close=float(row["Close"]), vix=float(row["VIX"]), tnx_pct=float(row["TNX"]))
        prev = CAL.prev_trading_day(d) if use_calendar_prev else idx[i - 1].date()
        state, events = step_fn(state, bar, prev, allow_entry=(i > i0 and i < i1), expiry_cap=cap, sp=sp)
        for ev in events:
            if ev["type"] == "exit": trades.append(ev["trade"])
            if ev["type"] == "entry_skipped": skipped += 1
        eq[idx[i]] = equity_mtm(state, bar, sp)
    tr = pd.DataFrame(trades)
    return tr, pd.Series(eq).sort_index(), state, skipped
