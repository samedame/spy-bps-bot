# SPY bull put spread bot (`BP_d40_D14_W5_PT50_SL2`)

An **alert-only** Discord bot with a **paper ledger**, built from `options_research` (VERDICT.md, 2026-10-24). It reads SPY, VIX and the 10-year yield, applies the research's frozen rules, tells you what to do, and keeps a paper account that follows the research engine exactly. **It never places orders and has no broker connection.** The research's own label for this rule set is **PROMISING (proxy prices, capped), confidence LOW**; this bot inherits that. Educational, not financial advice; a bull put spread can lose its full width minus the credit.

## The rules (all from the research; none tuned here)
| | |
|---|---|
| Underlying | SPY |
| When | first trading day of each week, only if no position is open (a position closed today can be replaced today) |
| Structure | sell the ~40-delta put, buy the put 5% of spot lower ($1 strikes), expiry = first trading day on/after 14 calendar days |
| Exits (checked at each daily close) | close at +50% of the credit; close at -200% of the credit (fills at the close, so gaps can lose more); otherwise hold to expiry; no rolls |
| Size | whole spreads = floor(2% of equity / max loss of one spread) |
| Prices | the research's Black-Scholes/VIX proxy with pessimistic modeled spreads ($0.67/leg fees) |

Rule values live in `bps_bot/spec.py`. The bot compares their fingerprint with the one the verification ran against and **refuses to start if they differ** (`ALLOW_UNVERIFIED=1` overrides, knowingly).

## Read this first: the sizing rule
One spread risks about $3,100-$3,500 at today's SPY. Under the tested 2% rule that needs roughly **$155k-$175k** of equity. On a $1k-$10k account the rule sizes to **0 spreads**, so the bot cannot be traded as tested at that size; it is a signal and a paper ledger. XSP, narrower widths and larger risk fractions are different, untested strategies and are not in the bot. The paper ledger starts at **$161,549.83** (the research's continuous 2008-2026 run, flat, on 2026-10-23) and already skipped three Mondays in October for lot size.

## What you get in Discord
- **3:45 pm ET, only when something happens** (`alert`): ENTRY (strikes, expiry, modeled credit, max loss, spreads for the paper ledger and for `ACCOUNT_EQUITY`, the buy-back levels for target and stop), CLOSE (target or stop hit), EXPIRY DAY, or "entry day, NO SIZE". Alerts use a live snapshot; the research trades at the official close, so strikes can differ by $1 (see the verification report, section 4).
- **After the close, every trading day** (`reconcile`): applies the official close to the paper ledger and posts one line: confirms the alert, says it differs, or "no action" with the open position's P&L and the next entry day. It also catches up any days that were missed, in order.
- Errors are loud: no usable price, a missing official close, or a failed Discord post turns the workflow red and (where possible) posts a message. The ledger is not changed by a failed step.

## Setup (5 steps)
1. Create a GitHub repo (e.g. `samedame/spy-bps-bot`) and push this folder to its root.
2. Repo secret `DISCORD_WEBHOOK_URL`. Optional repo variable `ACCOUNT_EQUITY` (your real account, so alerts show your spread count).
3. Settings > Actions > General > Workflow permissions: **Read and write**.
4. Run the `tests` workflow once (should be green), then run `alert` and `reconcile` once with **Run workflow**. Outside market hours both exit quietly; `reconcile` posts its status line.
5. Locally, to try it without Discord: `python -m bps_bot.run reconcile --dry-run` (prints the message instead of posting).

The ledger (`ledger/state.json`, `trades.csv`, `equity.csv`, `pending_alert.json`) is committed by the workflows. To restart it: `python -m bps_bot.run init --force [--cash 100000]`.

### Scheduling
GitHub's own cron can start hours late, and a 3:45 pm alert that arrives after 4:00 pm is useless (the program then stays quiet, and the after-close message says no alert ran). For an on-time alert, add two jobs to your existing Cloudflare `open-scheduler` Worker the same way as the other bots: `bps-alert` at 15:45 ET -> `alert.yml`, and `bps-reconcile` at 16:20 ET -> `reconcile.yml` (repo, ref `main`, small grace). Remember the Worker's cron weekday numbering (Cloudflare: 1 = Sunday) and that 16:20 ET is 21:20 UTC after Nov 1.

## Layout
```
bps_bot/spec.py            frozen rules + fingerprint
bps_bot/pricing.py         Black-Scholes proxy, strikes, fills (standard library only)
bps_bot/engine.py          step(): one trading day in, state + events out (the verified logic)
bps_bot/calendar_nyse.py   NYSE holidays from rules
bps_bot/data.py            Yahoo SPY / ^VIX / ^TNX (same series as the research)
bps_bot/ledger.py          state.json, trades.csv, equity.csv (atomic writes)
bps_bot/messages.py        Discord text
bps_bot/run.py             init | alert | reconcile | status
tests/                     36 unit tests (fake feed, fake Discord)
verification/              parity suite + VERIFICATION_REPORT.md
.github/workflows/         alert, reconcile, tests
```

## Verification (summary; full detail in `verification/VERIFICATION_REPORT.md`)
Held against the research engine run fresh, the research's published trade files and its leaderboard row:
- the entry plan on all 4,732 trading days: 0 differences;
- IS (412 trades), OOS (242) and full-sample (695; 698 at 5% risk): same dates, exit reasons, lots; P&L and daily equity within $1e-9; all ten leaderboard statistics identical;
- the real runner driven day by day (ledger files, alerts, after-close, 15% of days skipped and caught up) with a feed that raises on any look-ahead: identical ledger;
- calendar equals all 4,984 SPY trading days; live Yahoo closes equal the research CSVs;
- mutation test: 25 of 26 deliberate deviations caught (the 26th cannot change behaviour on this data).

Not verified: real option quotes and fills (the strategy's prices are a proxy), Discord delivery and scheduler timing, and whether the strategy has an edge.

Re-run: `RESEARCH_DIR=/path/to/options_research python verification/run_all.py` (about 3 minutes; needs pandas, numpy, scipy, pytest). `python -m pytest tests -q` needs only pytest. If the bot lives at `options_research/bot/`, `RESEARCH_DIR` defaults to the parent folder.
