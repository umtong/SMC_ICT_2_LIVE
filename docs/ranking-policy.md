# Strategy ranking policy

## Purpose

Rank hard-valid strategy and strategy-portfolio results by closeness to the full project objective. The ranking provides a current comparison baseline and does not certify target attainment, validation completion, or practical use.

## Eligibility

Include candidates that satisfy the basic validity contract for causality, calculation, data integrity, and realistic execution assumptions. Hard-invalid results remain in the failure registry but are excluded from the ranking.

Economic weakness is not hard invalidity. A method-valid result that is far below target remains rankable if it has comparable account-level evidence.

## Primary ordering

The primary ranking criterion is the gap between realistic after-cost geometric daily growth and the 1% target. Smaller target gap ranks higher.

A candidate with forced liquidation or irrecoverable account damage cannot outrank a survival-qualified candidate solely through raw return. The ranking therefore measures closeness to the full objective rather than unqualified return.

## Secondary ordering

When target gaps are materially similar or comparison uncertainty overlaps, use:

1. maximum drawdown and recovery;
2. liquidation and tail-loss behavior;
3. profit concentration and performance after removing top trades;
4. effective independent opportunity and trade count;
5. sensitivity to fees, spread, slippage, latency, partial fills, liquidity and capacity;
6. capital efficiency;
7. validation and comparison confidence.

Do not hide different weaknesses inside an arbitrary single weighted score.

## Incomplete normalization

Prefer common data, cost, execution and evaluation contracts. When full normalization is not possible, keep provisional ranks, disclose the missing normalization, and lower comparison confidence.

## Operational effect

Rank does not determine research priority, validation budget, protection, or default next steps. Work selection is based on expected contribution to the objective and information value.

All decision-ready results are retained once through the Result Registry, code commit, data snapshot and evaluation/cost/execution contract. Rank changes update the ranking record and do not trigger repeated preservation or validation.

## Component rankings

Execution routing, data, feature, portfolio-construction and other components may have separate rankings. A component first place does not enter the overall strategy ranking until it is embedded in a complete strategy or portfolio candidate.

## Current revision 7 ranking

1. `RES-20260725-ALPHA-HYP-001` / `high_resistance_sweep c232ae43b7a1401d`
   - after-cost geometric daily growth: `0.0024555%`
   - target gap: `0.9975445 percentage points per trading day`
   - total return: `+1.8076%`
   - MDD: `7.2774%`
   - 55 trades
   - negative at 18 and 24 bps
   - provisional, low comparison confidence
2. `RES-20260725-CAUSAL-ALPHA-WAVE1-001` / best nonzero balance-to-imbalance specification
   - geometric daily growth: approximately `-0.0719%`
   - provisional comparison due to different window and cost contract
3. `RES-20260725-CROSS-ASSET-LEADLAG-001` / best recorded underreaction configuration
   - geometric daily growth: approximately `-1.483%`
   - provisional comparison due to different window and cost contract

Current execution-routing component first place: `RES-20260725-1510-L1-EXEC-001`.
