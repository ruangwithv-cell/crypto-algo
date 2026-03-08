# Session Handover Report (Crypto Algo)
Date: 2026-03-06  
Owner: mini  
Project: `/Users/mini/crypto_algo`

## Executive Summary
During this session, the trading workflow was rebuilt into an automated, rule-based system focused on reducing discretionary noise.  
The system now:
- pulls market data daily from Binance,
- generates short-side action memos,
- sends Telegram notifications automatically,
- logs shadow PnL locally,
- and records 3 long-sleeve scenarios (`top50`, `top100`, `top200`) for market-neutral research.

The daily job is now active via `launchd` at **08:00** local machine time.

## What Was Built
### 1) New Core Strategy Track
- Implemented unrestricted short strategy module:
  - `/Users/mini/crypto_algo/crypto_algo/bear_unrestricted_backtest.py`
- Implemented live memo generator:
  - `/Users/mini/crypto_algo/crypto_algo/bear_unrestricted_live.py`
- Added symbol sanitation and eligibility filters (history/liquidity/stable exclusions).

### 2) Data Expansion
- Extended data pull from fixed manual symbols to auto-universe discovery:
  - `/Users/mini/crypto_algo/crypto_algo/binance_data_extender.py`
- Universe source is now Binance USDT perpetuals (capped in pipeline at 150).

### 3) Daily Automation + Notifications
- Daily runner:
  - `/Users/mini/crypto_algo/run_unrestricted_daily_telegram.sh`
- LaunchAgent plist (08:00 daily):
  - `/Users/mini/crypto_algo/com.rv.cryptoalgo.unrestricted.daily.plist`
- Telegram sender integrated using OpenClaw bot token/account:
  - `/Users/mini/crypto_algo/crypto_algo/telegram_notify.py`
- Configured env override:
  - `/Users/mini/.env.crypto_algo_telegram`

### 4) Shadow PnL Tracking
- Daily shadow PnL tracker:
  - `/Users/mini/crypto_algo/crypto_algo/shadow_pnl_daily.py`
- Daily PnL text summary formatter (for second Telegram message):
  - `/Users/mini/crypto_algo/crypto_algo/shadow_pnl_summary.py`

### 5) Long-Sleeve Research Scenarios
- Long candidate generator:
  - `/Users/mini/crypto_algo/crypto_algo/long_sleeve_candidates.py`
- Scenario recorder for `top50/top100/top200`:
  - `/Users/mini/crypto_algo/crypto_algo/long_sleeve_record_scenarios.py`
- Integrated scenario recording into daily runner.

## Current Live/Operational State
- LaunchAgent confirmed running under:
  - `com.rv.cryptoalgo.unrestricted.daily`
- Schedule:
  - Daily at **08:00**
- Telegram:
  - Two daily messages configured:
    1. Action memo
    2. Shadow PnL summary
- Local logging is active.

## Key Output Locations
### Daily action + state
- Latest memo:
  - `/Users/mini/crypto_algo/state_live/unrestricted_latest_action_memo.txt`
- Live state:
  - `/Users/mini/crypto_algo/state_live/unrestricted_live_state.json`

### Shadow PnL
- Tracker state:
  - `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_state.json`
- Daily PnL history CSV:
  - `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_daily.csv`
- Latest PnL Telegram text:
  - `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_latest.txt`

### Long-sleeve scenarios
- Latest `top50`:
  - `/Users/mini/crypto_algo/state_live/long_sleeve_top50_latest.json`
- Latest `top100`:
  - `/Users/mini/crypto_algo/state_live/long_sleeve_top100_latest.json`
- Latest `top200`:
  - `/Users/mini/crypto_algo/state_live/long_sleeve_top200_latest.json`
- Scenario history log:
  - `/Users/mini/crypto_algo/state_live/long_sleeve_scenarios_log.csv`

### Runner logs
- Stdout:
  - `/Users/mini/crypto_algo/state_live/logs/unrestricted_daily.out.log`
- Stderr:
  - `/Users/mini/crypto_algo/state_live/logs/unrestricted_daily.err.log`

## Ongoing Work (In Progress)
1. 45-day shadow validation window to confirm real-world robustness.
2. Compare short-only vs future market-neutral variant with frozen rules.
3. Evaluate pass/fail bounds against EW short benchmark and BTC short benchmark.
4. Decide capital deployment only after validation window.

## Known Notes / Caveats
- Backtests are promising but still model-based; execution slippage and live microstructure can reduce realized edge.
- Long sleeve is currently a research track (scenario logging), not yet final production long-execution logic.
- OpenClaw shell completion warning seen in terminal (`compdef`) is unrelated to strategy execution.

## Recommended Next Management Checkpoints
1. Daily: confirm both Telegram messages arrive and logs are clean.
2. Weekly: review shadow NAV, drawdown, and benchmark-relative performance.
3. At day 45: formal go/no-go decision for live capital.
