from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev

from .ls_config import LSConfig
from .ls_data import build_points, collect_timestamps, load_state, prices_at_next
from .ls_engine import construct_portfolio


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Long/short factor backtest (market-neutral)")
    p.add_argument("--history-json", type=Path, default=Path("/Users/mini/crypto_short_v2_state/portfolio_state.json"))
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--n-longs", type=int, default=6)
    p.add_argument("--n-shorts", type=int, default=6)
    p.add_argument("--min-score", type=float, default=0.10)
    p.add_argument("--output-json", type=Path, default=None)
    return p.parse_args()


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


def _turnover(prev_w: dict[str, float], new_w: dict[str, float]) -> float:
    keys = set(prev_w) | set(new_w)
    return 0.5 * sum(abs(new_w.get(k, 0.0) - prev_w.get(k, 0.0)) for k in keys)


def main() -> int:
    args = parse_args()
    cfg = LSConfig()
    cfg.n_longs = args.n_longs
    cfg.n_shorts = args.n_shorts
    cfg.rebalance_min_abs_score = args.min_score

    data = load_state(args.history_json)
    ts_list = collect_timestamps(data)
    if len(ts_list) < 3:
        raise SystemExit("Not enough timestamps")

    nav = 1.0
    nav_path = [nav]
    step_rets: list[float] = []
    gross_hist: list[float] = []
    turn_hist: list[float] = []

    prev_weights: dict[str, float] = {}
    trades = 0

    for i in range(len(ts_list) - 1):
        ts = ts_list[i]
        nxt = ts_list[i + 1]

        points = build_points(data, ts)
        weights, signals = construct_portfolio(data, ts, points, cfg)

        to = _turnover(prev_weights, weights)
        cost = to * (args.cost_bps / 10_000.0)

        symbols = list(weights.keys())
        px_t = {p.symbol: p.price for p in points if p.symbol in weights}
        px_n = prices_at_next(data, symbols, nxt)

        pnl_price = 0.0
        pnl_funding = 0.0
        funding_map = {p.symbol: p.funding_8h for p in points}
        for s, w in weights.items():
            p0 = px_t.get(s)
            p1 = px_n.get(s)
            if p0 is None or p1 is None or p0 <= 0:
                continue
            r = (p1 - p0) / p0
            pnl_price += w * r
            f = funding_map.get(s)
            if f is not None:
                pnl_funding += -w * f

        ret = pnl_price + pnl_funding - cost
        nav *= 1.0 + ret

        nav_path.append(nav)
        step_rets.append(ret)
        gross_hist.append(sum(abs(w) for w in weights.values()))
        turn_hist.append(to)
        trades += sum(1 for k in set(prev_weights) | set(weights) if abs(prev_weights.get(k, 0.0) - weights.get(k, 0.0)) > 1e-9)
        prev_weights = weights

    total_days = (ts_list[-1] - ts_list[0]).total_seconds() / 86400
    total_return = nav - 1.0
    cagr = (nav ** (365.0 / max(total_days, 1e-9)) - 1.0) if total_days > 0 else 0.0
    mdd = _max_drawdown(nav_path)

    avg = mean(step_rets) if step_rets else 0.0
    vol = pstdev(step_rets) if len(step_rets) > 1 else 0.0
    steps_per_day = len(step_rets) / max(total_days, 1e-9)
    sharpe = (avg / vol) * math.sqrt(365.0 * steps_per_day) if vol > 0 else 0.0

    report = {
        "period": {
            "start": ts_list[0].isoformat(),
            "end": ts_list[-1].isoformat(),
            "days": round(total_days, 4),
            "steps": len(step_rets),
        },
        "config": {
            "n_longs": cfg.n_longs,
            "n_shorts": cfg.n_shorts,
            "min_score": cfg.rebalance_min_abs_score,
            "cost_bps": args.cost_bps,
            "gross_exposure": cfg.gross_exposure,
        },
        "performance": {
            "final_nav": round(nav, 6),
            "total_return": round(total_return, 6),
            "cagr": round(cagr, 6),
            "max_drawdown": round(mdd, 6),
            "sharpe": round(sharpe, 6),
        },
        "activity": {
            "avg_gross": round(mean(gross_hist), 6) if gross_hist else 0.0,
            "avg_turnover": round(mean(turn_hist), 6) if turn_hist else 0.0,
            "symbol_weight_changes": trades,
        },
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
