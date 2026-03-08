from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UniverseConfig:
    min_rank: int = 50
    max_rank: int = 220
    rank_exit_buffer: int = 20
    excluded_symbols: tuple[str, ...] = ("BTC", "ETH")


@dataclass
class LiquidityConfig:
    min_open_interest_usd: float = 10_000_000.0
    min_volume_usd: float = 50_000_000.0


@dataclass
class SignalWeights:
    trend_90d: float = 0.35
    trend_30d: float = 0.25
    trend_7d: float = 0.10
    carry: float = 0.15
    oi_confirmation: float = 0.10
    liquidity: float = 0.05


@dataclass
class SignalConfig:
    entry_score_min: float = 0.62
    exit_score_max: float = 0.50
    momentum_exit_threshold: float = 0.02
    funding_entry_floor: float = -0.0008
    funding_hard_exit_floor: float = -0.0020
    weights: SignalWeights = field(default_factory=SignalWeights)


@dataclass
class DecisionConfig:
    entry_confirmation_runs: int = 2
    exit_confirmation_runs: int = 2
    reentry_cooldown_hours: int = 24
    min_hold_hours: int = 12


@dataclass
class RiskConfig:
    total_short_limit: float = 0.30
    max_positions: int = 8
    per_position_size: float = 0.0375


@dataclass
class StrategyConfig:
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
