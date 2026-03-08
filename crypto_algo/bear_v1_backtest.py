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
    p = argparse.ArgumentParser(description="Bear-market short engine backtest (v1)")
    p.add_argument("--data-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/binance_extended_365d.json"))
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--rebalance-days", type=int, default=3)
    p.add_argument("--n-shorts", type=int, default=5)
    p.add_argument("--lookback-days", type=int, default=365)
    p.add_argument("--output-json", type=Path, default=None)
    return p.parse_args()


def _zmap(v: dict[str, float]) -> dict[str, float]:
    if not v:
        return {}
    vals = list(v.values())
    mu = sum(vals) / len(vals)
    var = sum((x - mu) ** 2 for x in vals) / max(len(vals), 1)
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return {k: 0.0 for k in v}
    return {k: (x - mu) / sd for k, x in v.items()}


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


def _build_daily_matrix(payload: dict):
    # symbol -> list of bars sorted by open_time
    price_data = payload.get("price_data", {})
    by_symbol: dict[str, list[dict]] = {}
    all_days = set()
    for sym, bars in price_data.items():
        b = sorted(bars, key=lambda x: x["open_time"])
        by_symbol[sym] = b
        for r in b:
            all_days.add(int(r["open_time"]))
    days = sorted(all_days)

    # symbol/day lookup
    px = {}
    for sym, bars in by_symbol.items():
        px[sym] = {int(r["open_time"]): r for r in bars}

    # funding map: symbol/day -> avg funding rate for that UTC day
    funding_map: dict[str, dict[int, float]] = {}
    for sym, rows in payload.get("funding_data", {}).items():
        tmp: dict[int, list[float]] = {}
        for x in rows:
            t = int(x["funding_time"])
            day = (t // 86_400_000) * 86_400_000
            tmp.setdefault(day, []).append(float(x["funding_rate"]))
        funding_map[sym] = {d: (sum(v) / len(v)) for d, v in tmp.items()}

    return days, by_symbol, px, funding_map


def _window_closes(px_sym: dict[int, dict], days: list[int], idx: int, n: int) -> list[float]:
    out = []
    for j in range(max(0, idx - n + 1), idx + 1):
        bar = px_sym.get(days[j])
        if bar:
            out.append(float(bar["close"]))
    return out


def _ret(closes: list[float], lookback: int) -> float | None:
    if len(closes) <= lookback:
        return None
    a = closes[-lookback - 1]
    b = closes[-1]
    if a <= 0:
        return None
    return (b - a) / a


def _vol(closes: list[float], lookback: int = 20) -> float:
    if len(closes) < 8:
        return 0.06
    arr = closes[-(lookback + 1):]
    rets = []
    for a, b in zip(arr[:-1], arr[1:]):
        if a > 0:
            rets.append((b - a) / a)
    if len(rets) < 6:
        return 0.06
    mu = sum(rets) / len(rets)
    var = sum((x - mu) ** 2 for x in rets) / max(len(rets), 1)
    return max(min(math.sqrt(var), 0.25), 0.02)


def _eligible_symbols(symbols_meta: list[dict], px: dict[str, dict[int, dict]], days: list[int], idx: int) -> list[str]:
    day = days[idx]
    out = []
    excluded = {"BTC", "ETH", "USDT", "USDC", "DAI", "FDUSD", "BUSD", "TUSD", "PYUSD", "USDE", "STABLE"}
    for m in symbols_meta:
        s = m["asset"]
        if s in excluded or m.get("status") != "OK":
            continue
        # listing age >= 180 bars up to now
        hist = [d for d in days[: idx + 1] if d in px.get(s, {})]
        if len(hist) < 180:
            continue
        bar = px.get(s, {}).get(day)
        if not bar:
            continue
        out.append(s)
    return out


def _regime(idx: int, days: list[int], eligible: list[str], px: dict[str, dict[int, dict]]) -> tuple[bool, dict]:
    if len(eligible) < 6:
        return False, {"reason": "insufficient_history"}

    if idx >= 200:
        short_win = 50
        long_win = 200
        breadth_ma_win = 90
    elif idx >= 60:
        short_win = 20
        long_win = 60
        breadth_ma_win = 30
    else:
        return False, {"reason": "insufficient_history"}

    # synthetic market index close = median close across eligible symbols
    med_closes = []
    start_j = max(0, idx - (long_win + 20))
    for j in range(start_j, idx + 1):
        cls = []
        d = days[j]
        for s in eligible:
            b = px[s].get(d)
            if b:
                cls.append(float(b["close"]))
        if len(cls) >= 4:
            cls.sort()
            med_closes.append(cls[len(cls) // 2])

    if len(med_closes) < long_win:
        return False, {"reason": "insufficient_index"}

    ma_short = sum(med_closes[-short_win:]) / short_win
    ma_long = sum(med_closes[-long_win:]) / long_win

    breadth_weak = 0
    squeeze = 0
    usable = 0
    for s in eligible:
        closes = _window_closes(px[s], days, idx, 120)
        r7 = _ret(closes, 7)
        if len(closes) < breadth_ma_win or r7 is None:
            continue
        usable += 1
        ma_b = sum(closes[-breadth_ma_win:]) / breadth_ma_win
        if closes[-1] < ma_b:
            breadth_weak += 1
        if r7 > 0.25:
            squeeze += 1

    if usable < 4:
        return False, {"reason": "insufficient_breadth"}

    breadth_weak_ratio = breadth_weak / usable
    squeeze_ratio = squeeze / usable
    on = (ma_short < ma_long) and (breadth_weak_ratio >= 0.60) and (squeeze_ratio <= 0.30)
    return on, {
        "ma_short": ma_short,
        "ma_long": ma_long,
        "short_win": short_win,
        "long_win": long_win,
        "breadth_weak_ratio": breadth_weak_ratio,
        "squeeze_ratio": squeeze_ratio,
    }


def _select_shorts(
    idx: int,
    days: list[int],
    eligible: list[str],
    px: dict[str, dict[int, dict]],
    funding_map: dict[str, dict[int, float]],
    n_shorts: int,
) -> dict[str, Position]:
    day = days[idx]
    raw_mom = {}
    raw_rel = {}
    raw_carry = {}
    raw_squeeze_pen = {}
    raw_vol = {}

    # synthetic market 30d return for relative weakness
    market_r30s = []
    for s in eligible:
        closes = _window_closes(px[s], days, idx, 60)
        r30 = _ret(closes, 30)
        if r30 is not None:
            market_r30s.append(r30)
    if not market_r30s:
        return {}
    market_r30 = sum(market_r30s) / len(market_r30s)

    for s in eligible:
        closes = _window_closes(px[s], days, idx, 120)
        r7 = _ret(closes, 7)
        r30 = _ret(closes, 30)
        r90 = _ret(closes, 90)
        if r7 is None or r30 is None or r90 is None:
            continue

        # avoid squeeze candidates
        if r7 > 0.20:
            continue

        fund = funding_map.get(s, {}).get((day // 86_400_000) * 86_400_000, 0.0)
        mom = -(0.55 * r90 + 0.30 * r30 + 0.15 * r7)
        rel = -(r30 - market_r30)
        carry = fund  # positive funding helps shorts
        squeeze_pen = max(r7, 0.0)
        vv = _vol(closes, 20)

        raw_mom[s] = mom
        raw_rel[s] = rel
        raw_carry[s] = carry
        raw_squeeze_pen[s] = squeeze_pen
        raw_vol[s] = vv

    zm = _zmap(raw_mom)
    zr = _zmap(raw_rel)
    zc = _zmap(raw_carry)
    zs = _zmap(raw_squeeze_pen)

    scored = []
    for s in raw_mom:
        score = 0.45 * zm.get(s, 0.0) + 0.25 * zr.get(s, 0.0) + 0.20 * zc.get(s, 0.0) - 0.10 * zs.get(s, 0.0)
        if score >= 0.15:
            scored.append((s, score, raw_vol[s]))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:n_shorts]
    if not top:
        return {}

    # inverse-vol weighted shorts, capped
    inv = {s: 1.0 / max(v, 1e-6) for s, _, v in top}
    z = sum(inv.values())
    if z <= 0:
        return {}

    gross = 0.80
    out = {}
    for s, sc, v in top:
        w = -gross * (inv[s] / z)
        w = -min(abs(w), 0.22)
        stop = max(min(2.0 * v, 0.18), 0.08)
        take = max(min(3.0 * v, 0.35), 0.15)
        entry = float(px[s][days[idx]]["close"])
        out[s] = Position(symbol=s, weight=w, entry=entry, stop_pct=stop, take_pct=take)

    # renormalize to target gross
    g = sum(abs(p.weight) for p in out.values())
    if g > 1e-12:
        for p in out.values():
            p.weight = p.weight * (gross / g)

    return out


def _bench_ew_short(idx: int, days: list[int], eligible: list[str], px: dict[str, dict[int, dict]]) -> dict[str, float]:
    # short all eligible equally, bear regime dependent externally
    if not eligible:
        return {}
    w = -0.80 / len(eligible)
    return {s: w for s in eligible}


def _bench_topn_short(idx: int, days: list[int], eligible: list[str], px: dict[str, dict[int, dict]], n: int) -> dict[str, float]:
    arr = []
    for s in eligible:
        closes = _window_closes(px[s], days, idx, 60)
        r30 = _ret(closes, 30)
        if r30 is None:
            continue
        arr.append((s, r30))
    arr.sort(key=lambda x: x[1])
    top = [s for s, _ in arr[: max(n, 1)]]
    if not top:
        return {}
    w = -0.80 / len(top)
    return {s: w for s in top}


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    days, by_symbol, px, funding_map = _build_daily_matrix(payload)
    full_days = days
    symbols_meta = payload.get("symbols", [])

    if len(full_days) < 220:
        raise SystemExit("Not enough daily history")

    start_idx = 0
    if args.lookback_days and args.lookback_days > 0:
        end_day = full_days[-1]
        cutoff = end_day - args.lookback_days * 86_400_000
        while start_idx < len(full_days) - 1 and full_days[start_idx] < cutoff:
            start_idx += 1

    nav = 1.0
    nav_path = [1.0]
    rets = []
    active: dict[str, Position] = {}
    prev_w: dict[str, float] = {}

    bm_modes = ("ew_short_universe", "topn_short_momentum")
    bm_nav = {m: 1.0 for m in bm_modes}
    bm_nav_path = {m: [1.0] for m in bm_modes}
    bm_rets = {m: [] for m in bm_modes}
    bm_prev_w = {m: {} for m in bm_modes}

    turnover = []
    regime_on_days = 0
    trade_changes = 0
    pnl_price_sum = 0.0
    pnl_funding_sum = 0.0
    pnl_cost_sum = 0.0

    for i in range(start_idx, len(full_days) - 1):
        day = full_days[i]
        nxt = full_days[i + 1]
        eligible = _eligible_symbols(symbols_meta, px, full_days, i)
        regime_on, regime_meta = _regime(i, full_days, eligible, px)
        if regime_on:
            regime_on_days += 1

        do_rebal = (i % max(args.rebalance_days, 1) == 0)
        cost = 0.0

        if do_rebal:
            if regime_on:
                target_pos = _select_shorts(i, full_days, eligible, px, funding_map, args.n_shorts)
            else:
                target_pos = {}

            target_w = {s: p.weight for s, p in target_pos.items()}
            to = _turnover(prev_w, target_w)
            turnover.append(to)
            cost = to * (args.cost_bps / 10_000.0)
            trade_changes += sum(1 for k in set(prev_w) | set(target_w) if abs(prev_w.get(k, 0.0) - target_w.get(k, 0.0)) > 1e-12)
            active = target_pos
            prev_w = target_w

        pnl = 0.0
        price_leg = 0.0
        funding_leg = 0.0
        to_close = []
        for s, pos in active.items():
            bar_t = px.get(s, {}).get(day)
            bar_n = px.get(s, {}).get(nxt)
            if not bar_t or not bar_n:
                continue
            c0 = float(bar_t["close"])
            c1 = float(bar_n["close"])
            hi = float(bar_n["high"])
            lo = float(bar_n["low"])
            if c0 <= 0:
                continue

            stop_price = pos.entry * (1.0 + pos.stop_pct)
            take_price = pos.entry * (1.0 - pos.take_pct)

            hit_stop = hi >= stop_price
            hit_take = lo <= take_price

            if hit_stop and hit_take:
                # conservative: assume stop hit first
                r = -pos.stop_pct
                to_close.append(s)
            elif hit_stop:
                r = -pos.stop_pct
                to_close.append(s)
            elif hit_take:
                r = pos.take_pct
                to_close.append(s)
            else:
                r = (c0 - c1) / c0

            pr = abs(pos.weight) * r
            pnl += pr
            price_leg += pr

            # funding carry (short receives positive funding)
            day_key = (day // 86_400_000) * 86_400_000
            f = funding_map.get(s, {}).get(day_key)
            if f is not None:
                fr = abs(pos.weight) * float(f) * 3.0
                pnl += fr
                funding_leg += fr

        for s in to_close:
            active.pop(s, None)
            prev_w.pop(s, None)

        ret = pnl - cost
        pnl_price_sum += price_leg
        pnl_funding_sum += funding_leg
        pnl_cost_sum -= cost
        nav *= 1.0 + ret
        rets.append(ret)
        nav_path.append(nav)

        # benchmarks (same regime gate)
        bm_targets = {
            "ew_short_universe": _bench_ew_short(i, full_days, eligible, px) if regime_on else {},
            "topn_short_momentum": _bench_topn_short(i, full_days, eligible, px, args.n_shorts) if regime_on else {},
        }

        for m in bm_modes:
            bcost = 0.0
            if do_rebal:
                bto = _turnover(bm_prev_w[m], bm_targets[m])
                bcost = bto * (args.cost_bps / 10_000.0)
                bm_prev_w[m] = dict(bm_targets[m])

            bpnl = 0.0
            for s, w in bm_prev_w[m].items():
                bar_t = px.get(s, {}).get(day)
                bar_n = px.get(s, {}).get(nxt)
                if not bar_t or not bar_n:
                    continue
                c0 = float(bar_t["close"])
                c1 = float(bar_n["close"])
                if c0 <= 0:
                    continue
                bpnl += w * ((c1 - c0) / c0)

                day_key = (day // 86_400_000) * 86_400_000
                f = funding_map.get(s, {}).get(day_key)
                if f is not None:
                    bpnl += abs(w) * float(f) * 3.0

            br = bpnl - bcost
            bm_nav[m] *= 1.0 + br
            bm_rets[m].append(br)
            bm_nav_path[m].append(bm_nav[m])

    total_days = (full_days[-1] - full_days[start_idx]) / 86_400_000

    out = {
        "period": {
            "start_utc": __import__("datetime").datetime.fromtimestamp(full_days[start_idx] / 1000, tz=__import__("datetime").timezone.utc).isoformat(),
            "end_utc": __import__("datetime").datetime.fromtimestamp(full_days[-1] / 1000, tz=__import__("datetime").timezone.utc).isoformat(),
            "days": round(total_days, 4),
            "steps": len(rets),
        },
        "config": {
            "cost_bps": args.cost_bps,
            "rebalance_days": args.rebalance_days,
            "n_shorts": args.n_shorts,
            "lookback_days": args.lookback_days,
            "strategy": "bear_v1_short_only_regime",
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
            "trade_changes": trade_changes,
            "regime_on_ratio": round(regime_on_days / max(len(rets), 1), 6),
        },
        "pnl_decomposition": {
            "price_component_sum": round(pnl_price_sum, 6),
            "funding_component_sum": round(pnl_funding_sum, 6),
            "cost_component_sum": round(pnl_cost_sum, 6),
            "approx_sum": round(pnl_price_sum + pnl_funding_sum + pnl_cost_sum, 6),
        },
        "benchmarks": {
            m: {
                "final_nav": round(bm_nav[m], 6),
                "total_return": round(bm_nav[m] - 1.0, 6),
                "cagr": round((bm_nav[m] ** (365.0 / max(total_days, 1e-9)) - 1.0), 6),
                "max_drawdown": round(_max_dd(bm_nav_path[m]), 6),
                "sharpe": round(_sharpe(bm_rets[m], total_days), 6),
            }
            for m in bm_modes
        },
    }

    print(json.dumps(out, indent=2, sort_keys=True))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
