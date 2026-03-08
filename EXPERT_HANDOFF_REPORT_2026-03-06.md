# Crypto Algo Research Handoff Report
Date: 2026-03-06
Workspace: `/Users/mini/crypto_algo`
Prepared for: external expert review

## 1) Objective
Build a rule-based crypto short system that reduces discretionary bias and improves signal-to-noise during bear-like conditions, then benchmark it against simple alternatives.

## 2) Starting Problem (User Context)
- Existing system (`crypto_short_v2`) produced high churn and frequent reversals between runs.
- User observed noisy behavior and wanted a cleaner algorithmic approach with less human bias.
- User requested progressively: new codebase, anti-whipsaw logic, benchmarked backtests, and improved bear-market token selection.

## 3) Codebases/Modules Created

### Core baseline project
- `crypto_algo/crypto_algo/main.py`
- `crypto_algo/crypto_algo/engine.py`
- `crypto_algo/crypto_algo/signals.py`
- `crypto_algo/crypto_algo/policy.py`
- `crypto_algo/crypto_algo/state_store.py`

### Data adapters and utilities
- `crypto_algo/crypto_algo/adapters_v2.py` (reads v2 run snapshots)
- `crypto_algo/crypto_algo/binance_data_extender.py` (direct Binance history pull)

### Backtesting/analysis modules
- `crypto_algo/crypto_algo/backtest_compare.py` (old-vs-new churn/whipsaw)
- `crypto_algo/crypto_algo/backtest_history.py` (replay from local state history)
- `crypto_algo/crypto_algo/ls_backtest.py` (market-neutral LS backtest)
- `crypto_algo/crypto_algo/ls_v2_backtest.py` (regime+squeeze+vol-stop version)
- `crypto_algo/crypto_algo/v2_style_backtest_binance.py` (v2-style criteria on Binance dataset)
- `crypto_algo/crypto_algo/selection_lab_backtest.py` (multi-selector “subagent” lab)
- `crypto_algo/crypto_algo/bear_v1_backtest.py` (bear-focused short strategy + benchmarks)
- `crypto_algo/crypto_algo/bear_v2_meta_backtest.py` (meta-ensemble selector)

### Key generated reports/files
- `state_live/backtest_comparison.json`
- `state_live/replay_backtest_*.json`
- `state_live/ls_backtest_default.json`
- `state_live/ls_v2_backtest_*.json`
- `state_live/binance_extended_365d.json`
- `state_live/bear_v1_backtest_30d.json`
- `state_live/bear_v1_backtest_90d.json`
- `state_live/bear_v1_backtest_365d.json`
- `state_live/selection_lab_30d.json`
- `state_live/selection_lab_90d.json`
- `state_live/selection_lab_365d.json`
- `state_live/bear_v2_meta_tuned_30d.json`
- `state_live/bear_v2_meta_tuned_90d.json`
- `state_live/bear_v2_meta_tuned_365d.json`

## 4) Data Sources Used

### Local state/history
- `/Users/mini/crypto_short_v2_state/portfolio_state.json`
- `/Users/mini/crypto_short_v2/merged_portfolio_state.json`
- `/Users/mini/data/runs/*.json`

### Direct exchange data (public)
- Binance spot and futures APIs via `binance_data_extender.py`
- Extended symbol set used: `ENA,FARTCOIN,ARB,OP,GALA,RIVER,NEAR,WIF,FIL,LDO,SPX`
- Output file: `state_live/binance_extended_365d.json`

## 5) Methodology Evolution

### Phase A: baseline anti-whipsaw architecture
Implemented confirmation runs, cooldowns, and hysteresis to reduce flip-flop behavior.

### Phase B: market-neutral LS experiments
Tested factor-combo long/short constructions (momentum/carry/OI/liquidity).
Observation: sensitivity to selection and regime. Not consistently superior in short windows.

### Phase C: bear-focused short systems
Moved to short-only, regime-gated systems with:
- listing-age constraints
- squeeze filtering
- concentrated baskets
- vol-based stop/take
- turnover costs
- benchmark comparison against EW short and top-N momentum short

### Phase D: “subagent” selector lab
Simulated multiple independent selection approaches under common risk/execution rules:
1. `trend_relative`
2. `carry_pressure`
3. `breakdown_quality`
4. `hybrid_final`

## 6) Core Results (Most Relevant)

### 6.1 Fixed basket checks (user-provided names)
- Useful for diagnosis but not a robust strategy test.
- Demonstrated winner/loser concentration risk: a few squeeze names can dominate basket PnL.

### 6.2 v2-style criteria on Binance extended data
`v2_style_backtest_binance.py`
- 30d: -1.78%, Sharpe -0.04
- 90d: +41.58%, Sharpe 2.40
- 365d: +108.39%, Sharpe 1.41

### 6.3 bear_v1 (bear regime + risk controls)
`bear_v1_backtest.py`
- 30d: +3.34%, Sharpe 1.00
- 90d: +65.08%, Sharpe 3.38
- 365d: +120.70%, Sharpe 1.81

### 6.4 selection lab (multi-selector)
`selection_lab_backtest.py`
- 30d best selector: `carry_pressure` (+3.91%)
- 90d best selector: `breakdown_quality` (+70.94%)
- 365d best selector: `hybrid_final` (+133.06%)

### 6.5 bear_v2_meta (ensemble with persistence + spread gating)
`bear_v2_meta_backtest.py` tuned (`persistence=1`, `spread=0.25`)
- 30d: +0.07%, Sharpe 0.33
- 90d: +58.59%, Sharpe 2.95
- 365d: +126.03%, Sharpe 1.81

### 6.6 Benchmark vs EW short universe
Using same windows/data:
- 30d: `bear_v2_meta` underperforms EW
  - +0.07% vs +3.21%
- 90d: `bear_v2_meta` outperforms EW
  - +58.59% vs +39.16%
- 365d: `bear_v2_meta` outperforms EW
  - +126.03% vs +95.27%

## 7) Important Caveats / Risk of Overfitting
1. Universe is user-selected 11-symbol set, not full broad market.
2. Parameter tuning and evaluation still share the same historical sample.
3. Daily OHLC stop/take assumptions cannot resolve intrabar sequence perfectly.
4. Funding model approximations remain simplified.
5. Short-horizon variance remains high (30d instability visible).

## 8) Checks Against Common Quant Mistakes
- Look-ahead guard: feature calculations use data up to `t`; PnL uses `t->t+1`.
- Turnover costs included (bps model).
- Regime gating + no-trade states implemented.
- Benchmarks implemented for relative performance context.

Still needed for institutional-grade validation:
- Purged/embargoed walk-forward CV
- White’s Reality Check / PBO / Deflated Sharpe
- Broader universe including delisting treatment
- Higher-frequency execution realism

## 9) Recommended Next Testing Protocol (Out-of-Sample)
1. Freeze one final strategy spec (no parameter edits during trial).
2. Run 4–8 weeks shadow forward test.
3. Track rolling alpha vs EW short benchmark.
4. Add automatic fallback mode:
   - If rolling 30d alpha < 0, reduce risk or fallback selector mode.

## 10) Practical “Current Best Candidate”
- Candidate: `bear_v2_meta` tuned (`persistence=1`, `spread=0.25`)
- Why: strongest balance across 90d and 365d while retaining rule-based controls.
- Weakness: still not strongest on 30d, so requires live guardrails.

## 11) Reproducibility Commands

### Pull data
```bash
python3 -m crypto_algo.binance_data_extender \
  --symbols ENA,FARTCOIN,ARB,OP,GALA,RIVER,NEAR,WIF,FIL,LDO,SPX \
  --days 365 --interval 1d \
  --output /Users/mini/crypto_algo/state_live/binance_extended_365d.json
```

### Run bear_v2_meta tuned
```bash
python3 -m crypto_algo.bear_v2_meta_backtest \
  --data-json /Users/mini/crypto_algo/state_live/binance_extended_365d.json \
  --lookback-days 90 \
  --rebalance-days 3 \
  --n-shorts-min 3 --n-shorts-max 6 \
  --cost-bps 5 \
  --persistence-runs 1 \
  --spread-threshold 0.25 \
  --output-json /Users/mini/crypto_algo/state_live/bear_v2_meta_tuned_90d.json
```

### Run benchmark-capable baseline
```bash
python3 -m crypto_algo.bear_v1_backtest \
  --data-json /Users/mini/crypto_algo/state_live/binance_extended_365d.json \
  --lookback-days 90 \
  --rebalance-days 3 \
  --n-shorts 5 \
  --cost-bps 5 \
  --output-json /Users/mini/crypto_algo/state_live/bear_v1_backtest_90d.json
```

---
Prepared for expert critique with full file-level traceability and reproducible command lines.
