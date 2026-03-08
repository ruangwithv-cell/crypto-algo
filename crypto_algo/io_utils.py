from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import AssetInput, Instruction, RunResult, SignalView


def load_snapshot(path: Path) -> tuple[datetime, list[AssetInput]]:
    data = json.loads(path.read_text())
    ts = datetime.fromisoformat(data["timestamp"])
    assets: list[AssetInput] = []

    for row in data.get("assets", []):
        returns = row.get("returns", {})
        assets.append(
            AssetInput(
                symbol=str(row["symbol"]).upper(),
                rank=int(row["rank"]),
                price_usd=float(row["price_usd"]),
                funding_rate_8h=_to_optional_float(row.get("funding_rate_8h")),
                open_interest_usd=_to_optional_float(row.get("open_interest_usd")),
                volume_usd=_to_optional_float(row.get("volume_usd")),
                ret_1d=_to_optional_float(returns.get("1d")),
                ret_7d=_to_optional_float(returns.get("7d")),
                ret_30d=_to_optional_float(returns.get("30d")),
                ret_90d=_to_optional_float(returns.get("90d")),
            )
        )

    return ts, assets


def _to_optional_float(v: object) -> float | None:
    if v is None:
        return None
    return float(v)


def write_run_snapshot(path: Path, result: RunResult) -> None:
    payload = {
        "timestamp": result.timestamp.isoformat(),
        "exposure": result.exposure,
        "instructions": [
            {
                "action": i.action,
                "symbol": i.symbol,
                "reason": i.reason,
                "size_pct_nav": i.size_pct_nav,
            }
            for i in result.instructions
        ],
        "signals": [
            {
                "symbol": s.symbol,
                "score": s.score,
                "trend_90d": s.trend_90d,
                "trend_30d": s.trend_30d,
                "trend_7d": s.trend_7d,
                "carry_score": s.carry_score,
                "oi_score": s.oi_score,
                "liquidity_score": s.liquidity_score,
            }
            for s in result.signals
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def build_action_memo(result: RunResult, positions: dict[str, dict]) -> str:
    exits = [i for i in result.instructions if i.action == "SHORT_EXIT"]
    entries = [i for i in result.instructions if i.action == "SHORT_ENTRY"]
    top_watch = sorted(result.signals, key=lambda s: s.score, reverse=True)[:5]

    lines: list[str] = []
    lines.append("=" * 58)
    lines.append("  CRYPTO ALGO — ACTION MEMO")
    lines.append(f"  Run: {result.timestamp.isoformat()}")
    lines.append("=" * 58)
    lines.append("")
    lines.append(f"  EXPOSURE: {result.exposure:.1%}")
    lines.append("")
    lines.append("-" * 58)
    lines.append("  ACTION — EXECUTE NOW")
    lines.append("-" * 58)

    if not exits and not entries:
        lines.append("  No action required this run.")
    else:
        if exits:
            lines.append("  CLOSE:")
            for e in exits:
                lines.append(f"    CLOSE {e.symbol:<10} [{e.reason}]")
        if entries:
            lines.append("  OPEN:")
            for e in entries:
                size = e.size_pct_nav or 0.0
                lines.append(f"    OPEN  {e.symbol:<10} {size:.2%} NAV [{e.reason}]")

    lines.append("")
    lines.append("-" * 58)
    lines.append("  HOLD — NO ACTION")
    lines.append("-" * 58)
    if not positions:
        lines.append("  No open positions.")
    else:
        for symbol, pos in sorted(positions.items()):
            lines.append(
                f"    {symbol:<10} {pos['size_pct_nav']:.2%} NAV entry={pos['entry_price']:.6g} now={pos['last_price']:.6g}"
            )

    lines.append("")
    lines.append("-" * 58)
    lines.append("  WATCH")
    lines.append("-" * 58)
    for s in top_watch:
        lines.append(
            f"    {s.symbol:<10} score={s.score:.3f} trend30={s.trend_30d:.2f} carry={s.carry_score:.2f} oi={s.oi_score:.2f}"
        )
    lines.append("=" * 58)
    return "\n".join(lines) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
