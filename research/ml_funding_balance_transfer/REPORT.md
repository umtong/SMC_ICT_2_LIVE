# Continuous Bybit funding balance-transfer state — decision report

**Claim:** `CLM-20260730-ML-FUNDING-BALANCE-TRANSFER-001`  
**Result:** `RES-20260730-ML-FUNDING-BALANCE-TRANSFER-001`  
**Decision:** **RETIRED ECONOMIC FAILURE before official 2024**.

## Mechanism

The event is the exact Bybit funding settlement, not a clock window or chart shape. Transfer notional is `abs(rate) × causal OI × causal mark`; it is normalized by prior-only five-minute OI-notional turnover. Positive funding makes longs the payer side and negative funding makes shorts the payer side.

The implementation compared three SMC/ICT-readable actions: continuation after the first displacement rebalance, reversal after a funding-direction extension and reclaim, and continuation after an initial opposite move followed by a causal reclaim in the funding-transfer direction. Flat remained available.

## Programization audit

The first marketable-confirmation implementation chased a move that had already happened. It was replaced by causal first-rebalance and reclaim templates. The first target map used nearby confirmed one-hour pivots; recent semantic audits showed that such internal pools are not scale-matched to an eight-hour funding balance-sheet event. Final targets therefore use only still-unconsumed prior-day and confirmed four-hour external liquidity.

Future fill selection was removed. An unfilled but resolved pending action has zero return in training and still occupies the global slot until cancellation or expiry. All new orders activate after 500 ms and execute only at the first later observed one-minute price.

## Economic evidence

The complete 2021-2023 source produced 6,335 settlements and 7,258 resolved scale-matched action outcomes. Fixed-rule one-slot union returns were:

- 2021: **-46.91%**;
- 2022: **-60.05%**;
- 2023: **-53.43%**.

The strongest readable exceptions did not persist. A high-stress opposite-first/OI-response reclaim made +3.79% over 11 trades in 2022 but lost in 2023 and all positive PnL was in the top five. Receiver re-leverage aligned retracement lost in 2022, then made +7.54% in 2023 with 74.26% top-five positive-PnL share.

Direct account-value ML did not rescue the route:

| model | 2022 return | trades | 2023 return | trades |
|---|---:|---:|---:|---:|
| Ridge | -0.66% | 356 | -12.88% | 179 |
| HGBT | -53.62% | 513 | -31.45% | 326 |

The models include resolved unfilled candidates as zero-value actions and replay the pending/open global slot. Classification skill observed in an earlier target-hit experiment therefore cannot be mistaken for tradable NAV value.

## Decision

The cash transfer is real, but the available completed price/OI/account/premium state does not identify a stable cost-surviving action. The family is closed without funding threshold, confirmation-window, target, risk or leverage rescue. Official 2024-2026 remains unopened and no orders were submitted.
