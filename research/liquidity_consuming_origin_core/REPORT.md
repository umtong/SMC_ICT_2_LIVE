# Liquidity-consuming protected-origin first-return Core

**Result:** `RES-20260730-LIQUIDITY-CONSUMING-ORIGIN-CORE-001`  
**Decision:** `RETIRED_2022_SPARSE_TAIL_DEPENDENT_PROTECTED_ORIGIN_FAILURE`

## Logic tested

BTCUSDT and ETHUSDT were testbeds for one general SMC/ICT control-transfer proposition: an origin is economically meaningful only when it is formed while consuming already-known external liquidity. A one-use prior-day, prior-week or confirmed 4h pool was raided and rejected; the first reversal displacement through causal 15m internal structure established the body of the last actual opposite candle as the protected origin. Only its first later return was eligible, and the frozen raid extreme invalidated the premise.

The two registered actions were a one-tick-through midpoint limit and the first completed 5m response that overlapped the origin and closed back in the delivery direction. Both targeted the nearest still-unconsumed external draw known before entry. Actual funding, fixed 500 ms activation, one global slot, 0.5% current-NAV planned loss, 3x cap, 12/18/24 bp and no elapsed-time close were retained.

## Programization audit

Three material sequencing boundaries were corrected before the final decision:

1. an intraminute passive fill cannot receive a favorable target from a high or low that may have occurred before the fill;
2. a response entry cannot claim a target already consumed in its exact entry minute;
3. unresolved year-end exposure is marked with funding and retains the slot; it is not a strategy close, completed trade or winner.

Five semantic tests passed. Two fresh complete executions produced every common scientific output byte-identically.

## Event population

| Symbol | Live pools | Consumed pools | Protected-origin candidates | 2021 body/ATR boundary |
|---|---:|---:|---:|---:|
| BTCUSDT | 8,039 | 7,740 | 17 | 0.403587 |
| ETHUSDT | 7,708 | 7,509 | 16 | 0.415560 |

The final 2022 population contained only 33 distinct origin narratives. This is not enough to support a frequent Core unless the per-event economics are broad and concentration-resistant.

## Raw action surface

| Action | Candidates | Fills | Mean gross | Median gross |
|---|---:|---:|---:|---:|
| MIDPOINT_LIMIT | 33 | 23 | -18.37 bp | -47.11 bp |
| FIRST_RESPONSE | 14 | 14 | +21.25 bp including year-end mark | -39.46 bp on completed outcomes |

## 2022 one-slot account

| Action | Cost | Selected | Completed | NAV | PF | Median | H1 | H2 | Exact positive-event deletion / full reroute |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MIDPOINT_LIMIT | 24 bp | 20 | 20 | 1.005719x | 1.103 | -0.1794% | -2.23% | 2.87% | 0.945797x |
| FIRST_RESPONSE | 24 bp | 13 | 12 + 1 mark | 0.993595x | 0.727 | -0.1429% | -1.48% | 0.85% | 0.982412x |

The only ordinary-positive principal path, MIDPOINT_LIMIT, contained exactly two profitable trades and eighteen losing trades. Those two trades supplied all positive PnL. Removing them before complete slot rerouting left eighteen losses, PF zero and NAV `0.945797x`. FIRST_RESPONSE was sparse and ordinary-negative at 12, 18 and 24 bp.

## Logic diagnosis

This implementation is substantially closer to the source logic than an arbitrary last-opposite-candle order block. Nevertheless, chart-observed liquidity consumption and displacement still do not prove who owns the new inventory or who will defend the origin. The event does not directly observe resting replenishment, a forced position cohort, side-specific opening cost basis or sponsorship. The two positive midpoint trades are compatible with occasional large delivery, but not with a repeatable day-trading Core.

The exact family is retired. Do not rescue it with alternate body definitions, FVG/OTE/session gates, pool-source or symbol-side exceptions, another target/stop, lower costs, ML, risk or leverage. Calendar 2023 and the official period remain sealed.

No credentials, paper orders, testnet orders or live orders were used.
