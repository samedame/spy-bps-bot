# Retired 2026-11-13

The SPY bull-put-spread bot is superseded by Premium-Sleeve (same SPY premium, one sleeve instead of four). Ledger position at retirement: none (cash 161,980.34, last_date 2026-11-06).

**What changed:** the GitHub schedule (cron) blocks are commented out and every job now needs the repository variable `RETIRED_ENABLED` set to `true`. Without it, any run (including a dispatch from the Cloudflare `open-scheduler` Worker) is skipped, not billed.

**To bring it back:** set the variable (Settings > Secrets and variables > Actions > Variables), then restore the `schedule:` block in each workflow.

**Still to do outside this repo:** remove this bot's jobs from the `open-scheduler` Worker table and from BotDeck. Source: `claude/bot-fleet-optimization-scan-2026-11-13.md` in the Personal investor project.
