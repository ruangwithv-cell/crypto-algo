from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .adapters_v2 import load_v2_snapshot
from .config import StrategyConfig
from .engine import CryptoAlgoEngine
from .models import EngineState, Instruction


@dataclass
class SideStats:
    runs: int = 0
    entries: int = 0
    exits: int = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare v2 actions vs crypto_algo actions")
    p.add_argument("--v2-runs-dir", type=Path, default=Path("/Users/mini/data/runs"))
    p.add_argument("--whipsaw-window-runs", type=int, default=3)
    p.add_argument("--output-json", type=Path, default=None)
    return p.parse_args()


def _load_v2_files(runs_dir: Path) -> list[Path]:
    files = sorted(runs_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No run files found in {runs_dir}")
    return files


def _extract_old_instructions(path: Path) -> list[Instruction]:
    payload = json.loads(path.read_text())
    instructions: list[Instruction] = []
    for row in payload.get("instructions", []):
        instructions.append(
            Instruction(
                action=str(row.get("action", "")),
                symbol=str(row.get("symbol", "")).upper(),
                reason=str(row.get("reason", "")),
                size_pct_nav=row.get("size_pct_nav"),
            )
        )
    return instructions


def _whipsaw_counts(events: list[tuple[int, str, str]], window: int) -> dict[str, int]:
    # events: (run_idx, symbol, side) where side is ENTRY or EXIT
    quick_entry_exit = 0
    quick_exit_reentry = 0

    by_symbol: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for idx, sym, side in events:
        by_symbol[sym].append((idx, side))

    for seq in by_symbol.values():
        seq.sort(key=lambda x: x[0])
        for i in range(1, len(seq)):
            prev_idx, prev_side = seq[i - 1]
            idx, side = seq[i]
            if idx - prev_idx > window:
                continue
            if prev_side == "ENTRY" and side == "EXIT":
                quick_entry_exit += 1
            elif prev_side == "EXIT" and side == "ENTRY":
                quick_exit_reentry += 1

    return {
        "quick_entry_exit": quick_entry_exit,
        "quick_exit_reentry": quick_exit_reentry,
        "total_whipsaw": quick_entry_exit + quick_exit_reentry,
    }


def _collect_events(run_idx: int, instructions: Iterable[Instruction]) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for inst in instructions:
        if inst.action == "SHORT_ENTRY":
            out.append((run_idx, inst.symbol, "ENTRY"))
        elif inst.action == "SHORT_EXIT":
            out.append((run_idx, inst.symbol, "EXIT"))
    return out


def main() -> int:
    args = parse_args()
    files = _load_v2_files(args.v2_runs_dir)

    cfg = StrategyConfig()
    engine = CryptoAlgoEngine(cfg)
    state = EngineState()

    old_stats = SideStats()
    new_stats = SideStats()
    old_events: list[tuple[int, str, str]] = []
    new_events: list[tuple[int, str, str]] = []

    for idx, path in enumerate(files):
        old_instructions = _extract_old_instructions(path)
        old_stats.runs += 1
        old_stats.entries += sum(1 for i in old_instructions if i.action == "SHORT_ENTRY")
        old_stats.exits += sum(1 for i in old_instructions if i.action == "SHORT_EXIT")
        old_events.extend(_collect_events(idx, old_instructions))

        ts, assets = load_v2_snapshot(path)
        result = engine.run(ts, assets, state)
        new_stats.runs += 1
        new_stats.entries += sum(1 for i in result.instructions if i.action == "SHORT_ENTRY")
        new_stats.exits += sum(1 for i in result.instructions if i.action == "SHORT_EXIT")
        new_events.extend(_collect_events(idx, result.instructions))

    old_whipsaw = _whipsaw_counts(old_events, args.whipsaw_window_runs)
    new_whipsaw = _whipsaw_counts(new_events, args.whipsaw_window_runs)

    report = {
        "runs": len(files),
        "window_runs": args.whipsaw_window_runs,
        "old": {
            "entries": old_stats.entries,
            "exits": old_stats.exits,
            "total_actions": old_stats.entries + old_stats.exits,
            "actions_per_run": round((old_stats.entries + old_stats.exits) / max(old_stats.runs, 1), 4),
            **old_whipsaw,
        },
        "crypto_algo": {
            "entries": new_stats.entries,
            "exits": new_stats.exits,
            "total_actions": new_stats.entries + new_stats.exits,
            "actions_per_run": round((new_stats.entries + new_stats.exits) / max(new_stats.runs, 1), 4),
            **new_whipsaw,
        },
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
