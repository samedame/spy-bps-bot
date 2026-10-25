# Verification report: SPY bull put spread bot (`BP_d40_D14_W5_PT50_SL2`)
Generated 2026-10-24 08:57 UTC by `verification/run_all.py` (160 s). **Overall: PASS.**

**What this proves, and what it does not.** It proves the bot makes the same decisions, with the same numbers, as the research code and the published research results: same strikes, expiries, lots, exits, P&L and statistics. It does **not** re-validate the strategy. The research itself labels this rule set PROMISING (proxy prices, capped), confidence LOW, and "nothing confirmed"; the bot inherits that label.

## 1. What was held against what
| Reference | Role |
|---|---|
| `code/01_engine.py` + `02_run_grid.py` (the research engine, run fresh here) | the oracle for every trade and every daily equity value |
| `results/winner_trades_risk2.csv`, `winner_trades_risk5.csv`, `winner_equity_risk2.csv` | the research's own published output for this spec |
| `LEADERBOARD.csv` row `BP_d40_D14_W5_PT50_SL2` | the published IS / OOS statistics |
| `results/reimpl_is.json`, `reimpl_oos.json` | the research's own independent re-implementation (Gate 9), reported for context |
| `data/spy.csv`, `vix.csv`, `tnx.csv` | the exact price inputs |

Rule-set fingerprint (`spec_hash`): `40a007e6d8b8eb17c0d2076d78f837a93a926ede18e7f09357c92f807d10c196`. It equals the value recorded in `bps_bot/spec.py` (PASS); the bot refuses to run if it ever differs. `PREREGISTRATION.md` SHA-256 still equals the frozen value (PASS).

Input fingerprints (SHA-256, so this report can be tied to the exact files):

```
583209c058e90f36...  PREREGISTRATION.md
cfd6d07464365c98...  code/01_engine.py
75f59e5514271789...  code/02_run_grid.py
8bc42100304f1eaa...  data/spy.csv
40dce264a55182ed...  data/vix.csv
ab025af597e1a16e...  data/tnx.csv
3cf09edd301074df...  LEADERBOARD.csv
c53be0acea8e413e...  results/winner_trades_risk2.csv
4279cff5b9e4b8f9...  results/winner_trades_risk5.csv
a3d7ca05201a2c9f...  results/winner_equity_risk2.csv
```

## 2. Results by layer
| # | Layer | What was compared | Result |
|---|---|---|---|
| 1 | Entry plan, every trading day | strikes, expiry, modeled credit, max loss on 4,732 days (traded or not) | PASS: 0 mismatches; max credit diff $1.7e-11 |
| 2 | Trades + daily equity, IS risk=2% | 412 bot vs 412 engine trades; dates, reasons, lots, P&L, MTM equity | PASS: max equity diff $6.1e-10 |
| 2 | Trades + daily equity, OOS risk=2% | 242 bot vs 242 engine trades; dates, reasons, lots, P&L, MTM equity | PASS: max equity diff $1.9e-10 |
| 2 | Trades + daily equity, FULL risk=2% | 695 bot vs 695 engine trades; dates, reasons, lots, P&L, MTM equity | PASS: max equity diff $7.9e-10 |
| 2 | Trades + daily equity, FULL risk=5% | 698 bot vs 698 engine trades; dates, reasons, lots, P&L, MTM equity | PASS: max equity diff $4.9e-09 |
| 2 | Published trade files | FULL 2%: 695 trades; FULL 5%: 698 trades | PASS: max P&L diff $1.3e-10 |
| 3 | Real runner, OOS from $100k, alert+reconcile every day | 1,964 days; ledger files vs engine | PASS: 242/242 trades, equity diff $1.2e-10, 0 errors, 0 alert-vs-close differences |
| 3 | Real runner, OOS from $100k, 15% of days never run (catch-up) | 1,964 days; 292 never run; ledger files vs engine | PASS: 242/242 trades, equity diff $1.2e-10, 0 errors, 0 alert-vs-close differences |
| 3 | Real runner, FULL 2008-2026 from $100k, alert+reconcile every day | 4,733 days; ledger files vs engine | PASS: 695/695 trades, equity diff $7.3e-10, 0 errors, 0 alert-vs-close differences |
| 4 | Trading calendar | 4,984 SPY trading days 2007-2026 vs rule-based calendar | PASS: 0 + 0 differences |
| 5 | Mutation test | 26 deliberate deviations | PASS: 25/26 caught; survivors: entry-day rule '<=' -> '<' (equivalent, see 3.5) |
| 6 | Live data path (Yahoo) | SPY/VIX/TNX closes vs research CSVs; real runner end to end (dry run) | PASS: 44 days, max diff 0 |
| 7 | Unit tests | `pytest tests` | PASS: 36 passed in 0.20s |

## 3. Details
### 3.1 Statistics reproduced (IS and OOS, 2% risk, $100k, same windows as the research)
| Metric | IS published | IS bot | OOS published | OOS bot |
|---|---|---|---|---|
| Trades | 412 | 412 | 242 | 242 |
| Win rate | 81.31% | 81.31% | 87.19% | 87.19% |
| CAGR | 1.83% | 1.83% | 3.39% | 3.39% |
| Sharpe | 0.619 | 0.619 | 1.351 | 1.351 |
| Sortino | 0.668 | 0.668 | 1.421 | 1.421 |
| Max drawdown | -10.55% | -10.55% | -2.96% | -2.96% |
| Profit factor | 1.342 | 1.342 | 2.078 | 2.078 |
| Expectancy (on risk) | 2.87% | 2.87% | 7.36% | 7.36% |
| Trades / year | 37.5 | 37.5 | 31.0 | 31.0 |

Largest relative difference over all ten statistics: IS 2.8e-14, OOS 8.7e-15 (floating-point noise).

### 3.2 Full-sample run (2008-01-02 to 2026-10-23, continuous)
Final equity: bot $161,549.83 vs published $161,549.83. This is the account the paper ledger continues from: it starts flat at $161,549.83 on 2026-10-23.

### 3.3 The research's own independent re-implementation (context)
Gate 9 of the research compared two code paths within tolerance (trades +/-2%, P&L +/-5%). Bot vs that re-implementation: IS 412 vs 408 trades, P&L $22,122 vs $21,321; OOS 242 vs 242 trades, P&L $29,699 vs $29,910. The bot matches the **primary engine** exactly (section 2); the re-implementation differs from the engine by the small amounts the research already reported and accepted. The bot follows the engine because that is what produced every published number.

### 3.4 Real runner scenarios (layer 3)
The runner is the code the scheduler calls: it reads and writes the JSON/CSV ledger, applies `reconcile` after each close and `alert` at 3:45 pm. The fake feed serves raw (not forward-filled) research CSVs and **raises if the bot asks for a price from after the simulated clock**, so passing also proves there is no look-ahead.

| Scenario | Days | Never run | Trades | Equity rows | Alert messages | Alert vs close differences | Final equity (ledger vs engine) |
|---|---|---|---|---|---|---|---|
| OOS from $100k, alert+reconcile every day | 1,964 | 0 | 242 / 242 | 1964 / 1964 | 550 | 0 | $129,699.38 / $129,699.38 |
| OOS from $100k, 15% of days never run (catch-up) | 1,964 | 292 | 242 / 242 | 1964 / 1964 | 0 | 0 | $129,699.38 / $129,699.38 |
| FULL 2008-2026 from $100k, alert+reconcile every day | 4,733 | 0 | 695 / 695 | 4733 / 4733 | 1397 | 0 | $162,251.12 / $161,549.83 |

In the "never run" scenario about 15% of days were skipped at random; the next `reconcile` caught up day by day in order and produced the identical ledger.

**Boundary effect in "FULL 2008-2026 from $100k, alert+reconcile every day".** Every trade matches the engine, and the ledger's equity matches the engine on every day before 2026-10-19 (max diff $7.3e-10) and matches an uncapped replay of the bot core on all 4,733 days (max diff $1.5e-10). The ledger differs from the engine on exactly 5 days at the very end because the research engine caps every expiry at its last data bar (2026-10-23): on 2026-10-19 it priced a 4-day spread (credit about $291, 0 lots), whereas a live run prices the real 14-day expiry of 2026-11-02 (credit about $701, 1 lot) and opens a position. This is an artifact of where the research data stops, not a difference in rules.

### 3.5 Mutation test (layer 5)
Each row is one deliberate change to the bot; "caught" means the parity check stopped matching the engine.

| Deviation introduced | Caught | Where |
|---|---|---|
| delta 0.40 -> 0.30 | yes | OOS |
| delta 0.40 -> 0.41 | yes | OOS |
| dte 14 -> 15 | yes | OOS |
| width 5% -> 4% | yes | OOS |
| profit target 50% -> 49% | yes | OOS |
| stop 2.0x -> 2.1x | yes | OOS |
| stop removed | yes | OOS |
| risk 2% -> 2.1% | yes | OOS |
| slippage 100% -> 99% | yes | OOS |
| commission 0.65 -> 0.64 | yes | OOS |
| div yield 1.5% -> 1.51% | yes | OOS |
| skew_down 0.35 -> 0.36 | yes | OOS |
| skew_up 0.10 -> 0.11 | yes | OOS |
| pin fee 25 -> 0 | yes | OOS |
| pin zone 0.25% -> 0.30% | yes | OOS |
| half-spread pct 2% -> 2.1% | yes | OOS |
| IV term slope 0.04 -> 0.041 | yes | OOS |
| IV floor 8% -> 9% | yes | FULL |
| far-OTM spread mult 1.5 -> 1.0 | yes | OOS |
| entry-day rule '<=' -> '<' | **no** | - |
| entry only on Mondays (holiday weeks skipped) | yes | OOS |
| long strike truncated with int() instead of round() | yes | OOS |
| short strike floored instead of rounded | yes | OOS |
| lots: ceil instead of floor | yes | OOS |
| no same-day re-entry after an exit | yes | OOS |
| expiry settled one day late | yes | OOS |

Survivor `entry-day rule '<=' -> '<'` is an equivalent mutant: differs only if two consecutive trading days fall on the same weekday (a gap of exactly 7 days); number of such gaps in the 2007-2026 SPY data = 0.

The unmutated bot matched on both windows, so every catch is a real deviation. The IV-floor mutant only shows on the full window because VIX was below ~9.3 only before 2019.

## 4. Things the verification found that you should know
1. **The sizing rule starves the strategy of lots.** At 2% risk, one spread must have max loss <= 2% of equity. SPY's rise pushed one spread's max loss to about $3,100-$3,500, so on a $100k account the OOS replay skipped **66 entry weeks** (that run takes only 3 trades in 2026); the continuous run skipped 7. The paper ledger starts at $161,550 and **already skipped Oct 5, 12 and 19, 2026** (max loss $3,258 / $3,362 / $3,509 vs a $3,231 budget). One spread needs about $155k-$175k of equity under the tested rule. The bot reports this on every entry day instead of quietly resizing, because any other size is an untested strategy.
2. **`results/deployability.json` is a simplified illustration, not the engine.** It shows credit $7.2128 and max loss $3,078.72 *before* the two $0.67 entry fees and truncates the long strike with `int()`; the engine (which produced all trades and statistics, and which the bot follows) uses after-fee credit $7.1994 and max loss $3,080.06 and rounds the long strike. The bot reproduces the published illustration exactly once the fees are added back (tested), and the difference cannot change a lot count except at a knife-edge.
3. **The research's own run ends with an end-of-data artifact.** The engine caps every expiry at its last data bar, so its 2026-10-19 entry was priced as a 4-day spread and skipped for lot size. Under the same rules with the real expiry (2026-11-02) that Monday would have opened 1 spread (761/723). The paper ledger starts flat from the engine's final state ($161,549.83 on 2026-10-23) and does not back-fill that hypothetical trade.
4. **A 3:45 pm alert is not the verified fill.** The research trades at the official daily close. The alert uses a live snapshot, so its strikes can differ from the close's. The research has only daily closes, so this is a sensitivity with *assumed* intraday noise, not a measurement:

| Assumed SPY move 3:45 pm to close | Assumed VIX move | Entry dates where the alerted strikes equal the close's | Median change in model credit |
|---|---|---|---|
| 0.05% (1 sd) | 0.10 pts | 89.2% | $0.027 / share |
| 0.10% (1 sd) | 0.20 pts | 77.7% | $0.052 / share |
| 0.20% (1 sd) | 0.40 pts | 61.7% | $0.094 / share |

The after-close run therefore compares itself with the alert and posts a difference notice when they disagree; the paper ledger always follows the official close, so it stays equal to the verified engine.

## 5. Not verified (and why)
- **Real option prices and fills.** The verified strategy uses the research's Black-Scholes/VIX proxy with pessimistic modeled spreads. The bot's "credit" is that proxy, not a quote. No real chain history exists in the research (the verdict names this as the step from PROMISING to CONFIRMED).
- **Whether the strategy has an edge.** Not the question here. The research's own gates: DSR fails, confidence LOW, proxy-capped at PROMISING.
- **Discord delivery, GitHub Actions scheduling, Cloudflare triggers.** Not reachable from the verification machine. Posting is exercised only with a fake webhook; scheduling logic is exercised by unit tests with injected clocks.
- **Your real fills.** The ledger is the paper model; it does not know what you actually traded.
- **Refinements the research left untested** (kill-switch, vol-scaled sizing, XSP, narrower widths) are deliberately **not** in the bot.
- **Backtest-edge artifacts.** The research engine caps an expiry at the last data bar and forbids entries on the final bar of a window; the replay reproduces both so the comparison is exact, and neither can occur live.

## 6. Re-running
```
RESEARCH_DIR=/path/to/options_research python verification/run_all.py          # all layers (~4 min)
RESEARCH_DIR=... python verification/run_all.py --quick   # skips the 2008-2026 live-loop scenario
python -m pytest tests -q                                  # unit tests only (no research folder needed)
```
