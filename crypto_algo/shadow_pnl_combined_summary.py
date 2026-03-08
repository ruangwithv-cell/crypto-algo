from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build combined short+long Telegram-friendly shadow PnL summary text")
    p.add_argument("--short-csv", type=Path, required=True)
    p.add_argument("--short-state-json", type=Path, default=None)
    p.add_argument("--long-csv", type=Path, required=True)
    p.add_argument("--long-state-json", type=Path, default=None)
    p.add_argument("--out-path", type=Path, required=True)
    return p.parse_args()


def _latest_row(path: Path) -> dict | None:
    if not path.exists():
        return None
    rows = []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    if not rows:
        return None
    return rows[-1]


def _load_state(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text())


def main() -> int:
    args = parse_args()

    s = _latest_row(args.short_csv)
    l = _latest_row(args.long_csv)
    s_state = _load_state(args.short_state_json)
    l_state = _load_state(args.long_state_json)

    if s is None and l is None:
        msg = ["SHADOW PNL UPDATE", "status=initialized_no_pnl_row_yet"]
        args.out_path.parent.mkdir(parents=True, exist_ok=True)
        args.out_path.write_text("\n".join(msg) + "\n")
        print(args.out_path)
        return 0

    day = ""
    if s is not None:
        day = s.get("day_utc", "")
    if l is not None and l.get("day_utc"):
        day = l.get("day_utc", day)

    sr = float(s["daily_return"]) if s is not None else 0.0
    lr = float(l["daily_return"]) if l is not None else 0.0
    cr = sr + lr

    s_nav = float(s_state.get("nav", 1.0)) if s_state is not None else None
    l_nav = float(l_state.get("nav", 1.0)) if l_state is not None else None

    msg = ["SHADOW PNL UPDATE (SHORT+LONG)"]
    if day:
        msg.append(f"day_utc={day}")
    msg.append(f"short_daily_return={sr:+.2%}")
    msg.append(f"long_daily_return={lr:+.2%}")
    msg.append(f"combined_daily_return={cr:+.2%}")

    if s_nav is not None:
        msg.append(f"short_nav={s_nav:.4f}")
    if l_nav is not None:
        msg.append(f"long_nav={l_nav:.4f}")
    if s_nav is not None and l_nav is not None:
        msg.append(f"combined_nav_index={(s_nav + l_nav - 1.0):.4f}")

    if l is None and l_state is not None:
        msg.append("note=long_tracker_reset_top100_initialized_waiting_first_daily_mark")

    if s is not None:
        n_prev = int(float(s["n_positions_prev"]))
        n_used = int(float(s["symbols_used"]))
        msg.append(f"short_positions_prev={n_prev} gross_prev={float(s['gross_prev']):.2%} symbols_used={n_used}")
        if n_used < n_prev:
            msg.append(f"warning=short_symbols_missing_in_mark_to_market count={n_prev - n_used}")

    if l is not None:
        n_prev_l = int(float(l["n_positions_prev"]))
        n_used_l = int(float(l["symbols_used"]))
        msg.append(f"long_positions_prev={n_prev_l} gross_prev={float(l['gross_prev']):.2%} symbols_used={n_used_l}")
        if n_used_l < n_prev_l:
            msg.append(f"warning=long_symbols_missing_in_mark_to_market count={n_prev_l - n_used_l}")

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    args.out_path.write_text("\n".join(msg) + "\n")
    print(args.out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
