from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .adapters_v2 import latest_v2_run_path, load_v2_snapshot
from .config import StrategyConfig
from .engine import CryptoAlgoEngine
from .io_utils import build_action_memo, load_snapshot, write_run_snapshot, write_text
from .state_store import StateStore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="crypto_algo short engine")
    p.add_argument("--input", type=Path, default=None, help="Path to native market snapshot JSON")
    p.add_argument("--input-v2", type=Path, default=None, help="Path to crypto_short_v2 run JSON")
    p.add_argument(
        "--input-v2-latest-dir",
        type=Path,
        default=None,
        help="Use latest crypto_short_v2 run JSON from this directory",
    )
    p.add_argument("--state-dir", type=Path, default=Path("state"), help="State directory")
    p.add_argument("--write-memo", type=Path, default=None, help="Optional memo output path")
    p.add_argument("--write-run", type=Path, default=None, help="Optional run snapshot output path")
    return p.parse_args()


def _default_run_path(state_dir: Path, ts: datetime) -> Path:
    return state_dir / "runs" / f"run_{ts.strftime('%Y%m%dT%H%M%S')}.json"


def _positions_payload(state) -> dict[str, dict]:
    return {
        symbol: {
            "size_pct_nav": pos.size_pct_nav,
            "entry_price": pos.entry_price,
            "last_price": pos.last_price,
            "opened_at": pos.opened_at.isoformat(),
        }
        for symbol, pos in state.positions.items()
    }


def main() -> int:
    args = parse_args()
    config = StrategyConfig()
    engine = CryptoAlgoEngine(config)

    state_path = args.state_dir / "portfolio_state.json"
    store = StateStore(state_path)
    state = store.load()

    ts, assets = _resolve_input(args)
    result = engine.run(ts, assets, state)
    store.save(state)

    run_path = args.write_run or _default_run_path(args.state_dir, ts)
    write_run_snapshot(run_path, result)

    memo_path = args.write_memo
    if memo_path is not None:
        memo = build_action_memo(result, _positions_payload(state))
        write_text(memo_path, memo)
        print(memo)

    print(f"timestamp={result.timestamp.isoformat()}")
    print(f"instructions={len(result.instructions)}")
    print(f"exposure={result.exposure:.2%}")
    print(f"run_snapshot={run_path}")
    return 0


def _resolve_input(args: argparse.Namespace):
    if args.input:
        return load_snapshot(args.input)
    if args.input_v2:
        return load_v2_snapshot(args.input_v2)
    if args.input_v2_latest_dir:
        latest = latest_v2_run_path(args.input_v2_latest_dir)
        return load_v2_snapshot(latest)
    raise SystemExit("Provide one of --input, --input-v2, or --input-v2-latest-dir")


if __name__ == "__main__":
    raise SystemExit(main())
