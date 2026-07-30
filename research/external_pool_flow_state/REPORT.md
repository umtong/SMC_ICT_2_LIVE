# External stop-pool raid with direct flow-efficiency state

Result: `RES-20260730-EXTERNAL-POOL-FLOW-STATE-001`  
Claim: `CLM-20260730-EXTERNAL-POOL-FLOW-STATE-001` / issue #709  
Decision: `RETIRED_PRE2024_EXTERNAL_POOL_FLOW_STATE_FAILURE`

## Logic tested

The implementation separated two concepts that prior systems had conflated:

1. causal unconsumed 15-minute swing pools identified where vulnerable stop/liquidation orders could be consumed;
2. the next five seconds of actual Bybit aggressive turnover and price progress adjudicated `ACCEPT`, `ABSORB_REJECT` or `FLAT`.

Acceptance followed the raid toward the next pre-existing same-side pool. Rejection rotated toward the pre-existing opposite pool. Entry was the first observed trade after the state window plus fixed 500 ms. The initial system used a five-second state-loss exit; targets and hard stops were structural, no elapsed-time exit existed, and account paths used one slot, actual funding, fixed 0.5% NAV risk, 3x cap and 12/18/24 bp stress.

## Breadth

The source was not sparse:

- 17,769,695 canonical observed 500 ms buckets;
- 4,430 external-pool raid events;
- 2,815 acceptance states;
- 1,459 rejection states;
- 3,831 executable candidates after action-specific target and geometry checks.

Development contained 1,309 candidates and confirmation 1,287. This is therefore not a failure caused by over-filtering or dependence on one historical winner.

## Fixed state-exit result

| Stage | Selected trades | 12 bp | 18 bp | 24 bp | 24 bp PF |
|---|---:|---:|---:|---:|---:|
| March-April development | 937 | 0.06717x | 0.03991x | 0.03181x | 0.207 |
| May-June confirmation | 979 | 0.05239x | 0.02860x | 0.02302x | 0.088 |

The median holding time was measured in tens of seconds. A 15-minute external-liquidity delivery thesis was being invalidated by one complete five-second reversal. That was a real scale mismatch in the programization.

## Programization correction diagnostic

The same frozen entries, targets and hard stops were replayed with the five-second dynamic exit removed. No new signal, filter, threshold, risk or leverage was introduced.

| Stage | Zero-cost | 12 bp | 18 bp | 24 bp | Trades |
|---|---:|---:|---:|---:|---:|
| Development | 1.06947x | 0.10183x | 0.06266x | 0.05010x | 848 |
| Confirmation | 1.09101x | 0.06052x | 0.03350x | 0.02682x | 951 |

The correction recovered gross edge, proving that the original five-second exit was inconsistent with the scale of the thesis. It did **not** create tradable alpha: even the 12 bp path lost almost the entire account.

## Payoff geometry

The fixed market-chased entry arrived after the five-second confirmation while structural stops were only a few basis points away.

- development acceptance: mean gross `+0.09 bp`, median `-3.98 bp`, median stop `5.91 bp`;
- confirmation acceptance: mean gross `-0.58 bp`, median `-3.14 bp`, median stop `4.40 bp`;
- development rejection: mean gross `+1.82 bp`, median `-10.07 bp`, median stop `11.58 bp`;
- confirmation rejection: mean gross `+3.20 bp`, median `-5.66 bp`, median stop `7.65 bp`.

Rejection occasionally captured a large rotation, but the ordinary trade was negative and the average gross headroom remained far below realistic round-trip cost. Acceptance had essentially no stable gross edge.

## Decision

The exact family is retired. It must not be rescued by changing the pivot radius, five-second window, majority rule, flow sign, target, stop, cost, symbol, risk, leverage or by training ML to delete most trades.

The reusable lesson is narrower:

> Direct flow can contain some information after an external raid, but a market order after confirmation consumes the already-small edge. A faithful SMC/ICT successor must test the first high-resistance source retest/rebalance rather than chase the completed move.

That successor is a separate preregistered action family, not a parameter variation of this result. Official 2024–2026, ranking, ML and order authority remained closed. No credentials or orders were used.
