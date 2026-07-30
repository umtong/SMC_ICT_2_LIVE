# Mature-auction manipulation–distribution Core + runner

## Decision

`RES-20260730-MATURE-AUCTION-AMD-RUNNER-001` is **`RETIRED_PRE2024_MATURE_AUCTION_AMD_BASE_FAILURE`**.

The four registered project directions and the Korean transcript corpus were applied as market logic rather than as a pattern checklist. A range was not accepted merely because two pivots existed. It had to exhibit a causal two-sided auction: a founding high/low pair, a later revisit to each boundary zone and at least three completed equilibrium crossings before either side was breached. Only then could the first boundary raid be interpreted as manipulation.

A completed reclaim and opposite internal 15-minute swing break established distribution away from the raid. The untouched opposite boundary of that same frozen range was the destination. The alternate action waited for a genuine 5-minute FVG rebalance, realized half at equilibrium and kept a protected runner for the external boundary.

## Programization audit

The initial event build produced zero actions because a high-side raid used the wrong target-consumption inequality: it compared the current bar high to the lower short target. That expression was almost always true and falsely discarded all mature ranges. The rule was corrected to `bar low <= lower target`, and all events, actions and account paths were regenerated before any economic interpretation.

The final implementation also enforces causal pivot activation, maturity before raid, pre-maturity reset, frozen boundaries, one-time manipulation, target availability before entry, genuine FVG chronology, pending-slot occupancy, 50% partial arithmetic, post-partial protected-swing tightening, actual signed funding, 500ms latency and adverse same-minute ordering.

## Event funnel

| Symbol | causal 15m pivots | candidate ranges | pre-maturity breaches | mature ranges | raids | reclaim+shift actions | FVG fills |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 28,802 | 4,866 | 4,487 | 378 | 378 | 98 | 17 |
| ETHUSDT | 26,761 | 4,557 | 4,205 | 351 | 351 | 87 | 13 |

The maturity rule materially reduced the earlier false-pool problem. It did not, however, create a positive action surface.

## `SHIFT_FULL`

| Year | 0bp | 12bp | 18bp | 24bp | 24bp trades | 24bp PF | winner-rerouted 24bp |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 1.0044x | 0.9882x | 0.9811x | 0.9745x | 61 | 0.683 | 0.9567x |
| 2022 | 0.9974x | 0.9682x | 0.9567x | 0.9465x | 73 | 0.414 | 0.9359x |
| 2023 | 0.9978x | 0.9726x | 0.9626x | 0.9540x | 47 | 0.324 | 0.9476x |

The unchanged 2022–2023 route was approximately flat before cost and broadly negative after realistic cost. This is not a tail-concentration problem: the base mean itself is not positive.

## `FVG_SPLIT_RUNNER`

| Year | selected shifts | fills | 0bp | 12bp | 18bp | 24bp | 24bp PF | partial rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 61 | 7 | 0.9961x | 0.9938x | 0.9928x | 0.9920x | 0.000 | 14.29% |
| 2022 | 73 | 16 | 1.0017x | 0.9963x | 0.9940x | 0.9919x | 0.454 | 56.25% |
| 2023 | 47 | 6 | 1.0053x | 1.0010x | 0.9992x | 0.9977x | 0.554 | 50.00% |

The genuine-FVG path was sparse and its tiny frictionless gain did not survive realistic costs. Partial realization and protected-runner management did not manufacture alpha.

## Interpretation

This experiment closes a more faithful chart-only SMC/ICT mapping:

```text
mature balance
→ one-side liquidity raid
→ reclaim
→ internal order-flow shift
→ genuine inefficiency rebalance
→ equilibrium partial
→ scale-matched external target
```

The logic is coherent and the implementation error was real, but after correction the average price advantage was near zero. Therefore the remaining gap is not another touch count, FVG threshold, pivot radius, partial fraction or stop rule. Chart structure did not identify who was actually forced, who replenished liquidity or whether inventory truly transferred.

The next Core must include an economically earlier state such as executable order-book replenishment, queue resistance or an externally observed inventory transfer. It must still be evaluated as a causal SMC/ICT action lifecycle, not as an isolated indicator.

## Boundary

Do not rescue this family with maturity counts, equilibrium crossings, pivot scale, FVG, target, partial fraction, stop, symbol/side, cost, risk, leverage or ML. Official 2024–2026 remained sealed. No credentials or orders were used.
