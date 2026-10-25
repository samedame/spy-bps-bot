"""State and history on disk: ledger/state.json (paper account + open position), trades.csv, equity.csv, pending_alert.json.
Writes are atomic (temp file + rename) so a crashed run cannot leave half a file."""
from __future__ import annotations

import csv
import json
import os
import tempfile
from typing import List, Optional

from .engine import State
from .spec import RESEARCH_DATA_END, RESEARCH_FULL_RUN_FINAL_EQUITY, SPEC, spec_hash

TRADE_COLS = ["entry", "exit", "pnl", "risk", "ror", "reason", "vix_entry", "credit", "debit", "contracts",
              "short_k", "long_k", "expiry"]
EQUITY_COLS = ["date", "equity_mtm", "cash", "open_position"]


def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class Ledger:
    def __init__(self, directory: str):
        self.dir = directory
        self.state_path = os.path.join(directory, "state.json")
        self.trades_path = os.path.join(directory, "trades.csv")
        self.equity_path = os.path.join(directory, "equity.csv")
        self.pending_path = os.path.join(directory, "pending_alert.json")

    # ---- state ----
    def exists(self) -> bool:
        return os.path.exists(self.state_path)

    def init_continuing_research(self, cash: float = RESEARCH_FULL_RUN_FINAL_EQUITY, as_of: str = RESEARCH_DATA_END) -> State:
        """Flat paper account that continues the research's verified 2008-2026 run from its last day."""
        st = State(cash=cash, position=None, last_date=as_of)
        self.save_state(st)
        return st

    def load_state(self) -> State:
        with open(self.state_path) as f:
            d = json.load(f)
        if d.get("spec_hash") != spec_hash(SPEC):
            raise RuntimeError("ledger/state.json was written for a different rule set (spec hash mismatch). "
                               "Start a new ledger rather than mixing rule sets.")
        return State.from_dict(d["state"])

    def save_state(self, st: State) -> None:
        _atomic_write(self.state_path, json.dumps({"version": 1, "spec_id": SPEC.spec_id, "spec_hash": spec_hash(SPEC),
                                                   "state": st.to_dict()}, indent=1, sort_keys=True) + "\n")

    # ---- trades / equity ----
    def append_trade(self, trade: dict) -> None:
        new = not os.path.exists(self.trades_path)
        os.makedirs(self.dir, exist_ok=True)
        with open(self.trades_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=TRADE_COLS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({k: repr(v) if isinstance(v, float) else v for k, v in trade.items()})

    def read_trades(self) -> List[dict]:
        if not os.path.exists(self.trades_path):
            return []
        with open(self.trades_path) as f:
            return list(csv.DictReader(f))

    def append_equity(self, date_iso: str, equity: float, cash: float, open_position: bool) -> None:
        new = not os.path.exists(self.equity_path)
        os.makedirs(self.dir, exist_ok=True)
        with open(self.equity_path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(EQUITY_COLS)
            w.writerow([date_iso, repr(float(equity)), repr(float(cash)), int(open_position)])

    def equity_dates(self) -> set:
        if not os.path.exists(self.equity_path):
            return set()
        with open(self.equity_path) as f:
            return {row["date"] for row in csv.DictReader(f)}

    # ---- pending alert (what the 3:45 pm run said, so the after-close run can say if it changed) ----
    def save_pending(self, payload: dict) -> None:
        _atomic_write(self.pending_path, json.dumps(payload, indent=1, sort_keys=True) + "\n")

    def load_pending(self) -> Optional[dict]:
        if not os.path.exists(self.pending_path):
            return None
        with open(self.pending_path) as f:
            return json.load(f)

    def clear_pending(self) -> None:
        if os.path.exists(self.pending_path):
            os.unlink(self.pending_path)
