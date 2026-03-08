# Unrestricted Short Algo Handoff (45-Day Live Plan)
Date: 2026-03-06  
Repo: `/Users/mini/crypto_algo`  
Strategy ID: `bear_unrestricted_v1`

## 1) What This System Is
This is a rule-based, fully systematic short-selection engine for crypto perp markets.

Core intent:
- Remove discretionary/human bias.
- Trade only when a broad bear regime is detected.
- Select shorts from a wide universe (not a handpicked list).
- Size by risk (inverse volatility), not conviction.
- Send daily action + daily shadow PnL update to Telegram.

## 2) Current Production-Like Pipeline
Main runner:
- `/Users/mini/crypto_algo/run_unrestricted_daily_telegram.sh`

It runs these steps in order:
1. Refresh data from Binance futures universe (`max-symbols=150`, 365d, 1d bars)
2. Generate today’s action memo
3. Mark shadow daily PnL
4. Send action memo to Telegram
5. Send compact PnL summary as second Telegram message

Supporting modules:
- Data pull: `/Users/mini/crypto_algo/crypto_algo/binance_data_extender.py`
- Signal + backtest: `/Users/mini/crypto_algo/crypto_algo/bear_unrestricted_backtest.py`
- Live memo generation: `/Users/mini/crypto_algo/crypto_algo/bear_unrestricted_live.py`
- Shadow PnL ledger: `/Users/mini/crypto_algo/crypto_algo/shadow_pnl_daily.py`
- PnL summary text: `/Users/mini/crypto_algo/crypto_algo/shadow_pnl_summary.py`
- Telegram sender (OpenClaw token): `/Users/mini/crypto_algo/crypto_algo/telegram_notify.py`

## 3) How Selection Works (Decision by Decision)
All rules are deterministic.

### 3.1 Universe Eligibility Filter
A coin is considered only if:
- Symbol is clean ticker format (`A-Z0-9`).
- Not in excluded stable/majors list (`BTC`, `ETH`, `USDT`, etc.).
- Has enough history (`min_history_bars`, currently 120).
- Has sufficient liquidity (`min_dollar_volume`, currently $1,000,000 median over recent 20 bars).
- Has a bar on the current day.

Reasoning:
- Avoid stale/newly listed names with unstable behavior.
- Avoid illiquid names that create unrealistic backtest fills/slippage.
- Keep tradability and execution quality as first constraint.

### 3.2 Regime Gate (When to Trade)
Regime is `flat`, `bear`, or `deep_bear`.

Bear is ON when:
- Cross-sectional median-price MA short < MA long.
- Breadth weakness ratio is high (enough assets below their breadth MA).
- Squeeze ratio is limited (not too many assets in sharp short-term rebounds).

If regime is `flat`:
- Target portfolio is forced flat (no short exposure).

Reasoning:
- This avoids shorting in risk-on/mean-reverting environments.
- It keeps the strategy conditional on market structure, not always-on.

### 3.3 Cross-Sectional Scoring (Which Coins to Short)
For each eligible coin, features are computed:
- Trend weakness: weighted negative returns across 14/30/60/90/120d
- Relative weakness: underperformance vs market 30d average
- Carry: funding rate (short-side carry context)
- Breakdown quality: distance below 90d high
- Liquidity: log dollar volume
- Squeeze penalty: recent upside impulse (3d/7d)

Features are z-scored cross-sectionally, then combined:
- In `deep_bear`: more weight on trend + breakdown, less on carry/liquidity
- In `bear`: more balanced weights

Reasoning:
- Trend + breakdown identify persistent losers.
- Relative weakness avoids shorting market leaders by mistake.
- Squeeze penalty reduces blow-up risk from violent rebounds.
- Liquidity term keeps execution realistic.

### 3.4 How Many Shorts to Hold
Dynamic count (`n_shorts_min` to `n_shorts_max`) depends on:
- Score spread between top candidates.
- Absolute top-score strength.
- Score threshold floor.

Reasoning:
- Strong dispersion -> hold more names.
- Weak dispersion -> concentrate less, avoid forcing low-quality names.

### 3.5 Position Sizing
Sizing rules:
- Inverse-volatility weighting (lower vol gets larger weight).
- Per-name cap: 20% absolute.
- Gross target:
  - `85%` in `deep_bear`
  - `70%` in `bear`
- Re-normalize to exact gross target.

Reasoning:
- Prevent single-name dominance.
- Keep risk budget stable across regimes.
- Make portfolio behavior more consistent than equal-weight by nominal capital.

### 3.6 Exit / Risk on Positions
Per-position stop/take are volatility-derived:
- Stop = clamp(`2 * vol`, 8% to 18%)
- Take = clamp(`3 * vol`, 15% to 35%)

Reasoning:
- One fixed stop is too blunt across coins with different vol.
- Vol-adaptive bands reduce forced exits on normal noise and still cap tail risk.

## 4) What “Shadow PnL” Tracks
Shadow PnL marks yesterday’s held weights to today’s close:
- Price PnL component
- Funding PnL component
- Daily return
- Cumulative shadow NAV

Files:
- State: `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_state.json`
- Daily history: `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_daily.csv`
- Telegram summary text: `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_latest.txt`

## 5) Current Backtest Snapshot (Full-Universe, 1-Day Rebalance)
Data file:
- `/Users/mini/crypto_algo/state_live/binance_unrestricted_365d.json`

Saved reports:
- `/Users/mini/crypto_algo/state_live/bear_unrestricted_fulluni_30d_rebal1.json`
- `/Users/mini/crypto_algo/state_live/bear_unrestricted_fulluni_90d_rebal1.json`
- `/Users/mini/crypto_algo/state_live/bear_unrestricted_fulluni_365d_rebal1.json`

Performance vs EW short benchmark:
- 30d Sharpe: `2.2675` vs EW `-1.2689`
- 90d Sharpe: `3.2057` vs EW `0.2573`
- 365d Sharpe: `1.1981` vs EW `0.3258`

Important caveat:
- These are in-sample historical tests with simplified execution assumptions.
- Treat as promising evidence, not proof of forward edge.

## 6) Why This Could Work (Trader Framing)
The model is not trying to predict every coin.  
It is trying to consistently harvest the left tail of weak names during broad risk-off phases by:
- Trading only when market structure is bearish.
- Ranking cross-sectional losers with anti-squeeze controls.
- Diversifying across several weak names.
- Sizing by volatility and keeping gross bounded.

In plain terms:
- “Short the weakest names when the tide is going out, and don’t force trades when it isn’t.”

## 7) Key Risks / Failure Modes
1. Regime flip whipsaws: bear gate can lag sharp reversals.
2. Squeeze events: meme/low-float spikes can exceed stop assumptions intraday.
3. Cost/slippage underestimation in high-vol periods.
4. Funding regime shifts reducing expected carry.
5. Selection drift from exchange listing changes.
6. Overfitting risk from repeated parameter retuning on same sample.

## 8) 45-Day Live (Shadow) Validation Plan
Objective: decide GO/NO-GO for capital deployment.

### 8.1 Freeze Rules
For 45 days, do not change:
- Feature weights
- Thresholds
- Universe cap
- Rebalance frequency
- Stop/take formula

Any change resets the clock.

### 8.2 Daily Ops
Every day at scheduled time:
- Receive action memo (message 1)
- Receive PnL summary (message 2)
- Record broker-realistic assumptions if execution differs

### 8.3 Weekly Review (No Parameter Changes)
Track:
- Shadow NAV, weekly return, rolling 7/14/30-day Sharpe proxy
- Drawdown profile
- Turnover and exposure drift
- Hit-rate and contribution concentration by symbol

### 8.4 45-Day Decision Gate
Require at minimum:
- Positive cumulative return
- Sharpe above EW-short benchmark
- Drawdown within acceptable risk budget
- No operational instability (missing data, missed sends, bad symbols)

If pass:
- Move to small capital with hard risk budget.
If fail:
- Diagnose by bucket (regime, selection, sizing, execution) before retuning.

### 8.5 Explicit Failure Bounds (Recommended)
Use these as hard fail thresholds for the 45-day shadow trial.

Absolute failure (any one triggers FAIL):
- Cumulative return <= `-8%`
- Max drawdown <= `-12%`
- Daily loss worse than `-4%` on any single day
- 20-day rolling Sharpe <= `-0.5` for 10 consecutive trading days

Relative failure vs benchmark basket (any one triggers FAIL):
- Return underperformance vs EW short universe <= `-6%` over full 45d
- Sharpe underperformance vs EW short universe <= `-0.40` over full 45d
- Return underperformance vs BTC short (same gross, same cost assumptions) <= `-4%`
- Hit ratio (days strategy > EW short) < `45%`

“Worst expected” guardrail:
- Define expected relative alpha band from pre-live tests as:
  - EW-relative return alpha expected: `+2% to +12%` over 45d
  - EW-relative Sharpe alpha expected: `+0.20 to +1.00`
- If realized relative performance is below lower band for 2 consecutive weekly checkpoints, classify as “likely broken edge” and stop live test early.

## 9) Resume Checklist (After Break)
If work pauses, restart with this sequence:
1. Confirm latest data file exists and updates:  
   `/Users/mini/crypto_algo/state_live/binance_unrestricted_365d.json`
2. Run one manual cycle:  
   `cd /Users/mini/crypto_algo && ./run_unrestricted_daily_telegram.sh`
3. Check latest memo:  
   `/Users/mini/crypto_algo/state_live/unrestricted_latest_action_memo.txt`
4. Check PnL state + CSV:
   - `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_state.json`
   - `/Users/mini/crypto_algo/state_live/unrestricted_shadow_pnl_daily.csv`
5. Re-run backtests for sanity:
   - 30/90/365 windows with same fixed params
6. Only then consider any model changes.

## 10) Controlled Evolution Roadmap (Post-45 Days)
Priority order:
1. Execution realism:
   - Add slippage model tied to volatility and dollar volume.
2. Risk overlay:
   - Portfolio kill-switch (rolling drawdown / vol-target cap).
3. Robustness:
   - Walk-forward parameter validation, not global fit.
4. Feature upgrades:
   - Add OI and basis term-structure if stable data source available.
5. Benchmark expansion:
   - Compare against BTC short, ETH short, and EW short with same gross and cost model.

Rule:
- One change at a time, then re-run out-of-sample validation.

## 12) Market-Neutral Variant (Should You Add Longs?)
Short answer: yes, if your objective is cleaner alpha with lower beta to crypto market direction.

When market-neutral helps:
- You want strategy performance less dependent on broad market trend.
- You want smoother equity curve and lower directional drawdown.
- You can accept lower raw return in exchange for better risk-adjusted return.

When to stay short-only:
- You have a strong bear-market prior and want convex downside capture.
- You prefer simpler execution and lower model complexity.

Practical neutral setup (recommended first version):
- Keep current short selector unchanged.
- Add a long selector from the same eligible universe:
  - Positive 30/60/90d trend
  - Positive relative strength vs market
  - Positive liquidity score
  - Negative squeeze-penalty for shorts is mirrored as “avoid overextended longs”
- Portfolio constraints:
  - Gross short = `70%` to `85%` based on regime (existing)
  - Gross long = same as gross short (beta-neutral target)
  - Net exposure target near `0%` (range `-10%` to `+10%`)
  - Vol-scaling and single-name caps on both sides

Failure bounds for neutral variant:
- 45d return <= `-5%`
- 45d Sharpe <= `0.0`
- Underperform EW market-neutral benchmark by return <= `-4%` or Sharpe <= `-0.30`

Recommendation:
- Run short-only and neutral in parallel shadow books for the same 45 days.
- Pick deployment version by pre-committed objective:
  - Absolute bear capture -> short-only
  - Higher signal/noise and lower beta -> market-neutral

## 11) Operational Notes
- Telegram is sent via OpenClaw account token from:
  - `~/.openclaw/openclaw.json` (account default `rabbit`)
  - chat id override via `~/.env.crypto_algo_telegram`
- Daily scheduler plist prepared at:
  - `/Users/mini/crypto_algo/com.rv.cryptoalgo.unrestricted.daily.plist`
- In this environment, `launchctl` may show load/bootstrap I/O errors; manual local bootstrap is required on machine shell.

---
This document is the source-of-truth handoff for continuing development after a 45-day live shadow period.
