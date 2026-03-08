from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .models import AssetInput

_V2_RUN_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})\.json$")


def latest_v2_run_path(runs_dir: Path) -> Path:
    files = sorted(runs_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No JSON runs found in {runs_dir}")
    return files[-1]


def parse_v2_timestamp(run_path: Path) -> datetime:
    m = _V2_RUN_RE.match(run_path.name)
    if not m:
        return datetime.now(timezone.utc)
    day, hhmmss = m.groups()
    ts = datetime.strptime(f"{day}_{hhmmss}", "%Y-%m-%d_%H%M%S")
    return ts.replace(tzinfo=timezone.utc)


def load_v2_snapshot(path: Path) -> tuple[datetime, list[AssetInput]]:
    payload = json.loads(path.read_text())
    timestamp = parse_v2_timestamp(path)
    candidates = payload.get("candidates", [])

    assets: list[AssetInput] = []
    for row in candidates:
        symbol = str(row.get("symbol", "")).upper()
        if not symbol:
            continue

        # v2 run snapshots do not include 90d return or all spot prices in candidates.
        # We preserve usable features and leave unavailable fields as None.
        assets.append(
            AssetInput(
                symbol=symbol,
                rank=int(row.get("rank", 9999)),
                price_usd=1.0,
                funding_rate_8h=_to_optional_float(row.get("funding_rate")),
                open_interest_usd=_to_optional_float(row.get("open_interest_usd")),
                volume_usd=_to_optional_float(row.get("volume_usd")),
                ret_1d=None,
                ret_7d=_to_optional_float(row.get("return_7d")),
                ret_30d=_to_optional_float(row.get("momentum_30d")),
                ret_90d=None,
            )
        )

    return timestamp, assets


def _to_optional_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
