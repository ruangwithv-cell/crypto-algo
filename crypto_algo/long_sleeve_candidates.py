from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .bear_unrestricted_backtest import _build_daily, _closes, _eligible, _ret, _vol, _zmap


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build long-sleeve candidates from top-K liquid universe")
    p.add_argument("--data-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/binance_unrestricted_365d.json"))
    p.add_argument("--top-k", type=int, default=200, help="Top-K eligible symbols by recent median dollar volume")
    p.add_argument("--n-longs", type=int, default=10)
    p.add_argument("--gross-long", type=float, default=0.85)
    p.add_argument("--min-history-bars", type=int, default=120)
    p.add_argument("--min-dollar-volume", type=float, default=1_000_000.0)
    p.add_argument("--score-threshold", type=float, default=0.15)
    p.add_argument("--kelly-fraction", type=float, default=0.5)
    p.add_argument("--kelly-max-scale", type=float, default=1.5)
    p.add_argument("--output-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/long_sleeve_top200_latest.json"))
    return p.parse_args()


def _bars(px_sym: dict[int, dict], days: list[int], idx: int, n: int) -> list[dict]:
    out = []
    for j in range(max(0, idx - n + 1), idx + 1):
        b = px_sym.get(days[j])
        if b:
            out.append(b)
    return out


def build_long_sleeve(
    payload: dict,
    top_k: int,
    n_longs: int,
    gross_long: float,
    min_history_bars: int,
    min_dollar_volume: float,
    score_threshold: float,
    kelly_fraction: float = 0.5,
    kelly_max_scale: float = 1.5,
) -> dict:
    days, px, funding = _build_daily(payload)
    if not days:
        raise SystemExit("No data")
    idx = len(days) - 1

    eligible = _eligible(idx, days, px, min_history_bars, min_dollar_volume)
    if not eligible:
        raise SystemExit("No eligible symbols")

    liq_rank = []
    for s in eligible:
        bars20 = _bars(px[s], days, idx, 20)
        dv = [float(b["close"]) * float(b["volume"]) for b in bars20]
        med_dv = sorted(dv)[len(dv) // 2] if dv else 0.0
        liq_rank.append((s, med_dv))
    liq_rank.sort(key=lambda x: x[1], reverse=True)
    long_universe = [s for s, _ in liq_rank[: max(top_k, 1)]]

    market_r30 = []
    for s in long_universe:
        c = _closes(px[s], days, idx, 150)
        r30 = _ret(c, 30)
        if r30 is not None:
            market_r30.append(r30)
    m30 = sum(market_r30) / len(market_r30) if market_r30 else 0.0

    trend = {}
    rel = {}
    carry = {}
    breakout = {}
    squeeze_pen = {}
    vol = {}
    liq = {}
    day_key = (days[idx] // 86_400_000) * 86_400_000

    for s in long_universe:
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
        # avoid catching sharp collapses in a bear tape
        if r7 < -0.20:
            continue

        low90 = min(c[-90:])
        dist_low = (c[-1] - low90) / low90 if low90 > 0 else 0.0
        bars20 = _bars(px[s], days, idx, 20)
        dv = [float(b["close"]) * float(b["volume"]) for b in bars20]
        med_dv = sorted(dv)[len(dv) // 2] if dv else 0.0

        trend[s] = 0.35 * r120 + 0.30 * r90 + 0.20 * r60 + 0.10 * r30 + 0.05 * r14
        rel[s] = r30 - m30
        carry[s] = -funding.get(s, {}).get(day_key, 0.0)  # prefer cheaper longs
        breakout[s] = dist_low
        squeeze_pen[s] = max(r3, 0.0) + 0.5 * max(r7, 0.0)  # avoid euphoric spikes
        vol[s] = _vol(c, 20)
        liq[s] = math.log(max(med_dv, 1.0))

    if not trend:
        raise SystemExit("No scored symbols")

    zt = _zmap(trend)
    zr = _zmap(rel)
    zc = _zmap(carry)
    zb = _zmap(breakout)
    zs = _zmap(squeeze_pen)
    zl = _zmap(liq)

    score = {}
    for s in trend:
        score[s] = 0.35 * zt[s] + 0.20 * zr[s] + 0.15 * zc[s] + 0.20 * zb[s] + 0.10 * zl[s] - 0.20 * zs[s]

    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)
    picked = [s for s, sc in ranked if sc >= score_threshold][: max(n_longs, 1)]
    if not picked:
        picked = [s for s, _ in ranked[: max(n_longs, 1)]]

    inv = {s: 1.0 / max(vol[s], 1e-6) for s in picked}
    z = sum(inv.values())
    kf = max(0.0, min(float(kelly_fraction), 1.0))
    km = max(0.0, float(kelly_max_scale))
    raw = {}
    for s in picked:
        base_abs = gross_long * inv[s] / z
        edge = max(float(score[s]) - float(score_threshold), 0.0)
        scale = 1.0 + km * kf * min(edge, 1.0)
        raw[s] = base_abs * scale
    raw_sum = sum(raw.values())
    if raw_sum <= 0:
        weights = {s: gross_long / len(picked) for s in picked}
    else:
        weights = {s: gross_long * raw[s] / raw_sum for s in picked}

    out = {
        "asof_utc": __import__("datetime").datetime.fromtimestamp(days[idx] / 1000, tz=__import__("datetime").timezone.utc).isoformat(),
        "config": {
            "top_k": top_k,
            "n_longs": n_longs,
            "gross_long": gross_long,
            "min_history_bars": min_history_bars,
            "min_dollar_volume": min_dollar_volume,
            "score_threshold": score_threshold,
            "kelly_fraction": max(0.0, min(float(kelly_fraction), 1.0)),
            "kelly_max_scale": max(0.0, float(kelly_max_scale)),
        },
        "universe": {
            "eligible_count": len(eligible),
            "long_universe_count": len(long_universe),
        },
        "picks": [
            {
                "symbol": s,
                "weight": weights[s],
                "score": score[s],
                "vol20": vol[s],
            }
            for s in sorted(picked, key=lambda x: weights[x], reverse=True)
        ],
    }
    return out


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    out = build_long_sleeve(
        payload=payload,
        top_k=args.top_k,
        n_longs=args.n_longs,
        gross_long=args.gross_long,
        min_history_bars=args.min_history_bars,
        min_dollar_volume=args.min_dollar_volume,
        score_threshold=args.score_threshold,
        kelly_fraction=args.kelly_fraction,
        kelly_max_scale=args.kelly_max_scale,
    )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
