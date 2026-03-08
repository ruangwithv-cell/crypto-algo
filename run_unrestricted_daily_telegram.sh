#!/bin/zsh
set -euo pipefail

BASE="/Users/mini/crypto_algo"
STATE="$BASE/state_live"
DATA_JSON="$STATE/binance_unrestricted_365d.json"
MEMO="$STATE/unrestricted_latest_action_memo.txt"
LONG_SLEEVE_JSON="$STATE/long_sleeve_top100_latest.json"
LONG_MEMO="$STATE/long_sleeve_latest_action_memo.txt"
LONG_MEMO_STATE="$STATE/long_sleeve_live_state.json"
LONG_TRACKER_STATE="$STATE/long_sleeve_top100_shadow_pnl_state.json"
LONG_TRACKER_CSV="$STATE/long_sleeve_top100_shadow_pnl_daily.csv"
SHORT_NAV_USD="${SHORT_NAV_USD:-20000}"
LONG_NAV_USD="${LONG_NAV_USD:-6000}"
KELLY_FRACTION="${KELLY_FRACTION:-0.50}"
KELLY_MAX_SCALE="${KELLY_MAX_SCALE:-1.50}"

mkdir -p "$STATE" "$STATE/logs"

if [[ -f "$HOME/.env.crypto_algo_telegram" ]]; then
  set -a
  source "$HOME/.env.crypto_algo_telegram"
  set +a
fi

cd "$BASE"

# 1) Refresh full-universe data
python3 -m crypto_algo.binance_data_extender \
  --auto-universe all-usdt-perp \
  --max-symbols 0 \
  --days 365 \
  --interval 1d \
  --output "$DATA_JSON"

# 1b) Validate held symbols exist in refreshed data (fail fast)
python3 - <<'PY'
import json
from pathlib import Path

state = Path('/Users/mini/crypto_algo/state_live')
data = json.loads((state / 'binance_unrestricted_365d.json').read_text())
available = set((data.get('price_data') or {}).keys())

checks = []
for name, fn in [
    ('unrestricted_live_state', state / 'unrestricted_live_state.json'),
    ('unrestricted_shadow_pnl_state', state / 'unrestricted_shadow_pnl_state.json'),
    ('long_sleeve_live_state', state / 'long_sleeve_live_state.json'),
    ('long_sleeve_top100_shadow_pnl_state', state / 'long_sleeve_top100_shadow_pnl_state.json'),
]:
    if not fn.exists():
        continue
    obj = json.loads(fn.read_text())
    held = set((obj.get('weights') or {}).keys())
    if name.endswith('shadow_pnl_state'):
        held |= set((obj.get('last_weights') or {}).keys())
    missing = sorted(held - available)
    if missing:
        checks.append({'state': name, 'missing_symbols': missing})

if checks:
    print(json.dumps({'error': 'held_symbols_missing_from_data', 'details': checks}, indent=2))
    raise SystemExit(2)

print(json.dumps({'ok': True, 'validation': 'held_symbols_present_in_data'}, indent=2))
PY

# 2) Generate today's short action memo
python3 -m crypto_algo.bear_unrestricted_live \
  --data-json "$DATA_JSON" \
  --memo-path "$MEMO" \
  --state-json "$STATE/unrestricted_live_state.json" \
  --n-shorts-min 4 \
  --n-shorts-max 10 \
  --min-history-bars 120 \
  --min-dollar-volume 1000000 \
  --score-threshold 0.15 \
  --spread-threshold 0.25 \
  --kelly-fraction "$KELLY_FRACTION" \
  --kelly-max-scale "$KELLY_MAX_SCALE" \
  --nav-usd "$SHORT_NAV_USD" \
  --shadow-csv "$STATE/unrestricted_shadow_pnl_daily.csv" \
  --shadow-state-json "$STATE/unrestricted_shadow_pnl_state.json"

# 3) Record long-sleeve scenarios (top50/top100/top200)
python3 -m crypto_algo.long_sleeve_record_scenarios \
  --data-json "$DATA_JSON" \
  --state-dir "$STATE" \
  --n-longs 5 \
  --gross-long 0.85 \
  --min-history-bars 120 \
  --min-dollar-volume 5000000 \
  --score-threshold 0.15 \
  --kelly-fraction "$KELLY_FRACTION" \
  --kelly-max-scale "$KELLY_MAX_SCALE"

# 4) Generate today's long action memo (from top100 sleeve)
python3 -m crypto_algo.long_sleeve_live \
  --long-sleeve-json "$LONG_SLEEVE_JSON" \
  --memo-path "$LONG_MEMO" \
  --state-json "$LONG_MEMO_STATE" \
  --data-json "$DATA_JSON" \
  --nav-usd "$LONG_NAV_USD" \
  --shadow-csv "$LONG_TRACKER_CSV" \
  --shadow-state-json "$LONG_TRACKER_STATE"

# 5) Track short shadow PnL
python3 -m crypto_algo.shadow_pnl_daily \
  --data-json "$DATA_JSON" \
  --live-state-json "$STATE/unrestricted_live_state.json" \
  --tracker-state-json "$STATE/unrestricted_shadow_pnl_state.json" \
  --csv-path "$STATE/unrestricted_shadow_pnl_daily.csv"

# 6) Track long-sleeve shadow PnL (top100)
python3 -m crypto_algo.long_shadow_pnl_daily \
  --data-json "$DATA_JSON" \
  --long-sleeve-json "$LONG_SLEEVE_JSON" \
  --tracker-state-json "$LONG_TRACKER_STATE" \
  --csv-path "$LONG_TRACKER_CSV"

# 7) Send short action memo
TG_SHORT_ARGS=(
  --memo-path "$MEMO"
  --openclaw-config "$HOME/.openclaw/openclaw.json"
  --account "${OPENCLAW_TELEGRAM_ACCOUNT:-rabbit}"
  --discover-chat-id
)
if [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  TG_SHORT_ARGS+=(--chat-id "$TELEGRAM_CHAT_ID")
fi
python3 -m crypto_algo.telegram_notify "${TG_SHORT_ARGS[@]}"

# 8) Send long action memo
TG_LONG_ARGS=(
  --memo-path "$LONG_MEMO"
  --openclaw-config "$HOME/.openclaw/openclaw.json"
  --account "${OPENCLAW_TELEGRAM_ACCOUNT:-rabbit}"
  --discover-chat-id
)
if [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  TG_LONG_ARGS+=(--chat-id "$TELEGRAM_CHAT_ID")
fi
python3 -m crypto_algo.telegram_notify "${TG_LONG_ARGS[@]}"

# 9) Send combined short+long shadow PnL summary
python3 -m crypto_algo.shadow_pnl_combined_summary \
  --short-csv "$STATE/unrestricted_shadow_pnl_daily.csv" \
  --short-state-json "$STATE/unrestricted_shadow_pnl_state.json" \
  --long-csv "$LONG_TRACKER_CSV" \
  --long-state-json "$LONG_TRACKER_STATE" \
  --out-path "$STATE/unrestricted_shadow_pnl_latest.txt"

TG_PNL_ARGS=(
  --memo-path "$STATE/unrestricted_shadow_pnl_latest.txt"
  --openclaw-config "$HOME/.openclaw/openclaw.json"
  --account "${OPENCLAW_TELEGRAM_ACCOUNT:-rabbit}"
  --discover-chat-id
)
if [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  TG_PNL_ARGS+=(--chat-id "$TELEGRAM_CHAT_ID")
fi
python3 -m crypto_algo.telegram_notify "${TG_PNL_ARGS[@]}"
