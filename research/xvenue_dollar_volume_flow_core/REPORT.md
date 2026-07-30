# Cross-venue dollar-volume flow acceptance/rejection Core

**Result:** `RES-20260730-XVENUE-DOLLAR-VOLUME-FLOW-CORE-001`  
**Verdict:** `RETIRED_2022_DOLLAR_VOLUME_FLOW_BASE_FAILURE`  
**ML / 2023 confirmation / official 2024–2026:** unopened  
**Orders:** none

## Question

The test replaced fixed-time order-flow bars with a fixed **dollar-volume clock**. A Binance packet containing urgent signed taker flow was followed by the next equal-dollar-volume response packet. Same-direction flow and price retention represented acceptance; opposite flow and material price reclaim represented rejection. Execution remained on canonical Bybit with one global BTC/ETH slot.

This is not a prior-day liquidity-level filter, quarter-hour effect, OI-sign classifier or same-symbol price lead/lag rule. The information source is external aggressive inventory transfer measured in market time.

## Frozen source and state

Registered sources were reused without reacquisition:

- `DS-BINANCE-USDM-BTCETH-1M-202110-202212-AW1`;
- canonical Bybit BTCUSDT/ETHUSDT one-minute prices and exact signed funding.

Calendar 2021Q4 froze the complete contract:

| Symbol | Packet quote-volume target | Absolute flow q90 | Calibration packets | 2022 packets | Median packet duration |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 456,180,644.84 USDT | 0.139174 | 2,649 | 9,122 | 45 min |
| ETHUSDT | 212,832,883.28 USDT | 0.131647 | 2,582 | 11,297 | 40 min |

The 2022 event inventory contained 1,390 decisions and 1,229 executable action rows:

- `ACCEPT_CONTINUE`: 920;
- `REJECT_REVERSE`: 309;
- BTCUSDT: 489;
- ETHUSDT: 740.

## Account result

Fixed 0.5% current-NAV planned loss, 3x cap, actual funding, fixed 500ms activation, adverse ambiguity and no elapsed-time exit were applied.

### One-slot union

| Cost | Ending NAV | Multiple | Trades | PF | Median notional return | Trade-close MDD | Winner-deleted multiple |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 bp diagnostic | 11,642.33 | 1.1642x | 612 | 1.109 | -0.4746% | 13.27% | — |
| 12 bp | 8,987.47 | 0.8987x | 612 | 0.925 | -0.5946% | 22.16% | 0.7727x |
| 18 bp | 8,045.00 | 0.8045x | 612 | 0.849 | -0.6546% | 25.82% | 0.6696x |
| 24 bp | 7,271.10 | 0.7271x | 612 | 0.781 | -0.7146% | 29.05% | 0.6062x |

At 24 bp both halves lost: H1 approximately `0.9620x` and H2 approximately `0.7559x`. The top five winners supplied only 3.51% of positive PnL. The failure is therefore not a few-winner concentration problem; it is broad sub-cost churn.

### Competing actions at 24 bp

| Action | Ending NAV | Trades | PF | Median | Winner-deleted multiple |
|---|---:|---:|---:|---:|---:|
| Acceptance continuation | 8,341.53 | 458 | 0.855 | -1.0931% | 0.7144x |
| Rejection reversal | 7,688.19 | 296 | 0.265 | -0.0691% | 0.7501x |

The reversal action had a positive zero-cost median and the union had a positive zero-cost account, but neither had enough gross headroom to survive even 12 bp. Acceptance continuation had a strongly negative median because many accepted packets later lost state or hit the structural stop.

## Programization audit

Six focused tests cover:

1. source gaps restart the dollar-volume packet rather than bridging missing time;
2. fixed 500ms activation cannot fill at the decision timestamp;
3. stop wins same-minute stop/target ambiguity;
4. a state-loss minute exits at its observable open, with adverse gap-stop priority;
5. round-trip cost enters planned loss and realized PnL exactly once;
6. winner deletion rebuilds the entire global slot rather than subtracting selected profits.

Two fresh full executions produced byte-identical `RESULT.json`, `EVENTS_2022.csv` and `RESOLVED_ACTIONS_2022.csv`.

A preliminary development script had also materialized 2023 rows before the 2022 gate. Those rows were quarantined and are not confirmation evidence. The final authority hard-cuts all signal, execution and funding data at `2023-01-01 00:00 UTC`.

## Decision

Dollar-volume time makes the flow event dense and removes fixed-clock dilution, but the causal response rule supplies only a small zero-cost tendency. Realistic execution cost overwhelms it. ML would merely select a subset of a negative base surface, so it remains closed.

Do not rescue this family with another packet size, flow quantile, response fraction, fixed-time bar, target, stop, session, side subset, risk, leverage or SMC condition. The result adds one reusable lesson: **external aggressive flow can describe acceptance and rejection without supplying enough price displacement to pay a marketable Bybit round trip.**
