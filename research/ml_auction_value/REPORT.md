# ML causal auction-value acceptance and rejection — decision report

**Result:** `RES-20260729-ML-AUCTION-VALUE-001`  
**Claim:** `CLM-20260729-ML-AUCTION-VALUE-001` / issue #387  
**Decision:** **ECONOMIC FAIL**; official 2024 was not opened.

## Mechanism tested

Each UTC day used only the completed prior UTC day's official Bybit one-minute bars to construct a turnover-at-price profile. Turnover was distributed uniformly over each observed minute range on a fixed log-price grid. The resulting POC, 70%/80% value edges, high-volume nodes, and low-density corridors were frozen for the current decision day.

A completed five-minute close through a value edge created two counterfactual actions:

- **acceptance continuation** through the adjacent low-density corridor toward the next profile node, with exit on value re-entry, completed trailing-structure loss, node delivery, or structural stop;
- **rejection reversion** toward POC, with exit on POC delivery, re-acceptance outside value, or structural stop.

Pooled gradient-boosted mean and 35th-percentile value models compared continuation, reversion, and flat. No elapsed-time liquidation was used.

## Fixed execution and account contract

- BTCUSDT and ETHUSDT; one global pending/open slot.
- Completed five-minute decisions; fixed 500 ms activation delay; first observable one-minute open after activation.
- 24 bp round-trip execution stress plus actual canonical Bybit funding.
- Stop-first same-minute ambiguity and adverse gap execution.
- Fixed 0.5% NAV loss budget and 3x notional cap during alpha discovery.
- Simultaneous BTC/ETH candidates compete by predicted action value rather than symbol order.

## Causality correction before final publication

The first exploratory calculation was discarded after audit found three implementation defects:

1. the annual stage used bar-start year rather than the year in which the completed bar became available;
2. a late-year counterfactual outcome could resolve using the next development year's state;
3. simultaneous BTC and ETH candidates were ordered alphabetically instead of by expected action value.

The corrected implementation partitions on `available_at_ms`, resolves or marks every action no later than the next UTC year boundary, contains no future outcome columns in the feature table, and arbitrates the global slot by predicted value. Four unit tests and the result validator passed; all preliminary positive figures are invalid and are not reported as evidence.

## Corrected economic result

The primary 5 bp / 70% profile produced 11,177 value-edge events and 20,615 valid action outcomes. Both raw action families were negative after 24 bp and actual funding:

| action | year | outcomes | mean account return | median account return | positive fraction |
|---|---:|---:|---:|---:|---:|
| continuation | 2021 | 2,980 | -0.2278% | -0.4997% | 16.48% |
| continuation | 2022 | 3,615 | -0.2729% | -0.4998% | 12.59% |
| reversion | 2021 | 2,835 | -0.2474% | -0.4999% | 15.03% |
| reversion | 2022 | 3,524 | -0.3032% | -0.4999% | 14.81% |

Five profile/stop configurations and four model gates produced 20 causal 2022 policy routes. Ten routes selected no trades. None produced positive non-sparse growth.

The best route that actually traded was still negative:

- 5 bp grid, 80% value area, 0.25 ATR stop buffer, 12-bar structural trail;
- blended mean/lower-tail gate;
- 19 trades;
- NAV 10,000 → 9,775.51;
- return **-2.2449%**;
- geometric daily growth **-0.006220%**;
- PF **0.701**;
- MDD **5.63%**;
- median account return **-0.4998%**;
- top-five positive-PnL share **100%**.

The best dense policy was much worse:

- 398 trades;
- NAV 10,000 → 4,753.63;
- return **-52.4637%**;
- geometric daily growth **-0.20354%**;
- PF **0.532**;
- MDD **52.84%**;
- median account return **-0.4997%**.

## Decision

No 2022 policy survived, so the corrected protocol did not open a frozen 2023 confirmation, official 2024H1, risk/leverage optimization, ranking changes, or order authority. Raw 2023 action outcomes had already been exposed during debugging, but were not used to select or rescue this family.

The causal prior-day turnover profile did not create a stable cost-surviving advantage at the value edge. ML could choose broad losses, a small losing tail, or no trade. The exact family is closed. Any next study must change the economic source of alpha rather than narrow the profile, add confirmation gates, relax execution costs, or increase leverage.
