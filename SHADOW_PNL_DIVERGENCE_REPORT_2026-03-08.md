# Shadow PnL Divergence Report (2026-03-08)

## 1) Executive Summary
A divergence was observed between live portfolio PnL and shadow tracker PnL.

Primary root cause identified:
- The market data universe was capped at `150` symbols in the daily runner.
- At least one held short symbol (`STRK`) was missing from the refreshed dataset.
- The shadow engine therefore computed PnL on fewer symbols than actually held (`symbols_used < n_positions_prev`), undercounting daily return.

This affects both short and long tracking because both trackers consume the same shared dataset file.

## 2) Observed Symptoms
- User-observed live portfolio move: materially larger than shadow-reported move.
- Shadow short CSV showed:
  - `n_positions_prev=7`
  - `symbols_used=6`
- This mismatch occurred on multiple rows.

Relevant file:
- `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_daily.csv`

## 3) Evidence
### 3.1 Tracker output mismatch
From short shadow CSV:
- `2026-03-07`: `n_positions_prev=7`, `symbols_used=6`
- `2026-03-08`: `n_positions_prev=7`, `symbols_used=6`

Interpretation:
- One held symbol was dropped from mark-to-market calculation.

### 3.2 Missing held symbol in dataset
Dataset inspection showed:
- `price_data` symbol count: `150`
- `STRK` missing from `price_data`
- `GIGGLE` present

Relevant file:
- `/Users/mini/crypto_algo/state_live/binance_unrestricted_365d.json`

### 3.3 Concrete contribution check (example)
For `GIGGLE` at prior short weight `9.95%`:
- 24h close-to-close change in dataset: about `-1.7942%`
- Short-side contribution: about `+0.1785% NAV` (~`$35.7` on `$20,000` NAV)

If another missing symbol (e.g., `STRK`) had non-trivial move, total shadow undercount can be meaningful.

## 4) Technical Root Cause
The daily data refresh command in the runner used:
- `--auto-universe all-usdt-perp`
- `--max-symbols 150`

With a capped universe, symbols currently held by strategy can fall outside the refreshed set and disappear from `price_data`.

In tracker logic (`shadow_pnl_daily.py` and `long_shadow_pnl_daily.py`):
- PnL is only computed for symbols with both `prev_day` and `cur_day` bars in dataset.
- Missing symbols are silently skipped.
- Result: `symbols_used` drops below held count, biasing PnL.

## 5) Fix Applied
Runner updated to remove universe cap:
- Changed `--max-symbols 150` -> `--max-symbols 0`

File changed:
- `/Users/mini/crypto_algo/run_unrestricted_daily_telegram.sh`

Why this fixes both sides:
- Both short and long shadow trackers read the same refreshed dataset file:
  - `/Users/mini/crypto_algo/state_live/binance_unrestricted_365d.json`

## 6) Compatibility / Data Continuity
- No schema-breaking changes were introduced.
- Historical rows are not rewritten.
- Effect is forward-looking from next daily mark onward.

## 7) Validation Checklist (for next run)
1. Confirm dataset has broad symbol coverage and includes all currently held symbols.
2. Confirm short tracker row has `symbols_used == n_positions_prev`.
3. Confirm long tracker row has `symbols_used == n_positions_prev`.
4. Compare shadow and live daily movement again after this corrected run.

## 8) Remaining Gaps (Known)
Even after missing-symbol fix, shadow and live can still differ due to:
- close-to-close daily marking vs intraday live execution,
- execution slippage/fees/funding timing,
- exact fill timing and partial fills.

These are expected model-vs-live differences and are separate from the missing-symbol undercount bug fixed here.

## 9) Conclusion
The major divergence source investigated here is real and actionable:
- capped universe caused missing held symbols,
- tracker undercounted PnL,
- fix is applied and will be testable on next scheduled daily run.
