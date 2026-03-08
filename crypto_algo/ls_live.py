from __future__ import annotations

import argparse
from pathlib import Path

from .ls_config import LSConfig
from .ls_data import build_points, collect_timestamps, load_state
from .ls_engine import construct_portfolio


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate current long/short basket proposal")
    p.add_argument("--history-json", type=Path, default=Path("/Users/mini/crypto_short_v2_state/portfolio_state.json"))
    p.add_argument("--n-longs", type=int, default=6)
    p.add_argument("--n-shorts", type=int, default=6)
    p.add_argument("--min-score", type=float, default=0.10)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = LSConfig()
    cfg.n_longs = args.n_longs
    cfg.n_shorts = args.n_shorts
    cfg.rebalance_min_abs_score = args.min_score

    data = load_state(args.history_json)
    ts_list = collect_timestamps(data)
    if not ts_list:
        raise SystemExit("No timestamps found")
    ts = ts_list[-1]

    points = build_points(data, ts)
    weights, signals = construct_portfolio(data, ts, points, cfg)

    longs = sorted([(s, w) for s, w in weights.items() if w > 0], key=lambda x: x[1], reverse=True)
    shorts = sorted([(s, w) for s, w in weights.items() if w < 0], key=lambda x: x[1])

    print("=" * 60)
    print("CRYPTO_ALGO_LS PROPOSAL")
    print(f"timestamp={ts.isoformat()}")
    print(f"gross={sum(abs(w) for w in weights.values()):.2%} net={sum(weights.values()):+.2%}")
    print("=" * 60)
    print("LONGS")
    if not longs:
        print("  none")
    for s, w in longs:
        print(f"  LONG  {s:<10} {w:+.2%}")
    print("SHORTS")
    if not shorts:
        print("  none")
    for s, w in shorts:
        print(f"  SHORT {s:<10} {w:+.2%}")

    print("TOP SIGNALS")
    for r in signals[:5]:
        print(f"  {r.symbol:<10} score={r.score:+.3f} mom={r.z_mom:+.2f} carry={r.z_carry:+.2f} oi={r.z_oi_align:+.2f}")
    print("BOTTOM SIGNALS")
    for r in signals[-5:]:
        print(f"  {r.symbol:<10} score={r.score:+.3f} mom={r.z_mom:+.2f} carry={r.z_carry:+.2f} oi={r.z_oi_align:+.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
