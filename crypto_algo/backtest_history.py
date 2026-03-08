from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

from .config import StrategyConfig
from .engine import CryptoAlgoEngine
from .models import AssetInput, EngineState


@dataclass
class StepResult:
    ts: datetime
    nav: float
    period_return: float
    exposure: float
    actions: int


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replay backtest from merged_portfolio_state history")
    p.add_argument(
        "--history-json",
        type=Path,
        default=Path("/Users/mini/crypto_short_v2/merged_portfolio_state.json"),
    )
    p.add_argument("--cost-bps-per-action", type=float, default=5.0)
    p.add_argument("--assume-volume-usd", type=float, default=75_000_000.0)
    p.add_argument("--entry-score-min", type=float, default=None)
    p.add_argument("--exit-score-max", type=float, default=None)
    p.add_argument("--entry-confirmation-runs", type=int, default=None)
    p.add_argument("--exit-confirmation-runs", type=int, default=None)
    p.add_argument("--max-rank", type=int, default=None)
    p.add_argument("--output-json", type=Path, default=None)
    return p.parse_args()


def _parse_ts(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _collect_timestamps(data: dict) -> list[datetime]:
    out: set[datetime] = set()
    for bucket in ("rank_history", "funding_history", "open_interest_history"):
        for samples in data.get(bucket, {}).values():
            for x in samples:
                out.add(_parse_ts(x["timestamp"]))
    return sorted(out)


def _last_before(samples: list[dict], ts: datetime, value_key: str):
    val = None
    for s in samples:
        st = _parse_ts(s["timestamp"])
        if st <= ts:
            val = s[value_key]
        else:
            break
    return val


def _price_return(price_hist: list[dict], ts: datetime, lookback_days: int):
    now = _last_before(price_hist, ts, "price")
    if now is None or now <= 0:
        return None
    target = ts.timestamp() - lookback_days * 86400
    prev = None
    prev_ts = None
    for s in price_hist:
        st = _parse_ts(s["timestamp"])
        if st.timestamp() <= target:
            prev = s["price"]
            prev_ts = st
        else:
            break
    if prev is None or prev <= 0 or prev_ts is None:
        return None
    return (now - prev) / prev


def _build_assets(data: dict, ts: datetime, cfg: StrategyConfig, assume_volume: float) -> list[AssetInput]:
    rank_h = data.get("rank_history", {})
    fund_h = data.get("funding_history", {})
    oi_h = data.get("open_interest_history", {})
    price_h = data.get("price_history", {})

    symbols = set(rank_h.keys()) | set(fund_h.keys()) | set(oi_h.keys()) | set(price_h.keys())
    assets: list[AssetInput] = []

    for sym in sorted(symbols):
        ranks = rank_h.get(sym, [])
        prices = price_h.get(sym, [])
        if not ranks or not prices:
            continue

        rank = _last_before(ranks, ts, "rank")
        price = _last_before(prices, ts, "price")
        if rank is None or price is None:
            continue

        funding = _last_before(fund_h.get(sym, []), ts, "rate")
        oi = _last_before(oi_h.get(sym, []), ts, "open_interest_usd")

        ret_1d = _price_return(prices, ts, 1)
        ret_7d = _price_return(prices, ts, 7)
        ret_30d = _price_return(prices, ts, 30)
        ret_90d = _price_return(prices, ts, 90)

        assets.append(
            AssetInput(
                symbol=sym,
                rank=int(rank),
                price_usd=float(price),
                funding_rate_8h=float(funding) if funding is not None else None,
                open_interest_usd=float(oi) if oi is not None else None,
                volume_usd=assume_volume,
                ret_1d=ret_1d,
                ret_7d=ret_7d,
                ret_30d=ret_30d,
                ret_90d=ret_90d,
            )
        )

    return assets


def _max_drawdown(nav_series: list[float]) -> float:
    peak = nav_series[0]
    mdd = 0.0
    for x in nav_series:
        if x > peak:
            peak = x
        dd = (x - peak) / peak
        if dd < mdd:
            mdd = dd
    return mdd


def main() -> int:
    args = parse_args()
    data = _load(args.history_json)
    ts_list = _collect_timestamps(data)
    if len(ts_list) < 2:
        raise SystemExit("Not enough timestamps for replay")

    cfg = StrategyConfig()
    if args.entry_score_min is not None:
        cfg.signal.entry_score_min = float(args.entry_score_min)
    if args.exit_score_max is not None:
        cfg.signal.exit_score_max = float(args.exit_score_max)
    if args.entry_confirmation_runs is not None:
        cfg.decision.entry_confirmation_runs = int(args.entry_confirmation_runs)
    if args.exit_confirmation_runs is not None:
        cfg.decision.exit_confirmation_runs = int(args.exit_confirmation_runs)
    if args.max_rank is not None:
        cfg.universe.max_rank = int(args.max_rank)
    engine = CryptoAlgoEngine(cfg)
    state = EngineState()

    nav = 1.0
    nav_series = [nav]
    step_returns: list[float] = []
    steps: list[StepResult] = []

    for i in range(len(ts_list) - 1):
        ts = ts_list[i]
        nxt = ts_list[i + 1]
        assets_t = _build_assets(data, ts, cfg, args.assume_volume_usd)
        if not assets_t:
            continue

        result = engine.run(ts, assets_t, state)

        # Trading cost on actions at this step
        actions = len(result.instructions)
        cost = (args.cost_bps_per_action / 10_000.0) * actions

        # Period PnL for positions held after decisions
        price_map_t = {a.symbol: a.price_usd for a in assets_t}
        assets_n = _build_assets(data, nxt, cfg, args.assume_volume_usd)
        price_map_n = {a.symbol: a.price_usd for a in assets_n}

        gross = 0.0
        for pos in state.positions.values():
            p0 = price_map_t.get(pos.symbol)
            p1 = price_map_n.get(pos.symbol)
            if p0 is None or p1 is None or p0 <= 0:
                continue
            short_ret = (p0 - p1) / p0
            gross += pos.size_pct_nav * short_ret

        period_ret = gross - cost
        nav *= (1.0 + period_ret)
        nav_series.append(nav)
        step_returns.append(period_ret)
        steps.append(
            StepResult(
                ts=ts,
                nav=nav,
                period_return=period_ret,
                exposure=result.exposure,
                actions=actions,
            )
        )

    total_days = (ts_list[-1] - ts_list[0]).total_seconds() / 86400
    total_return = nav - 1.0
    cagr = (nav ** (365.0 / max(total_days, 1e-9)) - 1.0) if total_days > 0 else 0.0
    mdd = _max_drawdown(nav_series)

    avg = mean(step_returns) if step_returns else 0.0
    vol = pstdev(step_returns) if len(step_returns) > 1 else 0.0
    # annualization by average observed steps/day
    steps_per_day = len(step_returns) / max(total_days, 1e-9)
    sharpe = (avg / vol) * math.sqrt(365.0 * steps_per_day) if vol > 0 else 0.0

    avg_exposure = mean([s.exposure for s in steps]) if steps else 0.0
    actions_total = sum(s.actions for s in steps)

    report = {
        "period": {
            "start": ts_list[0].isoformat(),
            "end": ts_list[-1].isoformat(),
            "days": round(total_days, 4),
            "steps": len(step_returns),
        },
        "performance": {
            "final_nav": round(nav, 6),
            "total_return": round(total_return, 6),
            "cagr": round(cagr, 6),
            "max_drawdown": round(mdd, 6),
            "sharpe": round(sharpe, 6),
        },
        "activity": {
            "actions_total": actions_total,
            "actions_per_step": round(actions_total / max(len(step_returns), 1), 6),
            "avg_exposure": round(avg_exposure, 6),
        },
        "assumptions": {
            "volume_usd_constant": args.assume_volume_usd,
            "cost_bps_per_action": args.cost_bps_per_action,
            "entry_score_min": cfg.signal.entry_score_min,
            "exit_score_max": cfg.signal.exit_score_max,
            "entry_confirmation_runs": cfg.decision.entry_confirmation_runs,
            "exit_confirmation_runs": cfg.decision.exit_confirmation_runs,
            "max_rank": cfg.universe.max_rank,
            "note": "Historical replay uses merged state history; treat as preliminary due survivorship and synthetic volume assumption.",
        },
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
