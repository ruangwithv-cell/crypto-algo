from __future__ import annotations

import math
from dataclasses import dataclass

from .ls_config import LSConfig
from .ls_data import LSPoint, symbol_return_path


@dataclass
class SignalRow:
    symbol: str
    score: float
    z_mom: float
    z_carry: float
    z_oi_align: float
    z_liq: float


def _zscore_map(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    vals = list(values.values())
    mu = sum(vals) / len(vals)
    var = sum((x - mu) ** 2 for x in vals) / max(len(vals), 1)
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sd for k, v in values.items()}


def build_signals(points: list[LSPoint], cfg: LSConfig) -> list[SignalRow]:
    eligible = [
        p for p in points
        if cfg.min_rank <= p.rank <= cfg.max_rank
        and p.symbol not in cfg.excluded_symbols
        and p.oi_usd is not None
        and p.oi_usd >= cfg.min_open_interest_usd
        and p.ret_30d is not None
        and p.ret_7d is not None
    ]
    if not eligible:
        return []

    raw_mom: dict[str, float] = {}
    raw_carry: dict[str, float] = {}
    raw_oi: dict[str, float] = {}
    raw_liq: dict[str, float] = {}

    for p in eligible:
        r30 = p.ret_30d or 0.0
        r7 = p.ret_7d or 0.0
        r90 = p.ret_90d or 0.0
        mom = 0.5 * r30 + 0.3 * r7 + 0.2 * r90
        carry = -(p.funding_8h or 0.0)
        sign = 1.0 if mom >= 0 else -1.0
        oi_align = sign * (p.oi_change_7d or 0.0)
        liq = math.log(max(p.oi_usd or 1.0, 1.0))

        raw_mom[p.symbol] = mom
        raw_carry[p.symbol] = carry
        raw_oi[p.symbol] = oi_align
        raw_liq[p.symbol] = liq

    zm = _zscore_map(raw_mom)
    zc = _zscore_map(raw_carry)
    zo = _zscore_map(raw_oi)
    zl = _zscore_map(raw_liq)

    rows: list[SignalRow] = []
    for s in raw_mom:
        score = (
            cfg.w_momentum * zm.get(s, 0.0)
            + cfg.w_carry * zc.get(s, 0.0)
            + cfg.w_oi_alignment * zo.get(s, 0.0)
            + cfg.w_liquidity * zl.get(s, 0.0)
        )
        rows.append(SignalRow(symbol=s, score=score, z_mom=zm.get(s, 0.0), z_carry=zc.get(s, 0.0), z_oi_align=zo.get(s, 0.0), z_liq=zl.get(s, 0.0)))

    rows.sort(key=lambda r: r.score, reverse=True)
    return rows


def _cap_and_normalize(weights: dict[str, float], target_gross: float, cap: float) -> dict[str, float]:
    if not weights:
        return {}

    out = dict(weights)
    for _ in range(8):
        gross = sum(abs(w) for w in out.values())
        if gross <= 1e-12:
            return {k: 0.0 for k in out}
        out = {k: w * (target_gross / gross) for k, w in out.items()}
        clipped = False
        for k, w in list(out.items()):
            if abs(w) > cap:
                out[k] = cap if w > 0 else -cap
                clipped = True
        if not clipped:
            break

    gross = sum(abs(w) for w in out.values())
    if gross > 1e-12:
        out = {k: w * (target_gross / gross) for k, w in out.items()}
    return out


def _compute_betas(data: dict, symbols: list[str], ts, cfg: LSConfig) -> dict[str, float]:
    paths = {s: symbol_return_path(data, s, ts, cfg.beta_lookback_points) for s in symbols}
    usable = [s for s, arr in paths.items() if len(arr) >= cfg.min_beta_samples]
    if len(usable) < 4:
        return {s: 1.0 for s in symbols}

    min_len = min(len(paths[s]) for s in usable)
    market = []
    for i in range(min_len):
        market.append(sum(paths[s][-(min_len - i)] for s in usable) / len(usable))

    m_mu = sum(market) / len(market)
    m_var = sum((x - m_mu) ** 2 for x in market) / max(len(market), 1)
    if m_var <= 1e-12:
        return {s: 1.0 for s in symbols}

    out = {}
    for s in symbols:
        arr = paths.get(s, [])
        if len(arr) < min_len:
            out[s] = 1.0
            continue
        xs = arr[-min_len:]
        x_mu = sum(xs) / len(xs)
        cov = sum((x - x_mu) * (m - m_mu) for x, m in zip(xs, market)) / max(len(xs), 1)
        out[s] = cov / m_var
    return out


def _beta_neutral_scale(weights: dict[str, float], betas: dict[str, float], gross_target: float) -> dict[str, float]:
    if not weights:
        return {}
    longs = {k: v for k, v in weights.items() if v > 0}
    shorts = {k: v for k, v in weights.items() if v < 0}
    if not longs or not shorts:
        return weights

    long_gross = sum(longs.values())
    short_gross = sum(-v for v in shorts.values())
    if long_gross <= 1e-12 or short_gross <= 1e-12:
        return weights

    bl = sum((v / long_gross) * betas.get(k, 1.0) for k, v in longs.items())
    bs = sum((v / short_gross) * betas.get(k, 1.0) for k, v in shorts.items())
    # shorts have negative weights, so side beta contribution is -short_gross*bs
    denom = bl + bs
    if abs(denom) < 1e-9:
        return weights

    long_target = gross_target * (bs / denom)
    short_target = gross_target - long_target
    if long_target <= 0.1 * gross_target or short_target <= 0.1 * gross_target:
        return weights

    scaled = {}
    for k, v in longs.items():
        scaled[k] = v * (long_target / long_gross)
    for k, v in shorts.items():
        scaled[k] = v * (short_target / short_gross)
    return scaled


def construct_portfolio(data: dict, ts, points: list[LSPoint], cfg: LSConfig) -> tuple[dict[str, float], list[SignalRow]]:
    rows = build_signals(points, cfg)
    if not rows:
        return {}, []

    longs = [r for r in rows if r.score >= cfg.rebalance_min_abs_score][: cfg.n_longs]
    shorts = [r for r in reversed(rows) if r.score <= -cfg.rebalance_min_abs_score][: cfg.n_shorts]
    if not longs or not shorts:
        return {}, rows

    long_strength = {r.symbol: max(r.score, 1e-6) for r in longs}
    short_strength = {r.symbol: max(-r.score, 1e-6) for r in shorts}

    sum_l = sum(long_strength.values())
    sum_s = sum(short_strength.values())
    if sum_l <= 0 or sum_s <= 0:
        return {}, rows

    weights = {}
    for s, a in long_strength.items():
        weights[s] = 0.5 * cfg.gross_exposure * (a / sum_l)
    for s, a in short_strength.items():
        weights[s] = -0.5 * cfg.gross_exposure * (a / sum_s)

    betas = _compute_betas(data, list(weights.keys()), ts, cfg)
    weights = _beta_neutral_scale(weights, betas, cfg.gross_exposure)
    weights = _cap_and_normalize(weights, cfg.gross_exposure, cfg.max_single_name)
    return weights, rows
