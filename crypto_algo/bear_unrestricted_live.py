from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .bear_unrestricted_backtest import _build_daily, _eligible, _regime, _target


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one live signal step for bear_unrestricted_v1")
    p.add_argument("--data-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/binance_unrestricted_365d.json"))
    p.add_argument("--memo-path", type=Path, default=Path("/Users/mini/crypto_algo/state_live/unrestricted_latest_action_memo.txt"))
    p.add_argument("--state-json", type=Path, default=Path("/Users/mini/crypto_algo/state_live/unrestricted_live_state.json"))
    p.add_argument("--n-shorts-min", type=int, default=4)
    p.add_argument("--n-shorts-max", type=int, default=10)
    p.add_argument("--min-history-bars", type=int, default=120)
    p.add_argument("--min-dollar-volume", type=float, default=1_000_000.0)
    p.add_argument("--score-threshold", type=float, default=0.15)
    p.add_argument("--spread-threshold", type=float, default=0.25)
    return p.parse_args()


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"weights": {}, "entry_refs": {}, "last_run_utc": None}
    raw = path.read_text().strip()
    if not raw:
        return {"weights": {}, "entry_refs": {}, "last_run_utc": None}
    return json.loads(raw)


def _fmt_w(x: float) -> str:
    return f"{x:+.2%}"


def _fmt_px(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{float(x):.6f}"


def main() -> int:
    args = parse_args()
    payload = json.loads(args.data_json.read_text())
    days, px, funding = _build_daily(payload)
    if not days:
        raise SystemExit("No data in dataset")

    idx = len(days) - 1
    day = days[idx]
    close_ref = {s: float(b["close"]) for s, m in px.items() if (b := m.get(day)) is not None}

    eligible = _eligible(idx, days, px, args.min_history_bars, args.min_dollar_volume)
    regime, on = _regime(idx, days, eligible, px)

    if on:
        target_pos, spread, n_target = _target(
            idx,
            days,
            eligible,
            px,
            funding,
            regime,
            args.n_shorts_min,
            args.n_shorts_max,
            args.score_threshold,
            args.spread_threshold,
        )
    else:
        target_pos, spread, n_target = {}, 0.0, args.n_shorts_min

    state = _load_state(args.state_json)
    prev_w = state.get("weights", {}) or {}
    prev_entry = state.get("entry_refs", {}) or {}
    new_w = {s: p.weight for s, p in target_pos.items()}
    new_entry = {s: float(p.entry) for s, p in target_pos.items()}

    prev_syms = set(prev_w)
    new_syms = set(new_w)
    opens = sorted(new_syms - prev_syms)
    closes = sorted(prev_syms - new_syms)
    adjusts = sorted(s for s in (prev_syms & new_syms) if abs(float(prev_w[s]) - float(new_w[s])) > 1e-9)
    holds = sorted(s for s in (prev_syms & new_syms) if abs(float(prev_w[s]) - float(new_w[s])) <= 1e-9)

    now = datetime.now(timezone.utc).isoformat()
    lines = []
    lines.append("=" * 64)
    lines.append("BEAR_UNRESTRICTED_V1 ACTION MEMO")
    lines.append(f"run_utc={now}")
    lines.append(f"data_day_utc={datetime.fromtimestamp(days[idx] / 1000, tz=timezone.utc).isoformat()}")
    lines.append(f"regime={regime} active={on}")
    lines.append(f"eligible={len(eligible)} spread={spread:.3f} n_target={n_target}")
    lines.append("=" * 64)
    lines.append("ACTION NOW")

    if not opens and not closes and not adjusts:
        lines.append("  No changes.")
    else:
        if closes:
            lines.append("  CLOSE")
            for s in closes:
                lines.append(
                    f"    {s:<12} prev={_fmt_w(float(prev_w[s]))} entry_ref={_fmt_px(prev_entry.get(s))} exit_ref={_fmt_px(close_ref.get(s))}"
                )
        if opens:
            lines.append("  OPEN")
            for s in opens:
                pos = target_pos[s]
                lines.append(
                    f"    {s:<12} w={_fmt_w(pos.weight)} entry_ref={_fmt_px(float(pos.entry))} stop={pos.stop_pct:.1%} take={pos.take_pct:.1%}"
                )
        if adjusts:
            lines.append("  ADJUST")
            for s in adjusts:
                pos = target_pos[s]
                tag = "ADD" if abs(float(pos.weight)) > abs(float(prev_w[s])) else "REDUCE"
                lines.append(
                    f"    {s:<12} {_fmt_w(float(prev_w[s]))} -> {_fmt_w(pos.weight)} {tag}_ref={_fmt_px(close_ref.get(s))} stop={pos.stop_pct:.1%} take={pos.take_pct:.1%}"
                )

    lines.append("HOLD")
    if not holds:
        lines.append("  None")
    else:
        for s in holds:
            lines.append(f"  {s:<12} w={_fmt_w(float(new_w[s]))}")

    lines.append("")
    lines.append("TARGET PORTFOLIO")
    if not new_w:
        lines.append("  Flat")
    else:
        gross = sum(abs(float(v)) for v in new_w.values())
        lines.append(f"  gross_short={gross:.2%}")
        for s in sorted(new_w.keys(), key=lambda k: float(new_w[k])):
            lines.append(f"  {s:<12} {_fmt_w(float(new_w[s]))}")

    memo = "\n".join(lines) + "\n"
    args.memo_path.parent.mkdir(parents=True, exist_ok=True)
    args.memo_path.write_text(memo)

    archive = args.memo_path.parent / "unrestricted_memos"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (archive / f"unrestricted_memo_{stamp}.txt").write_text(memo)

    new_state = {
        "weights": new_w,
        "entry_refs": new_entry,
        "last_run_utc": now,
        "regime": regime,
        "spread": spread,
        "n_target": n_target,
        "eligible_count": len(eligible),
    }
    args.state_json.parent.mkdir(parents=True, exist_ok=True)
    args.state_json.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n")

    print(memo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
