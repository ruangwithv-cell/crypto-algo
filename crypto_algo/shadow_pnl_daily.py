from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .bear_unrestricted_backtest import _build_daily


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily shadow PnL tracker for unrestricted strategy")
    p.add_argument("--data-json", type=Path, required=True)
    p.add_argument("--live-state-json", type=Path, required=True, help="State from bear_unrestricted_live")
    p.add_argument("--tracker-state-json", type=Path, required=True, help="Persistent tracker state")
    p.add_argument("--csv-path", type=Path, required=True, help="PnL history csv")
    return p.parse_args()


def _iso_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _funding_value(funding_map: dict[str, dict[int, float]], symbol: str, cur_day_key: int, prev_day_key: int) -> tuple[float | None, str | None]:
    fmap = funding_map.get(symbol, {}) or {}
    if cur_day_key in fmap:
        return float(fmap[cur_day_key]), None
    if prev_day_key in fmap:
        return float(fmap[prev_day_key]), "fallback_prev_day"
    return None, "missing"


def main() -> int:
    args = parse_args()

    payload = json.loads(args.data_json.read_text())
    live = json.loads(args.live_state_json.read_text())
    days, px, funding = _build_daily(payload)
    if len(days) < 2:
        raise SystemExit("Not enough data")

    cur_day = days[-1]
    prev_day = days[-2]
    cur_day_key = (cur_day // 86_400_000) * 86_400_000
    prev_day_key = (prev_day // 86_400_000) * 86_400_000

    cur_weights: dict[str, float] = live.get("weights", {}) or {}

    if args.tracker_state_json.exists():
        tracker = json.loads(args.tracker_state_json.read_text())
    else:
        tracker = {}

    last_day = int(tracker.get("last_day_ms", 0) or 0)
    last_weights = tracker.get("last_weights", {}) or {}
    nav = float(tracker.get("nav", 1.0))

    if last_day <= 0 or not last_weights:
        new_state = {
            "nav": nav,
            "last_day_ms": cur_day,
            "last_weights": cur_weights,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }
        args.tracker_state_json.parent.mkdir(parents=True, exist_ok=True)
        args.tracker_state_json.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"initialized": True, "day_utc": _iso_day(cur_day), "nav": nav}, indent=2))
        return 0

    if cur_day <= last_day:
        print(json.dumps({"skipped": "already_marked", "day_utc": _iso_day(cur_day), "nav": nav}, indent=2))
        return 0

    price_pnl = 0.0
    funding_pnl = 0.0
    used = 0
    missing_symbols: list[str] = []
    missing_funding: list[str] = []
    funding_fallback_prev_day: list[str] = []

    for s, w in last_weights.items():
        if abs(w) < 1e-12:
            continue
        pmap = px.get(s, {})
        b0 = pmap.get(prev_day)
        b1 = pmap.get(cur_day)
        if not b0 or not b1:
            missing_symbols.append(s)
            continue
        c0 = float(b0["close"])
        c1 = float(b1["close"])
        if c0 <= 0:
            missing_symbols.append(s)
            continue
        price_pnl += abs(w) * ((c0 - c1) / c0)

        f, f_status = _funding_value(funding, s, cur_day_key, prev_day_key)
        if f is not None:
            funding_pnl += abs(w) * f * 3.0
            if f_status == "fallback_prev_day":
                funding_fallback_prev_day.append(s)
        else:
            missing_funding.append(s)
        used += 1

    day_ret = price_pnl + funding_pnl
    nav *= 1.0 + day_ret

    args.csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not args.csv_path.exists()
    with args.csv_path.open("a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(
                [
                    "day_utc",
                    "daily_return",
                    "shadow_nav",
                    "price_component",
                    "funding_component",
                    "n_positions_prev",
                    "gross_prev",
                    "n_positions_curr",
                    "gross_curr",
                    "symbols_used",
                ]
            )
        w.writerow(
            [
                _iso_day(cur_day),
                f"{day_ret:.8f}",
                f"{nav:.8f}",
                f"{price_pnl:.8f}",
                f"{funding_pnl:.8f}",
                len(last_weights),
                f"{sum(abs(v) for v in last_weights.values()):.6f}",
                len(cur_weights),
                f"{sum(abs(v) for v in cur_weights.values()):.6f}",
                used,
            ]
        )

    new_state = {
        "nav": nav,
        "last_day_ms": cur_day,
        "last_weights": cur_weights,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    args.tracker_state_json.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n")

    out = {
        "day_utc": _iso_day(cur_day),
        "daily_return": round(day_ret, 8),
        "shadow_nav": round(nav, 8),
        "price_component": round(price_pnl, 8),
        "funding_component": round(funding_pnl, 8),
        "symbols_used": used,
    }
    if missing_symbols:
        out["warning"] = "missing_symbols"
        out["missing_symbols"] = sorted(missing_symbols)
        out["expected_positions"] = len(last_weights)
    if missing_funding:
        out["warning_missing_funding"] = sorted(missing_funding)
    if funding_fallback_prev_day:
        out["warning_funding_fallback_prev_day"] = sorted(funding_fallback_prev_day)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
