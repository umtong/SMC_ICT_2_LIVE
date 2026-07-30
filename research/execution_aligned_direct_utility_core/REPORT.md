# Execution-aligned direct-utility Core result

## Decision

`RES-20260730-EXEC-ALIGNED-DIRECT-UTILITY-CORE-001` is **positive Core evidence but below the project target**. It is not a live candidate and does not replace the higher-growth Expansion ranking. It is useful as the current execution-aligned, low-concentration Core component.

## Why this path exists

Prior local action-value paths trained on a price/outcome contract that did not exactly match the account fill. This implementation keeps a regular UTC grid, invalidates state history after missing observations, and generates the ML label from the same entry, barrier, funding, cost and slot contract used by the account simulator.

## Frozen pre-2024 selection

The q-grid was opened on a continuous 2022-2023 account at fixed 0.5% planned loss and 3x notional cap. The selected `q=0.985` path produced:

- 2022: **+17.0803%**, 385 trades, PF 1.1473; top-five deletion and reroute **+16.5156%**.
- 2023: **+9.0512%**, 79 trades, PF 1.4745; top-five deletion and reroute **+8.3349%**.
- 24bp stress remained positive in both years and after exact winner rerouting.

Duration-adjusted targets `net_r/duration^0.25` and `net_r/duration^0.50` were compared under the same frozen gate and rejected; neither exceeded the original model's worst-year winner-rerouted growth.

## Continuous 2024-2026 result

At 15bp plus actual funding:

- start/end NAV: **10,000 → 11,537.85 USDT**
- multiple: **1.1538x**
- geometric daily growth: **0.01569%**
- maximum liquidation-value drawdown: **8.97170%**
- completed trades: **685**
- PF: **1.0763**
- mean cost-net R: **0.0450R**
- median/mean hold: **160/319.4 minutes**
- slot active time: **16.65989%**
- top-1/top-5/top-10 positive-PnL share: **0.38151% / 1.88346% / 3.70167%**

Half-year returns:

- 2024H1: **-1.03347%**, 119 trades
- 2024H2: **3.58254%**, 116 trades
- 2025H1: **11.49490%**, 191 trades
- 2025H2: **-0.95813%**, 118 trades
- 2026H1: **1.92392%**, 141 trades

Exact deletion followed by complete global-slot rerouting:

- top 1: 1.1538x, 0.01568%/day
- top 5: 1.1383x, 0.01421%/day
- top 10: 1.1376x, 0.01414%/day
- top 10% of positive trades: 1.1016x, 0.01061%/day

The low concentration and positive top-10%-rerouted path show that this is not a few-jackpot strategy. However, 2024H1 and 2025H2 were negative and the 24bp full path ended at 0.9500x. The edge is therefore weak and cost-sensitive.

## Economic diagnosis

The result is a repeatable but small Core:

- 685 trades over 912 days, but only 16.65989% of the global-slot minutes were occupied.
- The 15bp mean edge is only 0.0450R per trade.
- 18bp stays positive at 0.00829%/day; 24bp turns negative at -0.00562%/day.
- It is far from 1%/day and must not be rescued by risk or leverage.

Preserve it as a Core component and seek economically independent sources or execution improvements. The volume-sponsored channel is not an immediate Core complement: the later robust-risk audit found a median hold above 42 hours and that all <=48-hour trades lost, so it remains a long-hold Expansion tail rather than daytrading compounding.

## Reproduction

Set `DIRECT_CORE_DATA_ROOT` to the extracted canonical Bybit root and `DIRECT_CORE_OUTPUT_ROOT` to a writable directory. Compile `first_hit.cpp`, build states/outcomes, train annual models, run `evaluate_direct_core.py`, then `validate_direct_core.py`. No data reacquisition is performed.
