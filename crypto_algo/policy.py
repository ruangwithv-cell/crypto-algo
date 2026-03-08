from __future__ import annotations

from datetime import datetime, timedelta

from .config import StrategyConfig
from .models import AssetInput, EngineState, Instruction, Position, SignalView, SymbolMemory


def _get_memory(state: EngineState, symbol: str) -> SymbolMemory:
    mem = state.memory.get(symbol)
    if mem is None:
        mem = SymbolMemory()
        state.memory[symbol] = mem
    return mem


def _cooldown_active(state: EngineState, symbol: str, now: datetime, cfg: StrategyConfig) -> bool:
    last_exit = state.last_exit_at.get(symbol)
    if not last_exit:
        return False
    dt = datetime.fromisoformat(last_exit)
    return now < dt + timedelta(hours=cfg.decision.reentry_cooldown_hours)


def _can_add_position(state: EngineState, cfg: StrategyConfig) -> bool:
    exposure = sum(p.size_pct_nav for p in state.positions.values())
    if exposure + cfg.risk.per_position_size > cfg.risk.total_short_limit:
        return False
    if len(state.positions) >= cfg.risk.max_positions:
        return False
    return True


def _passes_entry_gates(asset: AssetInput, signal: SignalView, cfg: StrategyConfig) -> bool:
    if asset.symbol in cfg.universe.excluded_symbols:
        return False
    if asset.rank < cfg.universe.min_rank or asset.rank > cfg.universe.max_rank:
        return False
    if asset.open_interest_usd is None or asset.open_interest_usd < cfg.liquidity.min_open_interest_usd:
        return False
    if asset.volume_usd is None or asset.volume_usd < cfg.liquidity.min_volume_usd:
        return False
    if asset.funding_rate_8h is not None and asset.funding_rate_8h <= cfg.signal.funding_entry_floor:
        return False
    if asset.ret_30d is not None and asset.ret_30d >= 0:
        return False
    return signal.score >= cfg.signal.entry_score_min


def _exit_reason(asset: AssetInput, signal: SignalView, position: Position, now: datetime, cfg: StrategyConfig) -> str | None:
    if asset.rank > cfg.universe.max_rank + cfg.universe.rank_exit_buffer:
        return "rank_exit_hard"
    if asset.funding_rate_8h is not None and asset.funding_rate_8h <= cfg.signal.funding_hard_exit_floor:
        return "carry_collapse"

    held_for = now - position.opened_at
    if held_for < timedelta(hours=cfg.decision.min_hold_hours):
        return None

    # Hysteresis exits only after meaningful reversal
    if asset.ret_30d is not None and asset.ret_30d >= cfg.signal.momentum_exit_threshold:
        return "momentum_reversal"
    if signal.score <= cfg.signal.exit_score_max:
        return "score_decay"
    return None


def generate_instructions(
    now: datetime,
    assets: list[AssetInput],
    signals: list[SignalView],
    state: EngineState,
    cfg: StrategyConfig,
) -> list[Instruction]:
    signal_by_symbol = {s.symbol: s for s in signals}
    asset_by_symbol = {a.symbol: a for a in assets}
    instructions: list[Instruction] = []

    # Exit phase
    for symbol, pos in list(state.positions.items()):
        asset = asset_by_symbol.get(symbol)
        signal = signal_by_symbol.get(symbol)

        if asset is None or signal is None:
            instructions.append(Instruction(action="SHORT_EXIT", symbol=symbol, reason="dropped_from_universe"))
            continue

        reason = _exit_reason(asset, signal, pos, now, cfg)
        mem = _get_memory(state, symbol)
        if reason is None:
            mem.exit_streak = 0
            continue

        mem.exit_streak += 1
        if mem.exit_streak >= cfg.decision.exit_confirmation_runs:
            instructions.append(Instruction(action="SHORT_EXIT", symbol=symbol, reason=reason))
            mem.exit_streak = 0
            mem.entry_streak = 0

    # Entry phase
    for asset in assets:
        symbol = asset.symbol
        if symbol in state.positions:
            continue
        if _cooldown_active(state, symbol, now, cfg):
            continue
        if not _can_add_position(state, cfg):
            break

        signal = signal_by_symbol.get(symbol)
        if signal is None:
            continue

        mem = _get_memory(state, symbol)
        if _passes_entry_gates(asset, signal, cfg):
            mem.entry_streak += 1
        else:
            mem.entry_streak = 0

        if mem.entry_streak >= cfg.decision.entry_confirmation_runs:
            instructions.append(
                Instruction(
                    action="SHORT_ENTRY",
                    symbol=symbol,
                    reason="confirmed_signal",
                    size_pct_nav=cfg.risk.per_position_size,
                )
            )
            mem.entry_streak = 0
            mem.exit_streak = 0

    return instructions


def apply_instructions(
    now: datetime,
    instructions: list[Instruction],
    assets: list[AssetInput],
    state: EngineState,
) -> None:
    asset_by_symbol = {a.symbol: a for a in assets}

    for inst in instructions:
        if inst.action == "SHORT_ENTRY" and inst.size_pct_nav is not None:
            asset = asset_by_symbol.get(inst.symbol)
            if asset is None:
                continue
            state.positions[inst.symbol] = Position(
                symbol=inst.symbol,
                size_pct_nav=inst.size_pct_nav,
                entry_price=asset.price_usd,
                opened_at=now,
                last_price=asset.price_usd,
            )
            continue

        if inst.action == "SHORT_EXIT":
            state.positions.pop(inst.symbol, None)
            state.last_exit_at[inst.symbol] = now.isoformat()

    for symbol, pos in state.positions.items():
        asset = asset_by_symbol.get(symbol)
        if asset:
            pos.last_price = asset.price_usd
