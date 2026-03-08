from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LSConfig:
    min_rank: int = 30
    max_rank: int = 220
    min_open_interest_usd: float = 8_000_000.0
    excluded_symbols: tuple[str, ...] = (
        "BTC",
        "ETH",
        "USDT",
        "USDC",
        "DAI",
        "FDUSD",
        "TUSD",
        "USDE",
        "PYUSD",
        "BUSD",
        "STABLE",
    )
    lookback_days_short: int = 7
    lookback_days_medium: int = 30
    lookback_days_long: int = 90

    n_longs: int = 6
    n_shorts: int = 6
    gross_exposure: float = 1.0
    max_single_name: float = 0.20

    w_momentum: float = 0.45
    w_carry: float = 0.25
    w_oi_alignment: float = 0.20
    w_liquidity: float = 0.10

    rebalance_min_abs_score: float = 0.10
    turnover_cost_bps: float = 5.0

    beta_lookback_points: int = 20
    min_beta_samples: int = 8
