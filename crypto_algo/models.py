from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class AssetInput:
    symbol: str
    rank: int
    price_usd: float
    funding_rate_8h: Optional[float]
    open_interest_usd: Optional[float]
    volume_usd: Optional[float]
    ret_1d: Optional[float]
    ret_7d: Optional[float]
    ret_30d: Optional[float]
    ret_90d: Optional[float]


@dataclass
class SignalView:
    symbol: str
    score: float
    trend_90d: float
    trend_30d: float
    trend_7d: float
    carry_score: float
    oi_score: float
    liquidity_score: float


@dataclass
class Position:
    symbol: str
    size_pct_nav: float
    entry_price: float
    opened_at: datetime
    last_price: float


@dataclass
class Instruction:
    action: str
    symbol: str
    reason: str
    size_pct_nav: Optional[float] = None


@dataclass
class SymbolMemory:
    entry_streak: int = 0
    exit_streak: int = 0


@dataclass
class EngineState:
    positions: Dict[str, Position] = field(default_factory=dict)
    memory: Dict[str, SymbolMemory] = field(default_factory=dict)
    last_exit_at: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunResult:
    timestamp: datetime
    instructions: list[Instruction]
    signals: list[SignalView]
    exposure: float
