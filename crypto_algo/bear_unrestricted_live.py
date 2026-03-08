from __future__ import annotations

import argparse
import csv
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
    p.add_argument("--kelly-fraction", type=float, default=0.5)
    p.add_argument("--kelly-max-scale", type=float, default=1.5)
    p.add_argument("--nav-usd", type=float, default=20_000.0)
    p.add_argument("--shadow-csv", type=Path, default=None)
    p.add_argument("--shadow-state-json", type=Path, default=None)
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


def _fmt_usd(weight: float, nav_usd: float) -> str:
    return f"{weight * nav_usd:+.2f}"


def _fmt_qty(weight: float, nav_usd: float, px: float | None) -> str:
    if px is None or px <= 0:
        return "n/a"
    return f"{abs(weight * nav_usd) / px:.4f}"


def _load_latest_shadow(csv_path: Path | None, state_path: Path | None) -> tuple[str | None, float | None, float | None]:
    day = None
    day_ret = None
    nav = None
    if csv_path is not None and csv_path.exists():
        with csv_path.open() as f:
            rows = list(csv.DictReader(f))
        if rows:
            row = rows[-1]
            day = row.get("day_utc")
            v = row.get("daily_return")
            if v not in (None, ""):
                day_ret = float(v)
    if state_path is not None and state_path.exists():
        st = json.loads(state_path.read_text())
        nav = float(st.get("nav", 1.0))
    return day, day_ret, nav


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
            args.kelly_fraction,
            args.kelly_max_scale,
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
    lines.append(f"nav_reference_usd={args.nav_usd:.2f}")
    lines.append(f"kelly_fraction={max(0.0, min(args.kelly_fraction, 1.0)):.2f} kelly_max_scale={max(args.kelly_max_scale, 0.0):.2f}")
    shadow_day, shadow_ret, shadow_nav = _load_latest_shadow(args.shadow_csv, args.shadow_state_json)
    if shadow_ret is not None:
        tag = f"[{shadow_day}] " if shadow_day else ""
        lines.append(f"shadow_day_return={tag}{shadow_ret:+.2%}")
    if shadow_nav is not None:
        lines.append(f"shadow_nav={shadow_nav:.6f} shadow_pnl_usd={(shadow_nav - 1.0) * args.nav_usd:+.2f}")
    lines.append("=" * 64)
    lines.append("ACTION NOW")

    if not opens and not closes and not adjusts:
        lines.append("  No changes.")
    else:
        if closes:
            lines.append("  CLOSE")
            for s in closes:
                pw = float(prev_w[s])
                exit_px = close_ref.get(s)
                lines.append(
                    f"    {s:<12} prev={_fmt_w(pw)} usd={_fmt_usd(pw, args.nav_usd)} qty_est={_fmt_qty(pw, args.nav_usd, exit_px)} entry_ref={_fmt_px(prev_entry.get(s))} exit_ref={_fmt_px(exit_px)}"
                )
        if opens:
            lines.append("  OPEN")
            for s in opens:
                pos = target_pos[s]
                w = float(pos.weight)
                entry = float(pos.entry)
                lines.append(
                    f"    {s:<12} w={_fmt_w(w)} usd={_fmt_usd(w, args.nav_usd)} qty_est={_fmt_qty(w, args.nav_usd, entry)} entry_ref={_fmt_px(entry)} stop={pos.stop_pct:.1%} take={pos.take_pct:.1%}"
                )
        if adjusts:
            lines.append("  ADJUST")
            for s in adjusts:
                pos = target_pos[s]
                pw = float(prev_w[s])
                nw = float(pos.weight)
                tag = "ADD" if abs(nw) > abs(pw) else "REDUCE"
                delta = nw - pw
                lines.append(
                    f"    {s:<12} {_fmt_w(pw)} -> {_fmt_w(nw)} usd={_fmt_usd(pw, args.nav_usd)} -> {_fmt_usd(nw, args.nav_usd)} delta_usd={_fmt_usd(delta, args.nav_usd)} {tag}_ref={_fmt_px(close_ref.get(s))} stop={pos.stop_pct:.1%} take={pos.take_pct:.1%}"
                )

    lines.append("HOLD")
    if not holds:
        lines.append("  None")
    else:
        for s in holds:
            w = float(new_w[s])
            lines.append(f"  {s:<12} w={_fmt_w(w)} usd={_fmt_usd(w, args.nav_usd)}")

    lines.append("")
    lines.append("TARGET PORTFOLIO")
    if not new_w:
        lines.append("  Flat")
    else:
        gross = sum(abs(float(v)) for v in new_w.values())
        lines.append(f"  gross_short={gross:.2%} gross_short_usd={gross * args.nav_usd:.2f}")
        for s in sorted(new_w.keys(), key=lambda k: float(new_w[k])):
            w = float(new_w[s])
            lines.append(f"  {s:<12} {_fmt_w(w)} usd={_fmt_usd(w, args.nav_usd)}")

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
        "nav_reference_usd": args.nav_usd,
    }
    args.state_json.parent.mkdir(parents=True, exist_ok=True)
    args.state_json.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n")

    print(memo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
