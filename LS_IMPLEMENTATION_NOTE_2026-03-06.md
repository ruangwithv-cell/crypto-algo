# LS Implementation Note (2026-03-06)

Implemented `crypto_algo_ls` (market-neutral long/short factor engine) with:
- cross-sectional factor scoring (momentum, carry, OI alignment, liquidity)
- universe/risk filters (rank range, OI floor, stablecoin exclusions)
- dollar-neutral construction with beta-proxy side scaling
- replay backtest with turnover and transaction-cost deductions
- live proposal command for deterministic basket output

## Key Commands

Backtest:
```bash
python3 -m crypto_algo.ls_backtest \
  --history-json /Users/mini/crypto_short_v2_state/portfolio_state.json \
  --cost-bps 5 \
  --n-longs 6 \
  --n-shorts 6 \
  --min-score 0.10 \
  --output-json /Users/mini/crypto_algo/state_live/ls_backtest_default.json
```

Live proposal:
```bash
python3 -m crypto_algo.ls_live \
  --history-json /Users/mini/crypto_short_v2_state/portfolio_state.json \
  --n-longs 6 --n-shorts 6 --min-score 0.10
```

## Current Backtest Snapshot
Source: `/Users/mini/crypto_algo/state_live/ls_backtest_default.json`
- period: 2026-02-01 to 2026-03-06 (~32.9 days)
- total return: -1.43%
- sharpe: -2.93
- max drawdown: -1.59%

Conclusion: architecture implemented and operational, but edge not yet positive on current local sample. Continue in research/shadow mode.
