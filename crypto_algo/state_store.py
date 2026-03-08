from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import EngineState, Position, SymbolMemory


class StateStore:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> EngineState:
        if not self.state_path.exists():
            return EngineState()
        raw = self.state_path.read_text().strip()
        if not raw:
            return EngineState()
        data = json.loads(raw)

        positions = {
            symbol: Position(
                symbol=symbol,
                size_pct_nav=float(pos["size_pct_nav"]),
                entry_price=float(pos["entry_price"]),
                opened_at=datetime.fromisoformat(pos["opened_at"]),
                last_price=float(pos["last_price"]),
            )
            for symbol, pos in data.get("positions", {}).items()
        }
        memory = {
            symbol: SymbolMemory(
                entry_streak=int(mem.get("entry_streak", 0)),
                exit_streak=int(mem.get("exit_streak", 0)),
            )
            for symbol, mem in data.get("memory", {}).items()
        }
        return EngineState(
            positions=positions,
            memory=memory,
            last_exit_at=data.get("last_exit_at", {}),
        )

    def save(self, state: EngineState) -> None:
        payload = {
            "positions": {
                symbol: {
                    "size_pct_nav": pos.size_pct_nav,
                    "entry_price": pos.entry_price,
                    "opened_at": pos.opened_at.isoformat(),
                    "last_price": pos.last_price,
                }
                for symbol, pos in state.positions.items()
            },
            "memory": {symbol: asdict(mem) for symbol, mem in state.memory.items()},
            "last_exit_at": state.last_exit_at,
        }
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
