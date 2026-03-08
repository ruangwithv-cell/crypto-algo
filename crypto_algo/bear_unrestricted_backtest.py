from __future__ import annotations

import argparse
import json
import math
import re
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
    p = argparse.ArgumentParser(description="Unrestricted short selector backtest")
    p.add_argument("--data-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/binance_extended_365d.json"))
    p.add_argument("--lookback-days", type=int, default=90)
    p.add_argument("--rebalance-days", type=int, default=3)
    p.add_argument("--n-shorts-min", type=int, default=4)
    p.add_argument("--n-shorts-max", type=int, default=10)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--min-history-bars", type=int, default=120)
    p.add_argument("--min-dollar-volume", type=float, default=5_000_000.0)
    p.add_argument("--score-threshold", type=float, default=0.15)
    p.add_argument("--spread-threshold", type=float, default=0.25)
    p.add_argument("--output-json", type=Path, default=None)
    return p.parse_args()


def _zmap(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    vals = list(values.values())
    mu = sum(vals) / len(vals)
    var = sum((x - mu) ** 2 for x in vals) / max(len(vals), 1)
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sd for k, v in values.items()}


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
    by_symbol = {}
    all_days = set()
    for s, bars in payload.get("price_data", {}).items():
        arr = sorted(bars, key=lambda x: x["open_time"])
        by_symbol[s] = arr
        for r in arr:
            all_days.add(int(r["open_time"]))
    days = sorted(all_days)
    px = {s: {int(r["open_time"]): r for r in bars} for s, bars in by_symbol.items()}

    funding = {}
    for s, rows in payload.get("funding_data", {}).items():
        dmap = {}
        tmp = {}
        for x in rows:
            t = int(x["funding_time"])
            d = (t // 86_400_000) * 86_400_000
            tmp.setdefault(d, []).append(float(x["funding_rate"]))
        for d, vals in tmp.items():
            dmap[d] = sum(vals) / len(vals)
        funding[s] = dmap

    return days, px, funding


def _closes(px_sym: dict[int, dict], days: list[int], idx: int, n: int) -> list[float]:
    out = []
    for j in range(max(0, idx - n + 1), idx + 1):
        b = px_sym.get(days[j])
        if b:
            out.append(float(b["close"]))
    return out


def _bars(px_sym: dict[int, dict], days: list[int], idx: int, n: int) -> list[dict]:
    out = []
    for j in range(max(0, idx - n + 1), idx + 1):
        b = px_sym.get(days[j])
        if b:
            out.append(b)
    return out


def _ret(closes: list[float], lookback: int):
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
    return max(min(math.sqrt(var), 0.30), 0.02)


def _eligible(
    idx: int,
    days: list[int],
    px: dict[str, dict[int, dict]],
    min_history_bars: int,
    min_dollar_volume: float,
) -> list[str]:
    excluded = {"BTC", "ETH", "USDT", "USDC", "DAI", "FDUSD", "BUSD", "TUSD", "PYUSD", "USDE", "STABLE"}
    out = []
    for s, pmap in px.items():
        if not re.fullmatch(r"[A-Z0-9]+", s):
            continue
        if s in excluded:
            continue
        if days[idx] not in pmap:
            continue
        hist = [d for d in days[: idx + 1] if d in pmap]
        if len(hist) < min_history_bars:
            continue
        bars20 = _bars(pmap, days, idx, 20)
        if len(bars20) < 10:
            continue
        dollar = [float(b["close"]) * float(b["volume"]) for b in bars20]
        med_dollar = sorted(dollar)[len(dollar) // 2]
        if med_dollar < min_dollar_volume:
            continue
        out.append(s)
    return out


def _regime(idx: int, days: list[int], eligible: list[str], px: dict[str, dict[int, dict]]) -> tuple[str, bool]:
    if idx < 60 or len(eligible) < 10:
        return "flat", False

    sw, lw, bw = (20, 60, 30) if idx < 200 else (50, 200, 90)

    med = []
    start = max(0, idx - lw - 20)
    for j in range(start, idx + 1):
        d = days[j]
        cls = [float(px[s][d]["close"]) for s in eligible if d in px[s]]
        if len(cls) >= 8:
            cls.sort()
            med.append(cls[len(cls) // 2])
    if len(med) < lw:
        return "flat", False

    ma_s = sum(med[-sw:]) / sw
    ma_l = sum(med[-lw:]) / lw

    weak = 0
    squeeze = 0
    use = 0
    for s in eligible:
        c = _closes(px[s], days, idx, 120)
        r7 = _ret(c, 7)
        if r7 is None or len(c) < bw:
            continue
        use += 1
        ma_b = sum(c[-bw:]) / bw
        weak += 1 if c[-1] < ma_b else 0
        squeeze += 1 if r7 > 0.25 else 0
    if use < 8:
        return "flat", False

    weak_r = weak / use
    squeeze_r = squeeze / use
    on = (ma_s < ma_l) and (weak_r >= 0.58) and (squeeze_r <= 0.30)
    if not on:
        return "flat", False
    if weak_r >= 0.75 and squeeze_r <= 0.20:
        return "deep_bear", True
    return "bear", True


def _target(
    idx: int,
    days: list[int],
    eligible: list[str],
    px: dict[str, dict[int, dict]],
    funding: dict[str, dict[int, float]],
    regime: str,
    n_min: int,
    n_max: int,
    score_threshold: float,
    spread_threshold: float,
) -> tuple[dict[str, Position], float, int]:
    day_key = (days[idx] // 86_400_000) * 86_400_000

    market_r30 = []
    for s in eligible:
        c = _closes(px[s], days, idx, 150)
        r30 = _ret(c, 30)
        if r30 is not None:
            market_r30.append(r30)
    m30 = sum(market_r30) / len(market_r30) if market_r30 else 0.0

    trend = {}
    rel = {}
    carry = {}
    breakdown = {}
    squeeze_pen = {}
    vol = {}
    liq = {}

    for s in eligible:
        c = _closes(px[s], days, idx, 180)
        if len(c) < 121:
            continue
        r3 = _ret(c, 3)
        r7 = _ret(c, 7)
        r14 = _ret(c, 14)
        r30 = _ret(c, 30)
        r60 = _ret(c, 60)
        r90 = _ret(c, 90)
        r120 = _ret(c, 120)
        if None in (r3, r7, r14, r30, r60, r90, r120):
            continue
        if r7 > 0.20:
            continue

        high90 = max(c[-90:])
        dist_high = (high90 - c[-1]) / high90 if high90 > 0 else 0.0
        f = funding.get(s, {}).get(day_key, 0.0)
        vv = _vol(c, 20)
        bars20 = _bars(px[s], days, idx, 20)
        dv = [float(b["close"]) * float(b["volume"]) for b in bars20]
        med_dv = sorted(dv)[len(dv) // 2] if dv else 0.0

        trend[s] = -(0.35 * r120 + 0.30 * r90 + 0.20 * r60 + 0.10 * r30 + 0.05 * r14)
        rel[s] = -(r30 - m30)
        carry[s] = f
        breakdown[s] = dist_high
        squeeze_pen[s] = max(r3, 0.0) + 0.5 * max(r7, 0.0)
        vol[s] = vv
        liq[s] = math.log(max(med_dv, 1.0))

    if not trend:
        return {}, 0.0, n_min

    zt = _zmap(trend)
    zr = _zmap(rel)
    zc = _zmap(carry)
    zb = _zmap(breakdown)
    zs = _zmap(squeeze_pen)
    zl = _zmap(liq)

    if regime == "deep_bear":
        w_t, w_r, w_c, w_b, w_l, w_s = 0.35, 0.15, 0.10, 0.35, 0.05, 0.20
        gross = 0.85
    else:
        w_t, w_r, w_c, w_b, w_l, w_s = 0.35, 0.20, 0.15, 0.20, 0.10, 0.20
        gross = 0.70

    score = {}
    for s in trend:
        score[s] = w_t * zt[s] + w_r * zr[s] + w_c * zc[s] + w_b * zb[s] + w_l * zl[s] - w_s * zs[s]

    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    top_score = ranked[0][1]
    nth_idx = min(max(n_min - 1, 0), len(ranked) - 1)
    spread = top_score - ranked[nth_idx][1]

    if spread >= spread_threshold and top_score >= 0.70:
        n_target = min(n_max, n_min + 3)
    elif spread >= spread_threshold * 0.7:
        n_target = min(n_max, n_min + 1)
    else:
        n_target = n_min

    picked = [s for s, sc in ranked[:n_target] if sc >= score_threshold]
    if not picked:
        return {}, spread, n_target

    inv = {s: 1.0 / max(vol[s], 1e-6) for s in picked}
    z = sum(inv.values())
    if z <= 0:
        return {}, spread, n_target

    out = {}
    for s in picked:
        w = -gross * inv[s] / z
        w = -min(abs(w), 0.20)
        vv = vol[s]
        stop = max(min(2.0 * vv, 0.18), 0.08)
        take = max(min(3.0 * vv, 0.35), 0.15)
        entry = float(px[s][days[idx]]["close"])
        out[s] = Position(s, w, entry, stop, take)

    g = sum(abs(p.weight) for p in out.values())
    if g > 1e-12:
        for p in out.values():
            p.weight *= gross / g

    return out, spread, n_target


def _bench_ew(eligible: list[str], gross: float) -> dict[str, float]:
    if not eligible:
        return {}
    w = -gross / len(eligible)
    return {s: w for s in eligible}


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    days, px, funding = _build_daily(payload)
    if len(days) < 200:
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
    turns = []
    trade_changes = 0
    regime_on_days = 0
    regime_deep_days = 0
    spreads = []
    n_targets = []
    eligible_counts = []

    bm_nav = 1.0
    bm_path = [1.0]
    bm_rets = []
    bm_prev_w: dict[str, float] = {}

    price_sum = 0.0
    fund_sum = 0.0
    cost_sum = 0.0

    for i in range(start_idx, len(days) - 1):
        day = days[i]
        nxt = days[i + 1]
        eligible = _eligible(i, days, px, args.min_history_bars, args.min_dollar_volume)
        eligible_counts.append(len(eligible))
        regime, on = _regime(i, days, eligible, px)

        if on:
            regime_on_days += 1
        if regime == "deep_bear":
            regime_deep_days += 1

        do_rebal = (i % max(args.rebalance_days, 1) == 0)
        cost = 0.0

        if do_rebal:
            if on:
                tgt, spread, n_target = _target(
                    i,
                    days,
                    eligible,
                    px,
                    funding,
                    regime,
                    args.n_shorts_min,
                    args.n_shorts_max,
                    args.score_threshold,
                    args.spread_threshold,
                )
            else:
                tgt, spread, n_target = {}, 0.0, args.n_shorts_min

            spreads.append(spread)
            n_targets.append(n_target)

            tw = {s: p.weight for s, p in tgt.items()}
            to = _turnover(prev_w, tw)
            turns.append(to)
            cost = to * (args.cost_bps / 10_000.0)
            trade_changes += sum(1 for k in set(prev_w) | set(tw) if abs(prev_w.get(k, 0.0) - tw.get(k, 0.0)) > 1e-12)
            active = tgt
            prev_w = tw

            # benchmark uses same regime gate, equal short across eligible
            bm_tgt = _bench_ew(eligible, gross=0.80) if on else {}
            bto = _turnover(bm_prev_w, bm_tgt)
            bm_cost = bto * (args.cost_bps / 10_000.0)
            bm_prev_w = dict(bm_tgt)
        else:
            bm_cost = 0.0

        step_price = 0.0
        step_fund = 0.0
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

            stop_p = pos.entry * (1 + pos.stop_pct)
            take_p = pos.entry * (1 - pos.take_pct)
            hit_stop = hi >= stop_p
            hit_take = lo <= take_p

            if hit_stop and hit_take:
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

            step_price += abs(pos.weight) * r
            day_key = (day // 86_400_000) * 86_400_000
            f = funding.get(s, {}).get(day_key)
            if f is not None:
                step_fund += abs(pos.weight) * float(f) * 3.0

        for s in to_close:
            active.pop(s, None)
            prev_w.pop(s, None)

        ret = step_price + step_fund - cost
        nav *= 1.0 + ret
        nav_path.append(nav)
        rets.append(ret)

        price_sum += step_price
        fund_sum += step_fund
        cost_sum -= cost

        # benchmark step
        bpnl = 0.0
        for s, w in bm_prev_w.items():
            bt = px.get(s, {}).get(day)
            bn = px.get(s, {}).get(nxt)
            if not bt or not bn:
                continue
            c0 = float(bt["close"])
            c1 = float(bn["close"])
            if c0 <= 0:
                continue
            bpnl += w * ((c1 - c0) / c0)
            day_key = (day // 86_400_000) * 86_400_000
            f = funding.get(s, {}).get(day_key)
            if f is not None:
                bpnl += abs(w) * float(f) * 3.0
        br = bpnl - bm_cost
        bm_nav *= 1.0 + br
        bm_rets.append(br)
        bm_path.append(bm_nav)

    total_days = (days[-1] - days[start_idx]) / 86_400_000
    out = {
        "period": {
            "start_utc": __import__("datetime").datetime.fromtimestamp(days[start_idx] / 1000, tz=__import__("datetime").timezone.utc).isoformat(),
            "end_utc": __import__("datetime").datetime.fromtimestamp(days[-1] / 1000, tz=__import__("datetime").timezone.utc).isoformat(),
            "days": round(total_days, 4),
            "steps": len(rets),
        },
        "config": {
            "strategy": "bear_unrestricted_v1",
            "lookback_days": args.lookback_days,
            "rebalance_days": args.rebalance_days,
            "n_shorts_min": args.n_shorts_min,
            "n_shorts_max": args.n_shorts_max,
            "cost_bps": args.cost_bps,
            "min_history_bars": args.min_history_bars,
            "min_dollar_volume": args.min_dollar_volume,
            "score_threshold": args.score_threshold,
            "spread_threshold": args.spread_threshold,
        },
        "performance": {
            "final_nav": round(nav, 6),
            "total_return": round(nav - 1.0, 6),
            "cagr": round((nav ** (365.0 / max(total_days, 1e-9)) - 1.0), 6),
            "max_drawdown": round(_max_dd(nav_path), 6),
            "sharpe": round(_sharpe(rets, total_days), 6),
        },
        "benchmark_ew_short_universe": {
            "final_nav": round(bm_nav, 6),
            "total_return": round(bm_nav - 1.0, 6),
            "cagr": round((bm_nav ** (365.0 / max(total_days, 1e-9)) - 1.0), 6),
            "max_drawdown": round(_max_dd(bm_path), 6),
            "sharpe": round(_sharpe(bm_rets, total_days), 6),
        },
        "activity": {
            "avg_turnover": round(mean(turns), 6) if turns else 0.0,
            "trade_changes": trade_changes,
            "regime_on_ratio": round(regime_on_days / max(len(rets), 1), 6),
            "deep_bear_ratio": round(regime_deep_days / max(len(rets), 1), 6),
            "avg_spread": round(mean(spreads), 6) if spreads else 0.0,
            "avg_n_target": round(mean(n_targets), 6) if n_targets else 0.0,
            "avg_eligible": round(mean(eligible_counts), 4) if eligible_counts else 0.0,
            "min_eligible": min(eligible_counts) if eligible_counts else 0,
            "max_eligible": max(eligible_counts) if eligible_counts else 0,
        },
        "pnl_decomposition": {
            "price_component_sum": round(price_sum, 6),
            "funding_component_sum": round(fund_sum, 6),
            "cost_component_sum": round(cost_sum, 6),
            "approx_sum": round(price_sum + fund_sum + cost_sum, 6),
        },
    }

    print(json.dumps(out, indent=2, sort_keys=True))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
