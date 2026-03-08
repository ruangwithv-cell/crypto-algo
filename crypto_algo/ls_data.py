from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class LSPoint:
    symbol: str
    rank: int
    price: float
    funding_8h: float | None
    oi_usd: float | None
    ret_7d: float | None
    ret_30d: float | None
    ret_90d: float | None
    oi_change_7d: float | None


def parse_ts(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def load_state(path: Path) -> dict:
    return json.loads(path.read_text())


def collect_timestamps(data: dict) -> list[datetime]:
    out: set[datetime] = set()
    for bucket in ("price_history", "rank_history", "funding_history", "open_interest_history"):
        for samples in data.get(bucket, {}).values():
            for s in samples:
                out.add(parse_ts(s["timestamp"]))
    return sorted(out)


def _last_before(samples: list[dict], ts: datetime, key: str):
    val = None
    for s in samples:
        st = parse_ts(s["timestamp"])
        if st <= ts:
            val = s[key]
        else:
            break
    return val


def _value_before(samples: list[dict], ts: datetime, target_seconds: float, key: str):
    prev = None
    prev_ts = None
    t0 = ts.timestamp() - target_seconds
    for s in samples:
        st = parse_ts(s["timestamp"])
        if st.timestamp() <= t0:
            prev = s[key]
            prev_ts = st
        else:
            break
    return prev, prev_ts


def _return_over_days(price_samples: list[dict], ts: datetime, days: int) -> float | None:
    now = _last_before(price_samples, ts, "price")
    if now is None or now <= 0:
        return None
    prev, _ = _value_before(price_samples, ts, days * 86400.0, "price")
    if prev is None or prev <= 0:
        return None
    return (float(now) - float(prev)) / float(prev)


def _oi_change_7d(oi_samples: list[dict], ts: datetime) -> float | None:
    now = _last_before(oi_samples, ts, "open_interest_usd")
    if now is None or now <= 0:
        return None
    prev, _ = _value_before(oi_samples, ts, 7 * 86400.0, "open_interest_usd")
    if prev is None or prev <= 0:
        return None
    return (float(now) - float(prev)) / float(prev)


def build_points(data: dict, ts: datetime) -> list[LSPoint]:
    price_h = data.get("price_history", {})
    rank_h = data.get("rank_history", {})
    fund_h = data.get("funding_history", {})
    oi_h = data.get("open_interest_history", {})

    symbols = set(price_h.keys()) & set(rank_h.keys())
    out: list[LSPoint] = []

    for sym in sorted(symbols):
        prices = price_h.get(sym, [])
        ranks = rank_h.get(sym, [])
        if not prices or not ranks:
            continue

        rank = _last_before(ranks, ts, "rank")
        price = _last_before(prices, ts, "price")
        if rank is None or price is None:
            continue

        funding = _last_before(fund_h.get(sym, []), ts, "rate")
        oi_now = _last_before(oi_h.get(sym, []), ts, "open_interest_usd")
        out.append(
            LSPoint(
                symbol=sym,
                rank=int(rank),
                price=float(price),
                funding_8h=float(funding) if funding is not None else None,
                oi_usd=float(oi_now) if oi_now is not None else None,
                ret_7d=_return_over_days(prices, ts, 7),
                ret_30d=_return_over_days(prices, ts, 30),
                ret_90d=_return_over_days(prices, ts, 90),
                oi_change_7d=_oi_change_7d(oi_h.get(sym, []), ts),
            )
        )

    return out


def prices_at_next(data: dict, symbols: list[str], ts_next: datetime) -> dict[str, float]:
    out: dict[str, float] = {}
    ph = data.get("price_history", {})
    for s in symbols:
        samples = ph.get(s, [])
        px = _last_before(samples, ts_next, "price") if samples else None
        if px is not None:
            out[s] = float(px)
    return out


def symbol_return_path(data: dict, symbol: str, ts: datetime, points: int) -> list[float]:
    samples = data.get("price_history", {}).get(symbol, [])
    if len(samples) < 3:
        return []

    filtered = [x for x in samples if parse_ts(x["timestamp"]) <= ts]
    if len(filtered) < 3:
        return []

    vals = [float(x["price"]) for x in filtered[-(points + 1):]]
    if len(vals) < 3:
        return []

    rets: list[float] = []
    for a, b in zip(vals[:-1], vals[1:]):
        if a > 0:
            rets.append((b - a) / a)
    return rets
