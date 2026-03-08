from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev


@dataclass
class Position:
    symbol: str
    weight: float
    entry: float
    stop_pct: float
    take_pct: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backtest crypto_short_v2-style criteria on Binance extended dataset")
    p.add_argument("--data-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/binance_extended_365d.json"))
    p.add_argument("--lookback-days", type=int, default=30)
    p.add_argument("--rebalance-days", type=int, default=3)
    p.add_argument("--n-shorts", type=int, default=5)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--output-json", type=Path, default=None)
    return p.parse_args()


def _max_dd(path: list[float]) -> float:
    peak = path[0]
    mdd = 0.0
    for x in path:
        if x > peak:
            peak = x
        dd = (x - peak) / peak
        if dd < mdd:
            mdd = dd
    return mdd


def _sharpe(step_rets: list[float], total_days: float) -> float:
    if len(step_rets) < 2:
        return 0.0
    avg = mean(step_rets)
    vol = pstdev(step_rets)
    if vol <= 1e-12:
        return 0.0
    steps_per_day = len(step_rets) / max(total_days, 1e-9)
    return (avg / vol) * math.sqrt(365.0 * steps_per_day)


def _turnover(prev: dict[str, float], new: dict[str, float]) -> float:
    keys = set(prev) | set(new)
    return 0.5 * sum(abs(new.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)


def _build_daily(payload: dict):
    price_data = payload.get("price_data", {})
    by_symbol = {}
    all_days = set()
    for s, bars in price_data.items():
        arr = sorted(bars, key=lambda x: x["open_time"])
        by_symbol[s] = arr
        for r in arr:
            all_days.add(int(r["open_time"]))
    days = sorted(all_days)
    px = {s: {int(r["open_time"]): r for r in bars} for s, bars in by_symbol.items()}

    funding = {}
    for s, rows in payload.get("funding_data", {}).items():
        day_map = {}
        tmp = {}
        for x in rows:
            t = int(x["funding_time"])
            d = (t // 86_400_000) * 86_400_000
            tmp.setdefault(d, []).append(float(x["funding_rate"]))
        for d, vals in tmp.items():
            day_map[d] = sum(vals) / len(vals)
        funding[s] = day_map
    return days, px, funding


def _closes(px_sym: dict[int, dict], days: list[int], idx: int, n: int) -> list[float]:
    out = []
    for j in range(max(0, idx - n + 1), idx + 1):
        b = px_sym.get(days[j])
        if b:
            out.append(float(b["close"]))
    return out


def _ret(closes: list[float], lookback: int):
    if len(closes) <= lookback:
        return None
    a = closes[-lookback - 1]
    b = closes[-1]
    if a <= 0:
        return None
    return (b - a) / a


def _vol(closes: list[float]) -> float:
    if len(closes) < 10:
        return 0.06
    arr = closes[-21:]
    rets = []
    for a, b in zip(arr[:-1], arr[1:]):
        if a > 0:
            rets.append((b - a) / a)
    if len(rets) < 6:
        return 0.06
    mu = sum(rets) / len(rets)
    var = sum((x - mu) ** 2 for x in rets) / max(len(rets), 1)
    return max(min(math.sqrt(var), 0.25), 0.02)


def _v2_style_select(idx: int, days: list[int], px: dict[str, dict[int, dict]], funding: dict[str, dict[int, float]], n_shorts: int) -> dict[str, Position]:
    excluded = {"BTC", "ETH", "USDT", "USDC", "DAI", "FDUSD", "BUSD", "TUSD", "PYUSD", "USDE", "STABLE"}
    day = days[idx]
    rows = []

    for s, pmap in px.items():
        if s in excluded:
            continue
        if len([d for d in days[:idx + 1] if d in pmap]) < 60:
            continue

        closes = _closes(pmap, days, idx, 120)
        r7 = _ret(closes, 7)
        r30 = _ret(closes, 30)
        if r7 is None or r30 is None:
            continue

        f = funding.get(s, {}).get((day // 86_400_000) * 86_400_000, 0.0)

        # v2-like entry gates (simplified for Binance-only dataset)
        if r30 >= 0:
            continue
        if f <= -0.002:
            continue
        if r7 >= 0.25:
            continue
        if f > 0.001:
            continue

        # score: trend + funding (higher funding for shorts) + 7d weakness
        trend_score = min(max((-r30) / 0.30, 0.0), 1.0)
        funding_score = min(max((f + 0.001) / 0.002, 0.0), 1.0)
        short_term_score = min(max((-r7) / 0.20, 0.0), 1.0)
        score = 0.55 * trend_score + 0.30 * funding_score + 0.15 * short_term_score

        rows.append((s, score, closes))

    rows.sort(key=lambda x: x[1], reverse=True)
    top = rows[:n_shorts]
    if not top:
        return {}

    # equal-weight concentrated shorts with vol-based exits
    gross = 0.80
    w = -gross / len(top)
    out = {}
    for s, sc, closes in top:
        vv = _vol(closes)
        stop = max(min(2.0 * vv, 0.18), 0.08)
        take = max(min(3.0 * vv, 0.35), 0.15)
        entry = float(px[s][days[idx]]["close"])
        out[s] = Position(symbol=s, weight=w, entry=entry, stop_pct=stop, take_pct=take)
    return out


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    days, px, funding = _build_daily(payload)

    if len(days) < 120:
        raise SystemExit("Not enough daily history")

    end_day = days[-1]
    cutoff = end_day - max(args.lookback_days, 1) * 86_400_000
    start_idx = 0
    while start_idx < len(days) - 1 and days[start_idx] < cutoff:
        start_idx += 1

    nav = 1.0
    nav_path = [1.0]
    rets = []
    active: dict[str, Position] = {}
    prev_w: dict[str, float] = {}
    turnover = []
    changes = 0
    pnl_price = 0.0
    pnl_funding = 0.0
    pnl_cost = 0.0

    for i in range(start_idx, len(days) - 1):
        day = days[i]
        nxt = days[i + 1]
        do_rebal = (i % max(args.rebalance_days, 1) == 0)
        cost = 0.0

        if do_rebal:
            target = _v2_style_select(i, days, px, funding, args.n_shorts)
            target_w = {s: p.weight for s, p in target.items()}
            to = _turnover(prev_w, target_w)
            turnover.append(to)
            cost = to * (args.cost_bps / 10_000.0)
            changes += sum(1 for k in set(prev_w) | set(target_w) if abs(prev_w.get(k, 0.0) - target_w.get(k, 0.0)) > 1e-12)
            active = target
            prev_w = target_w

        step_price = 0.0
        step_funding = 0.0
        to_close = []
        for s, pos in active.items():
            bt = px.get(s, {}).get(day)
            bn = px.get(s, {}).get(nxt)
            if not bt or not bn:
                continue

            c0 = float(bt["close"])
            c1 = float(bn["close"])
            hi = float(bn["high"])
            lo = float(bn["low"])
            if c0 <= 0:
                continue

            stop_price = pos.entry * (1.0 + pos.stop_pct)
            take_price = pos.entry * (1.0 - pos.take_pct)
            hit_stop = hi >= stop_price
            hit_take = lo <= take_price
            if hit_stop and hit_take:
                r = -pos.stop_pct  # conservative
                to_close.append(s)
            elif hit_stop:
                r = -pos.stop_pct
                to_close.append(s)
            elif hit_take:
                r = pos.take_pct
                to_close.append(s)
            else:
                r = (c0 - c1) / c0

            step_price += abs(pos.weight) * r

            f = funding.get(s, {}).get((day // 86_400_000) * 86_400_000)
            if f is not None:
                step_funding += abs(pos.weight) * float(f) * 3.0

        for s in to_close:
            active.pop(s, None)
            prev_w.pop(s, None)

        ret = step_price + step_funding - cost
        nav *= 1.0 + ret
        rets.append(ret)
        nav_path.append(nav)
        pnl_price += step_price
        pnl_funding += step_funding
        pnl_cost -= cost

    total_days = (days[-1] - days[start_idx]) / 86_400_000
    out = {
        "period": {
            "start_utc": __import__('datetime').datetime.fromtimestamp(days[start_idx] / 1000, tz=__import__('datetime').timezone.utc).isoformat(),
            "end_utc": __import__('datetime').datetime.fromtimestamp(days[-1] / 1000, tz=__import__('datetime').timezone.utc).isoformat(),
            "days": round(total_days, 4),
            "steps": len(rets),
        },
        "config": {
            "lookback_days": args.lookback_days,
            "rebalance_days": args.rebalance_days,
            "n_shorts": args.n_shorts,
            "cost_bps": args.cost_bps,
            "strategy": "v2_style_short_only",
        },
        "performance": {
            "final_nav": round(nav, 6),
            "total_return": round(nav - 1.0, 6),
            "cagr": round((nav ** (365.0 / max(total_days, 1e-9)) - 1.0), 6),
            "max_drawdown": round(_max_dd(nav_path), 6),
            "sharpe": round(_sharpe(rets, total_days), 6),
        },
        "activity": {
            "avg_turnover": round(mean(turnover), 6) if turnover else 0.0,
            "trade_changes": changes,
        },
        "pnl_decomposition": {
            "price_component_sum": round(pnl_price, 6),
            "funding_component_sum": round(pnl_funding, 6),
            "cost_component_sum": round(pnl_cost, 6),
            "approx_sum": round(pnl_price + pnl_funding + pnl_cost, 6),
        },
    }

    print(json.dumps(out, indent=2, sort_keys=True))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
