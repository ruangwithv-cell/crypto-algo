from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .bear_v2_meta_backtest import _build_daily, _eligible, _regime, _meta_target


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one shadow signal step for bear_v2_meta")
    p.add_argument("--data-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/binance_extended_365d.json"))
    p.add_argument("--state-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/shadow_state.json"))
    p.add_argument("--memo-path", type=Path, default=Path("/Users/mini/crypto_algo/state_live/shadow_latest_action_memo.txt"))
    p.add_argument("--n-shorts-min", type=int, default=3)
    p.add_argument("--n-shorts-max", type=int, default=6)
    p.add_argument("--persistence-runs", type=int, default=1)
    p.add_argument("--spread-threshold", type=float, default=0.25)
    return p.parse_args()


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"weights": {}, "streaks": {}, "last_run_utc": None}
    raw = path.read_text().strip()
    if not raw:
        return {"weights": {}, "streaks": {}, "last_run_utc": None}
    return json.loads(raw)


def _fmt_w(x: float) -> str:
    return f"{x:+.2%}"


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    days, px, funding, symbols_meta = _build_daily(payload)
    if not days:
        raise SystemExit("No data in dataset")

    idx = len(days) - 1
    eligible = _eligible(idx, days, px, symbols_meta)
    regime, on = _regime(idx, days, eligible, px)

    state = _load_state(args.state_json)
    prev_w = state.get("weights", {})
    streaks = state.get("streaks", {})

    if on:
        target_pos, spread, n_target = _meta_target(
            idx,
            days,
            eligible,
            px,
            funding,
            regime,
            args.n_shorts_min,
            args.n_shorts_max,
            args.spread_threshold,
            streaks,
            args.persistence_runs,
        )
    else:
        target_pos, spread, n_target = {}, 0.0, args.n_shorts_min
        for s in list(streaks.keys()):
            streaks[s] = 0

    new_w = {s: p.weight for s, p in target_pos.items()}

    prev_syms = set(prev_w)
    new_syms = set(new_w)

    opens = sorted(new_syms - prev_syms)
    closes = sorted(prev_syms - new_syms)
    adjusts = sorted(s for s in (prev_syms & new_syms) if abs(prev_w[s] - new_w[s]) > 1e-9)
    holds = sorted(s for s in (prev_syms & new_syms) if abs(prev_w[s] - new_w[s]) <= 1e-9)

    now = datetime.now(timezone.utc).isoformat()

    lines = []
    lines.append("=" * 64)
    lines.append("BEAR_V2_META SHADOW ACTION MEMO")
    lines.append(f"run_utc={now}")
    lines.append(f"data_day_utc={datetime.fromtimestamp(days[idx] / 1000, tz=timezone.utc).isoformat()}")
    lines.append(f"regime={regime} active={on}")
    lines.append(f"spread={spread:.3f} n_target={n_target}")
    lines.append("=" * 64)

    lines.append("ACTION NOW (PAPER ONLY)")
    if not opens and not closes and not adjusts:
        lines.append("  No changes.")
    else:
        if closes:
            lines.append("  CLOSE")
            for s in closes:
                lines.append(f"    {s:<10} prev={_fmt_w(prev_w[s])}")
        if opens:
            lines.append("  OPEN")
            for s in opens:
                pos = target_pos[s]
                lines.append(
                    f"    {s:<10} w={_fmt_w(pos.weight)} stop={pos.stop_pct:.1%} take={pos.take_pct:.1%}"
                )
        if adjusts:
            lines.append("  ADJUST")
            for s in adjusts:
                pos = target_pos[s]
                lines.append(
                    f"    {s:<10} { _fmt_w(prev_w[s]) } -> { _fmt_w(pos.weight) } stop={pos.stop_pct:.1%} take={pos.take_pct:.1%}"
                )

    lines.append("HOLD")
    if not holds:
        lines.append("  None")
    else:
        for s in holds:
            lines.append(f"  {s:<10} w={_fmt_w(new_w[s])}")

    lines.append("")
    lines.append("TARGET PORTFOLIO")
    if not new_w:
        lines.append("  Flat")
    else:
        for s in sorted(new_w.keys(), key=lambda k: new_w[k]):
            lines.append(f"  {s:<10} { _fmt_w(new_w[s]) }")

    memo = "\n".join(lines) + "\n"
    args.memo_path.parent.mkdir(parents=True, exist_ok=True)
    args.memo_path.write_text(memo)

    # archive memo
    archive = args.memo_path.parent / "shadow_memos"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (archive / f"shadow_memo_{stamp}.txt").write_text(memo)

    # persist new state
    new_state = {
        "weights": new_w,
        "streaks": streaks,
        "last_run_utc": now,
        "regime": regime,
        "spread": spread,
        "n_target": n_target,
    }
    args.state_json.parent.mkdir(parents=True, exist_ok=True)
    args.state_json.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n")

    print(memo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
