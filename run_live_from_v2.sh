#!/bin/zsh
set -euo pipefail

BASE_DIR="/Users/mini/crypto_algo"
V2_RUNS_DIR="/Users/mini/data/runs"
STATE_DIR="/Users/mini/crypto_algo/state_live"
MEMO_PATH="$STATE_DIR/latest_action_memo.txt"

cd "$BASE_DIR"
/usr/bin/python3 -m crypto_algo.main \
  --input-v2-latest-dir "$V2_RUNS_DIR" \
  --state-dir "$STATE_DIR" \
  --write-memo "$MEMO_PATH"
