# Selection Subagents Report (2026-03-06)

Objective: test multiple independent token-selection approaches under the same execution/risk framework and choose one final version for live testing.

## Subagent Approaches Tested
1. `trend_relative`
- Prioritizes multi-horizon downside trend + weakness vs cross-sectional market proxy + funding support.

2. `carry_pressure`
- Prioritizes positive short carry (funding) + downside trend persistence.

3. `breakdown_quality`
- Prioritizes technical breakdown quality (distance from highs) + downside trend.

4. `hybrid_final` (research blend)
- Combines trend, breakdown, relative weakness, and carry into one score.

## Backtest Outputs
- 30d: `/Users/mini/crypto_algo/state_live/selection_lab_30d.json`
- 90d: `/Users/mini/crypto_algo/state_live/selection_lab_90d.json`
- 365d: `/Users/mini/crypto_algo/state_live/selection_lab_365d.json`

## Result Snapshot (Total Return)
- 30d:
  - trend_relative: +2.55%
  - carry_pressure: +3.91%
  - breakdown_quality: +1.77%
  - hybrid_final: -3.91%

- 90d:
  - trend_relative: +67.11%
  - carry_pressure: +58.60%
  - breakdown_quality: +70.94%
  - hybrid_final: +55.62%

- 365d:
  - trend_relative: +123.71%
  - carry_pressure: +129.84%
  - breakdown_quality: +124.73%
  - hybrid_final: +133.06%

## Final Version Chosen For Testing
Chosen selector: **`carry_pressure`**

Reason:
- Best cross-window consistency (top performer on 30d and 2nd-best on 90d/365d).
- Strong Sharpe profile without being overly concentrated in one regime archetype.

## Final Test Reports (carry_pressure)
- 30d: `/Users/mini/crypto_algo/state_live/bear_v2_final_30d.json`
- 90d: `/Users/mini/crypto_algo/state_live/bear_v2_final_90d.json`
- 365d: `/Users/mini/crypto_algo/state_live/bear_v2_final_365d.json`
