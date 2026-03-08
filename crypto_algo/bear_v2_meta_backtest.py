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
    p = argparse.ArgumentParser(description="bear_v2_meta backtest")
    p.add_argument("--data-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/binance_extended_365d.json"))
    p.add_argument("--lookback-days", type=int, default=90)
    p.add_argument("--rebalance-days", type=int, default=3)
    p.add_argument("--n-shorts-min", type=int, default=3)
    p.add_argument("--n-shorts-max", type=int, default=6)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--persistence-runs", type=int, default=2)
    p.add_argument("--spread-threshold", type=float, default=0.35)
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

    return days, px, funding, payload.get("symbols", [])


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


def _eligible(idx: int, days: list[int], px: dict[str, dict[int, dict]], symbols_meta: list[dict]) -> list[str]:
    excluded = {"BTC", "ETH", "USDT", "USDC", "DAI", "FDUSD", "BUSD", "TUSD", "PYUSD", "USDE", "STABLE"}
    out = []
    for m in symbols_meta:
        s = m.get("asset")
        if not s or s in excluded or m.get("status") != "OK":
            continue
        pmap = px.get(s, {})
        hist = [d for d in days[: idx + 1] if d in pmap]
        if len(hist) < 180:
            continue
        if days[idx] not in pmap:
            continue
        out.append(s)
    return out


def _regime(idx: int, days: list[int], eligible: list[str], px: dict[str, dict[int, dict]]) -> tuple[str, bool]:
    if idx < 60 or len(eligible) < 5:
        return "flat", False

    if idx >= 200:
        sw, lw, bw = 50, 200, 90
    else:
        sw, lw, bw = 20, 60, 30

    med = []
    start = max(0, idx - lw - 20)
    for j in range(start, idx + 1):
        d = days[j]
        cls = [float(px[s][d]["close"]) for s in eligible if d in px[s]]
        if len(cls) >= 4:
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
    if use < 4:
        return "flat", False

    weak_r = weak / use
    squeeze_r = squeeze / use
    on = (ma_s < ma_l) and (weak_r >= 0.55) and (squeeze_r <= 0.35)
    if not on:
        return "flat", False

    if weak_r >= 0.75 and squeeze_r <= 0.20:
        return "deep_bear", True
    return "bear", True


def _base_components(idx: int, days: list[int], eligible: list[str], px: dict[str, dict[int, dict]], funding: dict[str, dict[int, float]]):
    day_key = (days[idx] // 86_400_000) * 86_400_000
    market_r30 = []
    for s in eligible:
        c = _closes(px[s], days, idx, 120)
        r30 = _ret(c, 30)
        if r30 is not None:
            market_r30.append(r30)
    m30 = sum(market_r30) / len(market_r30) if market_r30 else 0.0

    raw = {}
    for s in eligible:
        c = _closes(px[s], days, idx, 120)
        r7 = _ret(c, 7)
        r14 = _ret(c, 14)
        r30 = _ret(c, 30)
        r90 = _ret(c, 90)
        if None in (r7, r14, r30, r90):
            continue
        if r7 > 0.20:
            continue
        f = funding.get(s, {}).get(day_key, 0.0)
        high60 = max(c[-60:]) if len(c) >= 60 else max(c)
        dist_high = (high60 - c[-1]) / high60 if high60 > 0 else 0.0
        raw[s] = {
            "r7": r7,
            "r14": r14,
            "r30": r30,
            "r90": r90,
            "fund": f,
            "dist_high": dist_high,
            "rel30": r30 - m30,
            "vol": _vol(c),
        }
    return raw


def _selector_scores(raw: dict[str, dict]):
    # subagent A
    a1 = {s: -(0.55*v['r90'] + 0.30*v['r30'] + 0.15*v['r7']) for s,v in raw.items()}
    a2 = {s: -v['rel30'] for s,v in raw.items()}
    a3 = {s: v['fund'] for s,v in raw.items()}
    a4 = {s: v['dist_high'] for s,v in raw.items()}
    za1,za2,za3,za4 = _zmap(a1),_zmap(a2),_zmap(a3),_zmap(a4)
    trend_relative = {s: 0.45*za1[s]+0.25*za2[s]+0.20*za3[s]+0.10*za4[s] for s in raw}

    # subagent B
    b1 = {s: v['fund'] for s,v in raw.items()}
    b2 = {s: -v['r30'] for s,v in raw.items()}
    b3 = {s: -v['r7'] for s,v in raw.items()}
    b4 = {s: v['dist_high'] for s,v in raw.items()}
    zb1,zb2,zb3,zb4 = _zmap(b1),_zmap(b2),_zmap(b3),_zmap(b4)
    carry_pressure = {s: 0.40*zb1[s]+0.25*zb2[s]+0.20*zb3[s]+0.15*zb4[s] for s in raw}

    # subagent C
    c1 = {s: v['dist_high'] for s,v in raw.items()}
    c2 = {s: -v['r30'] for s,v in raw.items()}
    c3 = {s: -v['r14'] for s,v in raw.items()}
    c4 = {s: -abs(v['r7']) for s,v in raw.items()}
    zc1,zc2,zc3,zc4 = _zmap(c1),_zmap(c2),_zmap(c3),_zmap(c4)
    breakdown_quality = {s: 0.45*zc1[s]+0.25*zc2[s]+0.20*zc3[s]+0.10*zc4[s] for s in raw}

    return trend_relative, carry_pressure, breakdown_quality


def _meta_target(
    idx: int,
    days: list[int],
    eligible: list[str],
    px: dict[str, dict[int, dict]],
    funding: dict[str, dict[int, float]],
    regime: str,
    n_min: int,
    n_max: int,
    spread_threshold: float,
    streaks: dict[str, int],
    persistence_runs: int,
) -> tuple[dict[str, Position], float, int]:
    raw = _base_components(idx, days, eligible, px, funding)
    if not raw:
        return {}, 0.0, n_min

    trend_relative, carry_pressure, breakdown_quality = _selector_scores(raw)

    # regime-dependent ensemble
    if regime == "deep_bear":
        w_tr, w_ca, w_br = 0.35, 0.15, 0.50
    else:
        w_tr, w_ca, w_br = 0.35, 0.40, 0.25

    score = {}
    for s in raw:
        score[s] = w_tr * trend_relative[s] + w_ca * carry_pressure[s] + w_br * breakdown_quality[s]

    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return {}, 0.0, n_min

    top_score = ranked[0][1]
    nth_idx = min(max(n_min - 1, 0), len(ranked) - 1)
    spread = top_score - ranked[nth_idx][1]

    if spread >= spread_threshold and top_score >= 0.60:
        n_target = min(n_max, max(n_min + 2, n_min))
    elif spread >= spread_threshold * 0.7:
        n_target = min(n_max, n_min + 1)
    else:
        n_target = n_min

    candidate_symbols = [s for s, sc in ranked[:n_target] if sc >= 0.10]
    # update persistence streaks
    cand_set = set(candidate_symbols)
    for s in list(streaks.keys()):
        if s not in cand_set:
            streaks[s] = 0
    for s in cand_set:
        streaks[s] = streaks.get(s, 0) + 1

    picked = [s for s in candidate_symbols if streaks.get(s, 0) >= persistence_runs]
    if not picked:
        return {}, spread, n_target

    # inverse-vol weights
    inv = {s: 1.0 / max(raw[s]['vol'], 1e-6) for s in picked}
    z = sum(inv.values())
    if z <= 0:
        return {}, spread, n_target

    gross = 0.80 if regime == "deep_bear" else 0.65
    out = {}
    for s in picked:
        w = -gross * inv[s] / z
        w = -min(abs(w), 0.22)
        v = raw[s]['vol']
        stop = max(min(2.0 * v, 0.18), 0.08)
        take = max(min(3.0 * v, 0.35), 0.15)
        entry = float(px[s][days[idx]]["close"])
        out[s] = Position(s, w, entry, stop, take)

    g = sum(abs(p.weight) for p in out.values())
    if g > 1e-12:
        for p in out.values():
            p.weight *= gross / g

    return out, spread, n_target


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    days, px, funding, symbols_meta = _build_daily(payload)

    end_day = days[-1]
    cutoff = end_day - max(args.lookback_days, 1) * 86_400_000
    start_idx = 0
    while start_idx < len(days) - 1 and days[start_idx] < cutoff:
        start_idx += 1

    nav = 1.0
    nav_path = [1.0]
    rets = []
    active = {}
    prev_w = {}
    turns = []
    trade_changes = 0
    regime_on_days = 0
    regime_deep_days = 0
    spread_series = []
    n_target_series = []

    price_sum = 0.0
    fund_sum = 0.0
    cost_sum = 0.0

    # persistence memory
    streaks = {}

    for i in range(start_idx, len(days) - 1):
        day = days[i]
        nxt = days[i + 1]
        eligible = _eligible(i, days, px, symbols_meta)
        regime, on = _regime(i, days, eligible, px)
        if on:
            regime_on_days += 1
        if regime == "deep_bear":
            regime_deep_days += 1

        do_rebal = (i % max(args.rebalance_days, 1) == 0)
        cost = 0.0

        if do_rebal:
            if on:
                tgt, spread, n_target = _meta_target(
                    i, days, eligible, px, funding, regime,
                    args.n_shorts_min, args.n_shorts_max,
                    args.spread_threshold, streaks, args.persistence_runs,
                )
            else:
                tgt, spread, n_target = {}, 0.0, args.n_shorts_min
                for s in list(streaks.keys()):
                    streaks[s] = 0

            spread_series.append(spread)
            n_target_series.append(n_target)
            tw = {s: p.weight for s, p in tgt.items()}
            to = _turnover(prev_w, tw)
            turns.append(to)
            cost = to * (args.cost_bps / 10_000.0)
            trade_changes += sum(1 for k in set(prev_w) | set(tw) if abs(prev_w.get(k, 0.0) - tw.get(k, 0.0)) > 1e-12)
            active = tgt
            prev_w = tw

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
            "n_shorts_min": args.n_shorts_min,
            "n_shorts_max": args.n_shorts_max,
            "cost_bps": args.cost_bps,
            "persistence_runs": args.persistence_runs,
            "spread_threshold": args.spread_threshold,
            "strategy": "bear_v2_meta",
        },
        "performance": {
            "final_nav": round(nav, 6),
            "total_return": round(nav - 1.0, 6),
            "cagr": round((nav ** (365.0 / max(total_days, 1e-9)) - 1.0), 6),
            "max_drawdown": round(_max_dd(nav_path), 6),
            "sharpe": round(_sharpe(rets, total_days), 6),
        },
        "activity": {
            "avg_turnover": round(mean(turns), 6) if turns else 0.0,
            "trade_changes": trade_changes,
            "regime_on_ratio": round(regime_on_days / max(len(rets), 1), 6),
            "deep_bear_ratio": round(regime_deep_days / max(len(rets), 1), 6),
            "avg_spread": round(mean(spread_series), 6) if spread_series else 0.0,
            "avg_n_target": round(mean(n_target_series), 6) if n_target_series else 0.0,
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
