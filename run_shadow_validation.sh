#!/bin/zsh
set -euo pipefail

BASE="/Users/mini/crypto_algo"
STATE="$BASE/state_live"
DATE_TAG=$(date -u +"%Y%m%dT%H%M%SZ")

SYMS="ENA,FARTCOIN,ARB,OP,GALA,RIVER,NEAR,WIF,FIL,LDO,SPX"
DATA_JSON="$STATE/binance_extended_365d.json"

mkdir -p "$STATE" "$STATE/validation_runs"

cd "$BASE"

# 1) Refresh exchange data
python3 -m crypto_algo.binance_data_extender \
  --symbols "$SYMS" \
  --days 365 \
  --interval 1d \
  --output "$DATA_JSON"

# 2) Run shadow action memo (paper portfolio updates only)
python3 -m crypto_algo.shadow_run_once \
  --data-json "$DATA_JSON" \
  --state-json "$STATE/shadow_state.json" \
  --memo-path "$STATE/shadow_latest_action_memo.txt" \
  --n-shorts-min 3 \
  --n-shorts-max 6 \
  --persistence-runs 1 \
  --spread-threshold 0.25

# 3) Validation windows for bear_v2_meta
python3 -m crypto_algo.bear_v2_meta_backtest --data-json "$DATA_JSON" --lookback-days 30  --rebalance-days 3 --n-shorts-min 3 --n-shorts-max 6 --cost-bps 5 --persistence-runs 1 --spread-threshold 0.25 --output-json "$STATE/validation_runs/bear_v2_meta_30d_${DATE_TAG}.json"
python3 -m crypto_algo.bear_v2_meta_backtest --data-json "$DATA_JSON" --lookback-days 90  --rebalance-days 3 --n-shorts-min 3 --n-shorts-max 6 --cost-bps 5 --persistence-runs 1 --spread-threshold 0.25 --output-json "$STATE/validation_runs/bear_v2_meta_90d_${DATE_TAG}.json"
python3 -m crypto_algo.bear_v2_meta_backtest --data-json "$DATA_JSON" --lookback-days 365 --rebalance-days 3 --n-shorts-min 3 --n-shorts-max 6 --cost-bps 5 --persistence-runs 1 --spread-threshold 0.25 --output-json "$STATE/validation_runs/bear_v2_meta_365d_${DATE_TAG}.json"

# 4) EW benchmark snapshots from bear_v1 harness
python3 -m crypto_algo.bear_v1_backtest --data-json "$DATA_JSON" --lookback-days 30  --rebalance-days 3 --n-shorts 5 --cost-bps 5 --output-json "$STATE/validation_runs/bear_v1_30d_${DATE_TAG}.json"
python3 -m crypto_algo.bear_v1_backtest --data-json "$DATA_JSON" --lookback-days 90  --rebalance-days 3 --n-shorts 5 --cost-bps 5 --output-json "$STATE/validation_runs/bear_v1_90d_${DATE_TAG}.json"
python3 -m crypto_algo.bear_v1_backtest --data-json "$DATA_JSON" --lookback-days 365 --rebalance-days 3 --n-shorts 5 --cost-bps 5 --output-json "$STATE/validation_runs/bear_v1_365d_${DATE_TAG}.json"

# 5) Append summary CSV row
python3 - <<PY
import json
from pathlib import Path
from datetime import datetime, timezone

state = Path("$STATE")
tag = "$DATE_TAG"

m30 = json.loads((state / f"validation_runs/bear_v2_meta_30d_{tag}.json").read_text())
m90 = json.loads((state / f"validation_runs/bear_v2_meta_90d_{tag}.json").read_text())
m365 = json.loads((state / f"validation_runs/bear_v2_meta_365d_{tag}.json").read_text())
b30 = json.loads((state / f"validation_runs/bear_v1_30d_{tag}.json").read_text())
b90 = json.loads((state / f"validation_runs/bear_v1_90d_{tag}.json").read_text())
b365 = json.loads((state / f"validation_runs/bear_v1_365d_{tag}.json").read_text())

ew30=b30['benchmarks']['ew_short_universe']
ew90=b90['benchmarks']['ew_short_universe']
ew365=b365['benchmarks']['ew_short_universe']

line = ",".join([
    tag,
    f"{m30['performance']['total_return']:.6f}", f"{ew30['total_return']:.6f}", f"{(m30['performance']['total_return']-ew30['total_return']):.6f}",
    f"{m90['performance']['total_return']:.6f}", f"{ew90['total_return']:.6f}", f"{(m90['performance']['total_return']-ew90['total_return']):.6f}",
    f"{m365['performance']['total_return']:.6f}", f"{ew365['total_return']:.6f}", f"{(m365['performance']['total_return']-ew365['total_return']):.6f}",
])

csv = state / "shadow_validation_log.csv"
if not csv.exists():
    csv.write_text("run_tag,meta_30d,ew_30d,alpha_30d,meta_90d,ew_90d,alpha_90d,meta_365d,ew_365d,alpha_365d\n")
with csv.open("a") as f:
    f.write(line + "\n")
print("appended", csv)
PY

echo "shadow validation complete: $DATE_TAG"
