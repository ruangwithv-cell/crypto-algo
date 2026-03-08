from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .bear_unrestricted_backtest import _build_daily


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build live long-sleeve action memo from latest sleeve picks")
    p.add_argument(
        "--long-sleeve-json",
        type=Path,
        default=Path("/Users/mini/crypto_algo/state_live/long_sleeve_top100_latest.json"),
    )
    p.add_argument(
        "--data-json",
        type=Path,
        default=Path("/Users/mini/crypto_algo/state_live/binance_unrestricted_365d.json"),
    )
    p.add_argument(
        "--memo-path",
        type=Path,
        default=Path("/Users/mini/crypto_algo/state_live/long_sleeve_latest_action_memo.txt"),
    )
    p.add_argument(
        "--state-json",
        type=Path,
        default=Path("/Users/mini/crypto_algo/state_live/long_sleeve_live_state.json"),
    )
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


def _risk_from_vol(vol20: float) -> tuple[float, float]:
    stop = max(min(2.0 * float(vol20), 0.18), 0.08)
    take = max(min(3.0 * float(vol20), 0.35), 0.15)
    return stop, take


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
    payload = json.loads(args.long_sleeve_json.read_text())

    data_payload = json.loads(args.data_json.read_text())
    days, px, _ = _build_daily(data_payload)
    close_ref = {}
    if days:
        day = days[-1]
        close_ref = {s: float(b["close"]) for s, m in px.items() if (b := m.get(day)) is not None}

    picks = payload.get("picks", []) or []
    cfg = payload.get("config", {}) or {}
    uni = payload.get("universe", {}) or {}
    asof_utc = payload.get("asof_utc", "")

    target = {}
    for p in picks:
        s = str(p.get("symbol", "")).strip()
        if not s:
            continue
        w = float(p.get("weight", 0.0) or 0.0)
        if w <= 0:
            continue
        stop, take = _risk_from_vol(float(p.get("vol20", 0.0) or 0.0))
        target[s] = {
            "weight": w,
            "stop_pct": stop,
            "take_pct": take,
            "entry_ref": close_ref.get(s),
        }

    state = _load_state(args.state_json)
    prev_w = state.get("weights", {}) or {}
    prev_entry = state.get("entry_refs", {}) or {}
    new_w = {s: x["weight"] for s, x in target.items()}
    new_entry = {s: x["entry_ref"] for s, x in target.items() if x.get("entry_ref") is not None}

    prev_syms = set(prev_w)
    new_syms = set(new_w)
    opens = sorted(new_syms - prev_syms)
    closes = sorted(prev_syms - new_syms)
    adjusts = sorted(s for s in (prev_syms & new_syms) if abs(float(prev_w[s]) - float(new_w[s])) > 1e-9)
    holds = sorted(s for s in (prev_syms & new_syms) if abs(float(prev_w[s]) - float(new_w[s])) <= 1e-9)

    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("LONG_SLEEVE_V1 ACTION MEMO")
    lines.append(f"run_utc={now}")
    if asof_utc:
        lines.append(f"data_day_utc={asof_utc}")
    lines.append(
        "top_k={top_k} n_target={n_t} eligible={eligible} long_universe={lu}".format(
            top_k=cfg.get("top_k", ""),
            n_t=len(new_w),
            eligible=uni.get("eligible_count", ""),
            lu=uni.get("long_universe_count", ""),
        )
    )
    lines.append(f"nav_reference_usd={args.nav_usd:.2f}")
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
                t = target[s]
                w = float(t["weight"])
                entry = t["entry_ref"]
                lines.append(
                    f"    {s:<12} w={_fmt_w(w)} usd={_fmt_usd(w, args.nav_usd)} qty_est={_fmt_qty(w, args.nav_usd, entry)} entry_ref={_fmt_px(entry)} stop={t['stop_pct']:.1%} take={t['take_pct']:.1%}"
                )
        if adjusts:
            lines.append("  ADJUST")
            for s in adjusts:
                t = target[s]
                pw = float(prev_w[s])
                nw = float(t["weight"])
                tag = "ADD" if abs(nw) > abs(pw) else "REDUCE"
                delta = nw - pw
                lines.append(
                    f"    {s:<12} {_fmt_w(pw)} -> {_fmt_w(nw)} usd={_fmt_usd(pw, args.nav_usd)} -> {_fmt_usd(nw, args.nav_usd)} delta_usd={_fmt_usd(delta, args.nav_usd)} {tag}_ref={_fmt_px(close_ref.get(s))} stop={t['stop_pct']:.1%} take={t['take_pct']:.1%}"
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
        lines.append(f"  gross_long={gross:.2%} gross_long_usd={gross * args.nav_usd:.2f}")
        for s in sorted(new_w.keys(), key=lambda k: float(new_w[k]), reverse=True):
            w = float(new_w[s])
            lines.append(f"  {s:<12} {_fmt_w(w)} usd={_fmt_usd(w, args.nav_usd)}")

    memo = "\n".join(lines) + "\n"
    args.memo_path.parent.mkdir(parents=True, exist_ok=True)
    args.memo_path.write_text(memo)

    archive = args.memo_path.parent / "long_memos"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (archive / f"long_memo_{stamp}.txt").write_text(memo)

    new_state = {
        "weights": new_w,
        "entry_refs": new_entry,
        "last_run_utc": now,
        "data_day_utc": asof_utc,
        "n_target": len(new_w),
        "top_k": cfg.get("top_k"),
        "nav_reference_usd": args.nav_usd,
    }
    args.state_json.parent.mkdir(parents=True, exist_ok=True)
    args.state_json.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n")

    print(memo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
