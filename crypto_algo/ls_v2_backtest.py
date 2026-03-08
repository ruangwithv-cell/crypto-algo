from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev

from .ls_data import build_points, collect_timestamps, load_state, prices_at_next, symbol_return_path


@dataclass
class Position:
    side: str  # 'long' or 'short'
    weight: float
    entry_price: float
    stop_pct: float
    take_pct: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="crypto_algo_ls_v2 backtest")
    p.add_argument("--history-json", type=Path, default=Path("/Users/mini/crypto_short_v2_state/portfolio_state.json"))
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--lookback-days", type=int, default=None)
    p.add_argument("--rebalance-steps", type=int, default=3)
    p.add_argument("--n-shorts", type=int, default=5)
    p.add_argument("--n-longs", type=int, default=3)
    p.add_argument("--short-min-score", type=float, default=0.05)
    p.add_argument("--long-min-score", type=float, default=0.05)
    p.add_argument("--output-json", type=Path, default=None)
    return p.parse_args()


def _z(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    vals = list(values.values())
    mu = sum(vals) / len(vals)
    var = sum((x - mu) ** 2 for x in vals) / max(len(vals), 1)
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sd for k, v in values.items()}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _vol_est(data: dict, symbol: str, ts: datetime, lookback_points: int = 20) -> float:
    rets = symbol_return_path(data, symbol, ts, lookback_points)
    if len(rets) < 6:
        return 0.06
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / max(len(rets), 1)
    vol = math.sqrt(max(var, 1e-12))
    return float(_clamp(vol, 0.02, 0.25))


def _max_drawdown(nav: list[float]) -> float:
    if not nav:
        return 0.0
    peak = nav[0]
    mdd = 0.0
    for x in nav:
        if x > peak:
            peak = x
        dd = (x - peak) / peak
        if dd < mdd:
            mdd = dd
    return mdd


def _cagr(nav: float, total_days: float) -> float:
    return (nav ** (365.0 / max(total_days, 1e-9)) - 1.0) if total_days > 0 else 0.0


def _sharpe(step_rets: list[float], total_days: float) -> float:
    if not step_rets:
        return 0.0
    avg = mean(step_rets)
    vol = pstdev(step_rets) if len(step_rets) > 1 else 0.0
    steps_per_day = len(step_rets) / max(total_days, 1e-9)
    return (avg / vol) * math.sqrt(365.0 * steps_per_day) if vol > 0 else 0.0


def _turnover(prev: dict[str, Position], target: dict[str, Position]) -> float:
    keys = set(prev) | set(target)
    return 0.5 * sum(abs(target.get(k, Position("long", 0.0, 0.0, 0.0, 0.0)).weight - prev.get(k, Position("long", 0.0, 0.0, 0.0, 0.0)).weight) for k in keys)


def _turnover_weights(prev: dict[str, float], target: dict[str, float]) -> float:
    keys = set(prev) | set(target)
    return 0.5 * sum(abs(target.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)


def _build_targets(
    data: dict,
    ts: datetime,
    points,
    n_shorts: int,
    n_longs: int,
    short_min_score: float,
    long_min_score: float,
) -> tuple[dict[str, float], dict[str, float], str]:
    # Universe filters
    excluded = {
        "BTC", "ETH", "USDT", "USDC", "DAI", "FDUSD", "BUSD", "TUSD", "PYUSD", "USDE", "STABLE"
    }
    eligible = [
        p for p in points
        if p.symbol not in excluded
        and 30 <= p.rank <= 220
        and p.oi_usd is not None and p.oi_usd >= 8_000_000.0
        and p.ret_7d is not None and p.ret_30d is not None
    ]
    if not eligible:
        return {}, {}, "flat"

    # Regime from cross-sectional median 7d return
    r7 = sorted(p.ret_7d for p in eligible if p.ret_7d is not None)
    med7 = r7[len(r7) // 2] if r7 else 0.0
    if med7 > 0.10:
        regime = "risk_on"
        gross_short, gross_long = 0.35, 0.35
    elif med7 > 0.02:
        regime = "neutral"
        gross_short, gross_long = 0.50, 0.20
    else:
        regime = "risk_off"
        gross_short, gross_long = 0.80, 0.00

    raw_short: dict[str, float] = {}
    raw_long: dict[str, float] = {}
    raw_carry: dict[str, float] = {}
    raw_oi_short: dict[str, float] = {}
    raw_oi_long: dict[str, float] = {}
    raw_liq: dict[str, float] = {}

    for p in eligible:
        mom = 0.65 * (p.ret_30d or 0.0) + 0.35 * (p.ret_7d or 0.0)
        carry_short = p.funding_8h or 0.0
        oi_ch = p.oi_change_7d or 0.0
        liq = math.log(max(p.oi_usd or 1.0, 1.0))

        # Squeeze filter for shorts: avoid hot names with rising OI
        squeeze = (p.ret_7d or 0.0) > 0.20 and oi_ch > 0.15
        if not squeeze:
            raw_short[p.symbol] = -mom
            raw_carry[p.symbol] = carry_short
            raw_oi_short[p.symbol] = oi_ch if mom < 0 else -oi_ch
            raw_liq[p.symbol] = liq

        raw_long[p.symbol] = mom
        raw_oi_long[p.symbol] = oi_ch if mom > 0 else -oi_ch

    z_short_m = _z(raw_short)
    z_short_c = _z(raw_carry)
    z_short_o = _z(raw_oi_short)
    z_liq = _z(raw_liq)

    short_scores = {
        s: 0.50 * z_short_m.get(s, 0.0) + 0.25 * z_short_c.get(s, 0.0) + 0.15 * z_short_o.get(s, 0.0) + 0.10 * z_liq.get(s, 0.0)
        for s in raw_short
    }

    z_long_m = _z(raw_long)
    z_long_o = _z(raw_oi_long)
    long_scores = {s: 0.75 * z_long_m.get(s, 0.0) + 0.25 * z_long_o.get(s, 0.0) for s in raw_long}

    shorts = [s for s, sc in sorted(short_scores.items(), key=lambda kv: kv[1], reverse=True) if sc >= short_min_score][:n_shorts]
    longs = [s for s, sc in sorted(long_scores.items(), key=lambda kv: kv[1], reverse=True) if sc >= long_min_score][:n_longs]

    short_w: dict[str, float] = {}
    long_w: dict[str, float] = {}

    if shorts and gross_short > 0:
        eq = gross_short / len(shorts)
        for s in shorts:
            short_w[s] = -eq

    if longs and gross_long > 0:
        eq = gross_long / len(longs)
        for s in longs:
            long_w[s] = eq

    # cap single name to avoid concentration
    for k in list(short_w):
        short_w[k] = -min(abs(short_w[k]), 0.20)
    for k in list(long_w):
        long_w[k] = min(abs(long_w[k]), 0.20)

    return short_w, long_w, regime


def _eligible_universe(points):
    excluded = {
        "BTC", "ETH", "USDT", "USDC", "DAI", "FDUSD", "BUSD", "TUSD", "PYUSD", "USDE", "STABLE"
    }
    return [
        p for p in points
        if p.symbol not in excluded
        and 30 <= p.rank <= 220
        and p.oi_usd is not None and p.oi_usd >= 8_000_000.0
        and p.ret_30d is not None
    ]


def _benchmark_target(points, mode: str, n_shorts: int) -> dict[str, float]:
    uni = _eligible_universe(points)
    if not uni:
        return {}
    if mode == "ew_short_universe":
        names = [p.symbol for p in uni]
    elif mode == "topn_short_momentum":
        sorted_uni = sorted(uni, key=lambda p: p.ret_30d or 0.0)
        names = [p.symbol for p in sorted_uni[: max(n_shorts, 1)]]
    else:
        names = []
    if not names:
        return {}
    w = -1.0 / len(names)
    return {s: w for s in names}


def main() -> int:
    args = parse_args()
    data = load_state(args.history_json)
    ts_list = collect_timestamps(data)
    if len(ts_list) < 3:
        raise SystemExit("Not enough timestamps")

    if args.lookback_days is not None and args.lookback_days > 0:
        end_ts = ts_list[-1]
        cutoff = end_ts.timestamp() - args.lookback_days * 86400.0
        filtered = [t for t in ts_list if t.timestamp() >= cutoff]
        if len(filtered) >= 3:
            ts_list = filtered

    active: dict[str, Position] = {}
    nav = 1.0
    nav_path = [nav]
    step_rets: list[float] = []
    gross_hist: list[float] = []
    turn_hist: list[float] = []
    actions = 0
    rebals = 0
    regime_counts = {"risk_on": 0, "neutral": 0, "risk_off": 0, "flat": 0}

    # Benchmarks
    bm_modes = ("ew_short_universe", "topn_short_momentum")
    bm_weights = {m: {} for m in bm_modes}
    bm_nav = {m: 1.0 for m in bm_modes}
    bm_nav_path = {m: [1.0] for m in bm_modes}
    bm_step_rets = {m: [] for m in bm_modes}
    bm_turnover = {m: [] for m in bm_modes}

    for i in range(len(ts_list) - 1):
        ts = ts_list[i]
        nxt = ts_list[i + 1]
        points = build_points(data, ts)
        point_map = {p.symbol: p for p in points}

        do_rebal = (i % max(args.rebalance_steps, 1) == 0)
        target: dict[str, Position] = active

        if do_rebal:
            short_w, long_w, regime = _build_targets(
                data,
                ts,
                points,
                args.n_shorts,
                args.n_longs,
                args.short_min_score,
                args.long_min_score,
            )
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
            merged = {**short_w, **long_w}
            target = {}
            for s, w in merged.items():
                p = point_map.get(s)
                if not p or p.price <= 0:
                    continue
                vol = _vol_est(data, s, ts)
                stop = _clamp(2.0 * vol, 0.08, 0.18)
                take = _clamp(3.0 * vol, 0.12, 0.35)
                side = "long" if w > 0 else "short"
                target[s] = Position(side=side, weight=w, entry_price=p.price, stop_pct=stop, take_pct=take)

            to = _turnover(active, target)
            turn_hist.append(to)
            actions += sum(1 for k in set(active) | set(target) if abs(active.get(k, Position('long', 0.0, 0.0, 0.0, 0.0)).weight - target.get(k, Position('long', 0.0, 0.0, 0.0, 0.0)).weight) > 1e-9)
            cost = to * (args.cost_bps / 10_000.0)
            active = target
            rebals += 1

            # benchmark rebalance
            for m in bm_modes:
                t_w = _benchmark_target(points, m, args.n_shorts)
                to_bm = _turnover_weights(bm_weights[m], t_w)
                bm_turnover[m].append(to_bm)
                bm_weights[m] = t_w
        else:
            cost = 0.0

        px_t = {p.symbol: p.price for p in points}
        px_n = prices_at_next(data, list(active.keys()), nxt)

        pnl = 0.0
        to_drop = []
        for s, pos in active.items():
            p0 = px_t.get(s)
            p1 = px_n.get(s)
            if p0 is None or p1 is None or p0 <= 0:
                continue

            # side-aware simple return
            raw_r = (p1 - p0) / p0
            side_r = raw_r if pos.side == "long" else -raw_r

            # stop/take relative to entry
            cum_raw = (p1 - pos.entry_price) / pos.entry_price
            cum_side = cum_raw if pos.side == "long" else -cum_raw
            if cum_side <= -pos.stop_pct:
                # stop hit: realize exactly -stop on remaining lifecycle
                effective = -pos.stop_pct
                to_drop.append(s)
            elif cum_side >= pos.take_pct:
                effective = pos.take_pct
                to_drop.append(s)
            else:
                effective = side_r

            pnl += abs(pos.weight) * effective

            # funding contribution (8h rate prorated by elapsed hours)
            p = point_map.get(s)
            if p and p.funding_8h is not None:
                dt_h = max((nxt - ts).total_seconds() / 3600.0, 0.0)
                periods = dt_h / 8.0
                if pos.side == "short":
                    pnl += abs(pos.weight) * p.funding_8h * periods
                else:
                    pnl -= abs(pos.weight) * p.funding_8h * periods

        for s in to_drop:
            active.pop(s, None)

        ret = pnl - cost
        nav *= 1.0 + ret
        nav_path.append(nav)
        step_rets.append(ret)
        gross_hist.append(sum(abs(p.weight) for p in active.values()))

        # benchmark returns for this step
        for m in bm_modes:
            w_map = bm_weights[m]
            bm_cost = 0.0
            if do_rebal:
                bm_cost = _turnover_weights({}, {})  # placeholder for type stability
                bm_cost = (bm_turnover[m][-1] if bm_turnover[m] else 0.0) * (args.cost_bps / 10_000.0)

            bm_pnl = 0.0
            for s, w in w_map.items():
                p0 = px_t.get(s)
                p1 = px_n.get(s)
                if p0 is None or p1 is None or p0 <= 0:
                    continue
                raw_r = (p1 - p0) / p0
                bm_pnl += w * raw_r
            bm_ret = bm_pnl - bm_cost
            bm_nav[m] *= 1.0 + bm_ret
            bm_step_rets[m].append(bm_ret)
            bm_nav_path[m].append(bm_nav[m])

    total_days = (ts_list[-1] - ts_list[0]).total_seconds() / 86400
    sharpe = _sharpe(step_rets, total_days)

    benchmarks = {}
    for m in bm_modes:
        benchmarks[m] = {
            "final_nav": round(bm_nav[m], 6),
            "total_return": round(bm_nav[m] - 1.0, 6),
            "cagr": round(_cagr(bm_nav[m], total_days), 6),
            "max_drawdown": round(_max_drawdown(bm_nav_path[m]), 6),
            "sharpe": round(_sharpe(bm_step_rets[m], total_days), 6),
            "avg_turnover": round(mean(bm_turnover[m]), 6) if bm_turnover[m] else 0.0,
        }

    report = {
        "period": {
            "start": ts_list[0].isoformat(),
            "end": ts_list[-1].isoformat(),
            "days": round(total_days, 4),
            "steps": len(step_rets),
        },
        "config": {
            "cost_bps": args.cost_bps,
            "rebalance_steps": args.rebalance_steps,
            "n_shorts": args.n_shorts,
            "n_longs": args.n_longs,
            "short_min_score": args.short_min_score,
            "long_min_score": args.long_min_score,
        },
        "performance": {
            "final_nav": round(nav, 6),
            "total_return": round(nav - 1.0, 6),
            "cagr": round(_cagr(nav, total_days), 6),
            "max_drawdown": round(_max_drawdown(nav_path), 6),
            "sharpe": round(sharpe, 6),
        },
        "benchmarks": benchmarks,
        "activity": {
            "avg_gross": round(mean(gross_hist), 6) if gross_hist else 0.0,
            "avg_turnover": round(mean(turn_hist), 6) if turn_hist else 0.0,
            "rebalance_count": rebals,
            "symbol_weight_changes": actions,
            "regime_counts": regime_counts,
        },
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
