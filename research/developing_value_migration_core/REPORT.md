# Developing-value migration first-rebalance Core

Decision: `RETIRED_2022_SPARSE_AND_NEGATIVE_GROSS_DEVELOPING_VALUE_MIGRATION_FAILURE`

The symbols are test markets. The information unit is two consecutive equal-turnover auctions whose entire 70% value migrates beyond the same prior-day value edge, followed by the first causal rebalance to the near edge and delivery to the frozen new POC.

## Event funnel

- loaded market years before gate: `[2021, 2022]`
- 2023 opened: `False`
- total events: `53`
- by year: `{'2021': 22, '2022': 31}`
- by symbol: `{'BTCUSDT': 30, 'ETHUSDT': 23}`

| Symbol | prior profiles | packet pairs | accepted value | edge lost first | rebalance found | POC preconsumed | sub-24bp | final |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 729 | 728 | 119 | 56 | 51 | 18 | 2 | 30 |
| ETHUSDT | 656 | 656 | 108 | 54 | 45 | 15 | 3 | 23 |

## Account paths

| Year | Cost | Completed | Multiple | PF | Median | Daily MDD | Winner-removed | H1 | H2 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 0bp | 22 | 0.925818x | 0.0534 | -0.4611% | 7.77% | 0.921951x | 0.963856x | 0.960535x |
| 2021 | 12bp | 22 | 0.915712x | 0.0318 | -0.4735% | 8.68% | 0.913180x | 0.960102x | 0.953765x |
| 2021 | 18bp | 22 | 0.913741x | 0.0266 | -0.4771% | 8.84% | 0.911593x | 0.959020x | 0.952786x |
| 2021 | 24bp | 22 | 0.912184x | 0.0221 | -0.4799% | 8.96% | 0.910379x | 0.958122x | 0.952054x |
| 2022 | 0bp | 31 | 0.938108x | 0.3968 | -0.4542% | 7.29% | 0.898349x | 0.940110x | 0.997870x |
| 2022 | 12bp | 31 | 0.913707x | 0.2397 | -0.4705% | 9.45% | 0.887193x | 0.933716x | 0.978571x |
| 2022 | 18bp | 31 | 0.907192x | 0.1973 | -0.4749% | 10.05% | 0.884944x | 0.932499x | 0.972861x |
| 2022 | 24bp | 31 | 0.902277x | 0.1664 | -0.4782% | 10.48% | 0.883240x | 0.931568x | 0.968557x |

At 2022/24bp, only `3/31` trades won: 22 hard stops, 6 value-edge state losses and 3 POC targets. Removing those three positive events before complete slot rerouting left 28 losses and `0.883240x`.

## Programization audit

The first complete process was quarantined because it loaded 2023 event inventory before the 2022 gate, despite not using 2023 economics. The final authority loads only 2021–2022 and leaves 2023 unopened. It passed eight synthetic semantic tests, 28 full event/account assertions and two fresh-process byte-identical comparison across 22 scientific output files.

## Interpretation

The state was both too sparse for a steady-compounding Core and negative before non-price cost; execution refinement cannot rescue it. Repeated value formation outside an old auction is stronger evidence than a wick breakout, but the first near-edge rebalance did not prove that the edge was defended or that price would redeliver to the new POC.

Retire the exact packet fraction, profile, first-rebalance action and POC target without packet/profile/entry/target/stop/cost/symbol/ML/risk/leverage rescue. Calendar 2023 and official 2024–2026 remain unopened. No credential or order was used.
