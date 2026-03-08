from __future__ import annotations

from .config import StrategyConfig
from .models import AssetInput, SignalView


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(x, hi))


def _to_short_score(negative_return: float | None, scale: float) -> float:
    if negative_return is None:
        return 0.5
    return _clamp(max(-negative_return, 0.0) / scale)


def _carry_score(funding_8h: float | None) -> float:
    if funding_8h is None:
        return 0.5
    # map [-0.10%, +0.10%] per 8h into [0,1]
    return _clamp((funding_8h + 0.001) / 0.002)


def _oi_confirmation_score(asset: AssetInput) -> float:
    # Proxy: stronger when 7d return is negative and OI is significant.
    trend = _to_short_score(asset.ret_7d, 0.25)
    if asset.open_interest_usd is None:
        return 0.5 * trend
    oi_scale = _clamp(asset.open_interest_usd / 100_000_000.0)
    return _clamp(0.5 * trend + 0.5 * oi_scale)


def _liquidity_score(asset: AssetInput) -> float:
    if asset.open_interest_usd is None or asset.volume_usd is None:
        return 0.0
    oi = _clamp(asset.open_interest_usd / 75_000_000.0)
    vol = _clamp(asset.volume_usd / 150_000_000.0)
    return 0.5 * (oi + vol)


def build_signal(asset: AssetInput, cfg: StrategyConfig) -> SignalView:
    w = cfg.signal.weights
    trend_90 = _to_short_score(asset.ret_90d, 0.60)
    trend_30 = _to_short_score(asset.ret_30d, 0.35)
    trend_7 = _to_short_score(asset.ret_7d, 0.20)
    carry = _carry_score(asset.funding_rate_8h)
    oi_score = _oi_confirmation_score(asset)
    liq = _liquidity_score(asset)

    score = (
        w.trend_90d * trend_90
        + w.trend_30d * trend_30
        + w.trend_7d * trend_7
        + w.carry * carry
        + w.oi_confirmation * oi_score
        + w.liquidity * liq
    )

    return SignalView(
        symbol=asset.symbol,
        score=round(score, 6),
        trend_90d=trend_90,
        trend_30d=trend_30,
        trend_7d=trend_7,
        carry_score=carry,
        oi_score=oi_score,
        liquidity_score=liq,
    )
