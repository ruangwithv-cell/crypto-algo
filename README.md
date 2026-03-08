# crypto_algo

A fresh, bias-resistant crypto short engine designed to reduce noisy flip-flop signals.

## Design goals
- Professional-style signal construction: multi-horizon trend + carry + liquidity + OI confirmation.
- Professional-style execution policy: hysteresis, confirmation runs, cooldowns, minimum hold time.
- Deterministic and auditable: JSON in/out, persisted state, human-readable action memo.
- Standard library only.

## Project layout
- `crypto_algo/config.py`: strategy and risk controls
- `crypto_algo/models.py`: core data structures
- `crypto_algo/signals.py`: score computation
- `crypto_algo/policy.py`: anti-whipsaw entry/exit decisions
- `crypto_algo/state_store.py`: persistence
- `crypto_algo/engine.py`: orchestrator
- `crypto_algo/main.py`: CLI
- `examples/market_snapshot.json`: example input

## Input format
Run the engine with a snapshot JSON file:

```json
{
  "timestamp": "2026-03-06T08:00:00+00:00",
  "assets": [
    {
      "symbol": "APT",
      "rank": 75,
      "price_usd": 0.99,
      "funding_rate_8h": 0.0004,
      "open_interest_usd": 23000000,
      "volume_usd": 120000000,
      "returns": {"1d": -0.02, "7d": -0.12, "30d": -0.28, "90d": -0.40}
    }
  ]
}
```

## Run
```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.main \
  --input examples/market_snapshot.json \
  --state-dir state \
  --write-memo state/latest_action_memo.txt
```

## Run From `crypto_short_v2` Feed
Use the latest v2 snapshot produced at `/Users/mini/data/runs`:

```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.main \
  --input-v2-latest-dir /Users/mini/data/runs \
  --state-dir /Users/mini/crypto_algo/state_live \
  --write-memo /Users/mini/crypto_algo/state_live/latest_action_memo.txt
```

Or run the helper script:
```bash
/Users/mini/crypto_algo/run_live_from_v2.sh
```

## Backtest Comparison (`old` vs `crypto_algo`)
This compares turnover and whipsaw frequency on historical v2 runs:

```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.backtest_compare \
  --v2-runs-dir /Users/mini/data/runs \
  --output-json /Users/mini/crypto_algo/state_live/backtest_comparison.json
```

Whipsaw metric uses a default 3-run window:
- quick entry-exit
- quick exit-reentry

## Market-Neutral Long/Short (`crypto_algo_ls`)
This is a second strategy track focused on economic edge via factor spreads:
- Momentum (7/30/90d)
- Carry (funding transfer)
- OI-trend alignment
- Liquidity quality
- Dollar-neutral with beta-proxy side scaling

Backtest:
```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.ls_backtest \
  --history-json /Users/mini/crypto_short_v2_state/portfolio_state.json \
  --cost-bps 5 \
  --n-longs 6 \
  --n-shorts 6 \
  --min-score 0.10 \
  --output-json /Users/mini/crypto_algo/state_live/ls_backtest_default.json
```

Current portfolio proposal:
```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.ls_live \
  --history-json /Users/mini/crypto_short_v2_state/portfolio_state.json \
  --n-longs 6 \
  --n-shorts 6 \
  --min-score 0.10
```

## `crypto_algo_ls_v2` (Regime + Squeeze + Vol Stops)
V2 adds:
- regime-aware gross sizing (`risk_on / neutral / risk_off`)
- squeeze filter before short entry
- slower rebalance cadence
- volatility-based stop/take per position

Backtest:
```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.ls_v2_backtest \
  --history-json /Users/mini/crypto_short_v2_state/portfolio_state.json \
  --lookback-days 90 \
  --rebalance-steps 3 \
  --n-shorts 6 \
  --n-longs 1 \
  --short-min-score 0.10 \
  --long-min-score 0.10 \
  --cost-bps 5 \
  --output-json /Users/mini/crypto_algo/state_live/ls_v2_backtest_best_found.json
```

`ls_v2_backtest` now includes benchmark outputs in the same report:
- `ew_short_universe`
- `topn_short_momentum`

## `crypto_algo_bear_v1` (Bear-Market Focus)
Builds a short-only strategy for bear periods with:
- bear-regime gate (trend + weak breadth + squeeze control)
- listing-age filter (avoids fresh launch names)
- squeeze filter (skip 7d momentum spikes)
- concentrated short book (top-N)
- volatility-based stop/take and slower rebalance
- benchmark comparison in same report

Run data extension first:
```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.binance_data_extender \
  --symbols ENA,FARTCOIN,ARB,OP,GALA,RIVER,NEAR,WIF,FIL,LDO,SPX \
  --days 365 \
  --interval 1d \
  --output /Users/mini/crypto_algo/state_live/binance_extended_365d.json
```

Backtest 90 days:
```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.bear_v1_backtest \
  --data-json /Users/mini/crypto_algo/state_live/binance_extended_365d.json \
  --lookback-days 90 \
  --rebalance-days 3 \
  --n-shorts 5 \
  --cost-bps 5 \
  --output-json /Users/mini/crypto_algo/state_live/bear_v1_backtest_90d.json
```

Backtest 365 days:
```bash
cd /Users/mini/crypto_algo
python3 -m crypto_algo.bear_v1_backtest \
  --data-json /Users/mini/crypto_algo/state_live/binance_extended_365d.json \
  --lookback-days 365 \
  --rebalance-days 3 \
  --n-shorts 5 \
  --cost-bps 5 \
  --output-json /Users/mini/crypto_algo/state_live/bear_v1_backtest_365d.json
```

## Schedule Every 8 Hours (macOS launchd)
Template provided at:
- `com.rv.cryptoalgo.plist`

Install:
```bash
mkdir -p /Users/mini/crypto_algo/state_live/logs
cp /Users/mini/crypto_algo/com.rv.cryptoalgo.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.rv.cryptoalgo.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.rv.cryptoalgo.plist
```

## Next steps
- Tune thresholds in `crypto_algo/config.py` once 2-4 weeks of live logs accumulate.
- Review memo; only execute listed `OPEN`/`CLOSE` actions.
