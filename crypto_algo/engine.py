from __future__ import annotations

from datetime import datetime

from .config import StrategyConfig
from .models import AssetInput, RunResult
from .policy import apply_instructions, generate_instructions
from .signals import build_signal


class CryptoAlgoEngine:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()

    def run(self, timestamp: datetime, assets: list[AssetInput], state) -> RunResult:
        signals = [build_signal(asset, self.config) for asset in assets]
        signals.sort(key=lambda s: s.score, reverse=True)

        instructions = generate_instructions(timestamp, assets, signals, state, self.config)
        apply_instructions(timestamp, instructions, assets, state)

        exposure = round(sum(p.size_pct_nav for p in state.positions.values()), 6)
        return RunResult(
            timestamp=timestamp,
            instructions=instructions,
            signals=signals,
            exposure=exposure,
        )
