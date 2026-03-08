from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .long_sleeve_candidates import build_long_sleeve


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Record long sleeve scenarios for top50/top100/top200")
    p.add_argument("--data-json", type=Path, required=True)
    p.add_argument("--state-dir", type=Path, default=Path("/Users/mini/crypto_algo/state_live"))
    p.add_argument("--n-longs", type=int, default=10)
    p.add_argument("--gross-long", type=float, default=0.85)
    p.add_argument("--min-history-bars", type=int, default=120)
    p.add_argument("--min-dollar-volume", type=float, default=1_000_000.0)
    p.add_argument("--score-threshold", type=float, default=0.15)
    return p.parse_args()


def _top3(picks: list[dict]) -> str:
    arr = picks[:3]
    return "|".join(f"{x['symbol']}:{x['weight']:.4f}" for x in arr)


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    args.state_dir.mkdir(parents=True, exist_ok=True)

    scenario_out = {}
    for k in (50, 100, 200):
        out = build_long_sleeve(
            payload=payload,
            top_k=k,
            n_longs=args.n_longs,
            gross_long=args.gross_long,
            min_history_bars=args.min_history_bars,
            min_dollar_volume=args.min_dollar_volume,
            score_threshold=args.score_threshold,
        )
        p = args.state_dir / f"long_sleeve_top{k}_latest.json"
        p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
        scenario_out[k] = out

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = args.state_dir / "long_sleeve_scenarios_log.csv"
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(
                [
                    "run_utc",
                    "day_utc",
                    "top_k",
                    "eligible_count",
                    "long_universe_count",
                    "n_picks",
                    "top3",
                ]
            )
        for k in (50, 100, 200):
            o = scenario_out[k]
            picks = o.get("picks", [])
            w.writerow(
                [
                    ts,
                    o.get("asof_utc", "")[:10],
                    k,
                    o.get("universe", {}).get("eligible_count", 0),
                    o.get("universe", {}).get("long_universe_count", 0),
                    len(picks),
                    _top3(picks),
                ]
            )

    print(
        json.dumps(
            {
                "run_utc": ts,
                "outputs": [str(args.state_dir / f"long_sleeve_top{k}_latest.json") for k in (50, 100, 200)],
                "csv": str(csv_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
