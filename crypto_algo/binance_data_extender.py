from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _exchange_symbols() -> tuple[set[str], set[str]]:
    spot = _get_json("https://api.binance.com/api/v3/exchangeInfo")
    fut = _get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
    spot_set = {s["symbol"] for s in spot.get("symbols", [])}
    fut_set = {s["symbol"] for s in fut.get("symbols", [])}
    return spot_set, fut_set


def _discover_all_usdt_perp_assets(max_symbols: int | None = None) -> list[str]:
    ex = _get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
    tickers = _get_json("https://fapi.binance.com/fapi/v1/ticker/24hr")
    qv = {t.get("symbol"): float(t.get("quoteVolume", 0.0)) for t in tickers}

    rows = []
    for s in ex.get("symbols", []):
        sym = s.get("symbol", "")
        if s.get("status") != "TRADING":
            continue
        if s.get("contractType") != "PERPETUAL":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        if not sym.endswith("USDT"):
            continue
        base = s.get("baseAsset", "")
        if not base:
            continue
        rows.append((base, qv.get(sym, 0.0)))

    rows.sort(key=lambda x: x[1], reverse=True)
    assets = [base for base, _ in rows]
    if max_symbols and max_symbols > 0:
        assets = assets[:max_symbols]
    return assets


def _resolve_symbol(asset: str, spot_set: set[str], fut_set: set[str]) -> tuple[str | None, str | None]:
    candidates = [f"{asset}USDT"]
    if asset == "FARTCOIN":
        candidates = ["FARTCOINUSDT", "1000FARTCOINUSDT"]
    if asset == "SPX":
        candidates = ["SPXUSDT", "1000SPXUSDT"]

    for s in candidates:
        if s in fut_set:
            return s, "futures"
        if s in spot_set:
            return s, "spot"
    return None, None


def _fetch_klines(symbol: str, market: str, interval: str, start_ms: int, end_ms: int) -> list[list]:
    base = "https://fapi.binance.com/fapi/v1/klines" if market == "futures" else "https://api.binance.com/api/v3/klines"
    out: list[list] = []
    cursor = start_ms
    while cursor < end_ms:
        q = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        rows = _get_json(f"{base}?{q}")
        if not rows:
            break
        out.extend(rows)
        last_open = int(rows[-1][0])
        next_cursor = last_open + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.03)
    return out


def _fetch_funding(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    out: list[dict] = []
    cursor = start_ms
    while cursor < end_ms:
        q = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        rows = _get_json(f"https://fapi.binance.com/fapi/v1/fundingRate?{q}")
        if not rows:
            break
        out.extend(rows)
        last_t = int(rows[-1]["fundingTime"])
        next_cursor = last_t + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.03)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pull extended historical data from Binance")
    p.add_argument("--symbols", type=str, default="", help="Comma-separated base symbols, e.g. ENA,ARB,OP")
    p.add_argument(
        "--auto-universe",
        type=str,
        default="none",
        choices=("none", "all-usdt-perp"),
        help="Auto-discover assets from Binance futures universe",
    )
    p.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="Optional cap when using --auto-universe (0 = no cap)",
    )
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--interval", type=str, default="1d")
    p.add_argument("--output", type=Path, required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    assets = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.auto_universe == "all-usdt-perp":
        assets = _discover_all_usdt_perp_assets(args.max_symbols if args.max_symbols > 0 else None)
        print(json.dumps({"auto_universe": args.auto_universe, "assets_discovered": len(assets)}, indent=2))
    if not assets:
        raise SystemExit("No symbols provided")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(args.days, 1))
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    spot_set, fut_set = _exchange_symbols()

    payload = {
        "generated_at_utc": end.isoformat(),
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "days": args.days,
        "interval": args.interval,
        "symbols": [],
        "price_data": {},
        "funding_data": {},
    }

    for asset in assets:
        resolved, market = _resolve_symbol(asset, spot_set, fut_set)
        if not resolved or not market:
            payload["symbols"].append({"asset": asset, "status": "NOT_FOUND"})
            continue

        klines = _fetch_klines(resolved, market, args.interval, start_ms, end_ms)
        if not klines:
            payload["symbols"].append({"asset": asset, "symbol": resolved, "market": market, "status": "NO_KLINES"})
            continue

        price_rows = [
            {
                "open_time": int(r[0]),
                "open_time_utc": datetime.fromtimestamp(int(r[0]) / 1000, tz=timezone.utc).isoformat(),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
            for r in klines
        ]
        payload["price_data"][asset] = price_rows

        item = {
            "asset": asset,
            "symbol": resolved,
            "market": market,
            "bars": len(price_rows),
            "first_bar_utc": price_rows[0]["open_time_utc"],
            "last_bar_utc": price_rows[-1]["open_time_utc"],
            "status": "OK",
        }

        if market == "futures":
            fund = _fetch_funding(resolved, start_ms, end_ms)
            payload["funding_data"][asset] = [
                {
                    "funding_time": int(x["fundingTime"]),
                    "funding_time_utc": datetime.fromtimestamp(int(x["fundingTime"]) / 1000, tz=timezone.utc).isoformat(),
                    "funding_rate": float(x["fundingRate"]),
                }
                for x in fund
            ]
            item["funding_points"] = len(payload["funding_data"][asset])

        payload["symbols"].append(item)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "output": str(args.output),
        "symbols": payload["symbols"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
