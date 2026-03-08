# Crypto Algo Feasibility Report
Date: 2026-03-06
Project: /Users/mini/crypto_algo
Scope: Strategy architecture, anti-whipsaw controls, v2-feed adapter path, and historical action-churn comparison.

## Review Board (Expert Roles)
- Quant Research Lead (signal design, overfitting risk)
- Portfolio/Risk Manager (position/risk constraints, deployment gates)
- Systematic Execution Lead (turnover, hysteresis, no-trade zones)
- Data Engineering Lead (data lineage, feature completeness, survivorship bias)
- Controls/Audit Lead (reproducibility, state/auditability, operational safety)

## Method
1. Code inspection of core modules (`config.py`, `signals.py`, `policy.py`, `adapters_v2.py`, `backtest_compare.py`).
2. Historical replay against `/Users/mini/data/runs` (29 runs).
3. Whipsaw robustness checks with multiple windows (1, 2, 3, 5, 8 runs).

## Executive Verdict
- **Feasible now for shadow deployment** (paper decisions, no capital).
- **Not yet feasible for live capital deployment** until critical data-quality gaps are fixed.

Reason: current adapter-driven evaluation materially understates uncertainty and cannot validate return edge.

## Findings

### Critical Findings
1. **Adapter uses synthetic price (`price_usd=1.0`)**
   - Evidence: `crypto_algo/adapters_v2.py:46`
   - Impact: position mark-to-market and any price-based risk logic are non-informative in v2-adapter mode.

2. **High-horizon trend input is missing in adapter mode (`ret_90d=None`)**
   - Evidence: `crypto_algo/adapters_v2.py:53`
   - Signal behavior: missing values are scored neutral (0.5) in `signals.py:11-14`.
   - Impact: 90d component weight is effectively diluted in live-v2 path.

3. **Universe for new strategy is inherited from old strategy's candidate list**
   - Evidence: adapter only reads `payload["candidates"]` (`adapters_v2.py:32`).
   - Impact: selection independence is compromised; this is not a fully independent strategy test.

4. **Backtest comparator validates churn reduction only, not PnL/Sharpe/drawdown edge**
   - Evidence: comparator computes actions/whipsaw counts only (`backtest_compare.py:121-137`).
   - Impact: cannot conclude economic edge yet; only operational stability improvement is demonstrated.

### High Findings
1. **Anti-whipsaw policy is structurally sound**
   - Confirmation: entry/exit confirmation (`policy.py:95`, `policy.py:120`), cooldown (`policy.py:17-23`), minimum hold (`policy.py:56-58`), hysteresis exits (`policy.py:60-64`).
   - Impact: materially lowers flip-flop frequency.

2. **Observed churn reduction is strong and robust by window**
   - Dataset: 29 runs.
   - Old strategy actions/run: 1.7241 (50 actions).
   - `crypto_algo` actions/run: 0.1034 (3 actions).
   - Whipsaw counts:
     - window=1 run: old 14 vs new 0
     - window=2 run: old 27 vs new 0
     - window=3 run: old 27 vs new 0
     - window=5 run: old 27 vs new 0
     - window=8 run: old 27 vs new 0

### Medium Findings
1. **Signal calibration still heuristic**
   - Evidence: hardcoded scales in `signals.py` (e.g., 0.60/0.35/0.20 trend scales).
   - Impact: likely regime-sensitive; requires out-of-sample calibration.

2. **Risk model currently exposure/slot based, not volatility-targeted**
   - Evidence: fixed per-position sizing in `config.py` and `policy.py`.
   - Impact: stable turnover, but risk parity and tail-risk adaptation are limited.

## Feasibility Decision Matrix
- Strategy stability (turnover/whipsaw): **PASS**
- Data integrity for live decisions: **FAIL (critical)**
- Independent signal test validity: **FAIL (critical)**
- Operational reproducibility/auditability: **PASS**
- Capital readiness: **NO-GO**
- Shadow readiness: **GO**

## Required Gates Before Live Capital
1. Build direct market-data adapter (not v2-candidate derived) with full feature set: rank, 1d/7d/30d/90d returns, funding, OI, volume, and real spot/mark price.
2. Add PnL-aware backtest harness with transaction cost + slippage model and risk metrics (CAGR, max drawdown, Sharpe/Sortino, turnover).
3. Run forward shadow period >= 4 weeks with fixed config and no discretionary overrides.
4. Add guardrails for stale data / partial feed / missing fields with fail-closed behavior.

## Board Recommendation
- Continue immediately in **shadow mode** using current code.
- Block capital deployment until the four gates above are complete and re-reviewed.
