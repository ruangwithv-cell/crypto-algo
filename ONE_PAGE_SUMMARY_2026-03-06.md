# One-Page Summary: Crypto Algo Session
Date: 2026-03-06

## Objective
Replace discretionary, noisy short decisions with a fully systematic and automated process, then run shadow validation before deploying meaningful capital.

## What Is Now Live
- Daily automated job at **08:00** via LaunchAgent:
  - `com.rv.cryptoalgo.unrestricted.daily`
- Daily workflow now executes:
  1. Pull Binance data (broad perp universe)
  2. Generate action memo (short sleeve)
  3. Update shadow PnL
  4. Send Telegram message #1 (action memo)
  5. Send Telegram message #2 (PnL summary)
  6. Record long scenario snapshots for `top50/top100/top200`

## Strategy Direction
- **Short sleeve (active)**: unchanged core logic, regime-gated, rule-based selection, inverse-vol sizing, capped gross exposure.
- **Long sleeve (research track)**: scenario generation for top liquid subsets (`top50`, `top100`, `top200`) to support potential market-neutral deployment.

## Why This Matters
- Eliminates day-to-day human bias and inconsistent manual overrides.
- Creates a full local audit trail for risk and performance review.
- Enables objective pass/fail decision after a fixed validation window.

## Current Recordkeeping
- Action memo, state, and logs saved locally every run.
- Shadow PnL logged to CSV for cumulative NAV tracking.
- Long-scenario snapshots logged daily for comparison.

## Decision Framework (Next 45 Days)
- Continue shadow run with frozen rules.
- Compare against EW short and BTC short benchmarks.
- Use pre-defined failure bounds and drawdown limits.
- Decide go/no-go at end of 45-day window.

## Key Files
- Full handover report:
  - `/Users/mini/crypto_algo/SESSION_HANDOVER_REPORT_2026-03-06.md`
- Detailed strategy handoff:
  - `/Users/mini/crypto_algo/UNRESTRICTED_ALGO_45D_HANDOFF_2026-03-06.md`
