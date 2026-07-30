# Failed developing-value migration rotation Core — fatal screen

## Decision

`RES-20260730-FAILED-DEVELOPING-VALUE-ROTATION-001` is `RETIRED_2022_FAILED_DEVELOPING_VALUE_ROTATION_FAILURE`.

BTCUSDT and ETHUSDT were only testbeds. The parent state required two completed equal-turnover packets to establish their full 70% value outside the same frozen prior-day value edge. This audit traded the explicit opposite hypothesis: the first later completed five-minute close through the near edge means the outside value failed, traps inventory established there, and may rotate first to the old value edge or the old POC.

## Programization corrections before verdict

Two preliminary defects were quarantined before the final tape:

1. the hard stop was initially written outside `new_VAH/new_VAL`, even though value-area edges may already have been traded through. The final stop is one basis point beyond the full causal packet-1-start-to-failure-decision excursion;
2. target freshness was initially checked only in the failure bar. The final route cancels an action when the old-value target was touched at any completed minute from migrated-state availability through the failure decision.

The full event/action/account tape was rebuilt after both corrections. Six semantic tests passed. Two fresh complete processes produced all 42 scientific output files byte-identically.

## Event funnel

| Symbol/year | Migrated states | Failed states | Old-edge actions | Old-POC actions |
|---|---:|---:|---:|---:|
| BTC 2021 | 46 | 39 | 32 | 39 |
| ETH 2021 | 47 | 44 | 35 | 44 |
| BTC 2022 | 59 | 53 | 42 | 53 |
| ETH 2022 | 63 | 56 | 50 | 56 |

The failure was not caused by event scarcity.

## 2022 fixed-small-risk account

| Action | Cost | Trades | NAV | PF | Median | H1 | H2 | Winner-deleted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Old edge | 0bp | 85 | 1.013260x | 1.4676 | -0.0146% | 1.005246x | 1.007972x | — |
| Old edge | 12bp | 85 | 0.995241x | 0.8806 | -0.0324% | 0.994947x | 1.000295x | — |
| Old edge | 24bp | 85 | 0.979407x | 0.5897 | -0.0491% | 0.985840x | 0.993475x | 0.967631x |
| Old POC | 0bp | 101 | 1.029056x | 1.7523 | -0.0212% | 1.016122x | 1.012728x | — |
| Old POC | 12bp | 101 | 1.006004x | 1.1122 | -0.0385% | 1.004474x | 1.001524x | — |
| Old POC | 24bp | 101 | 0.986019x | 0.7906 | -0.0528% | 0.994187x | 0.991785x | 0.951303x |

At 24bp, old-edge rotation made 21 winning trades versus 61 state-loss exits and 24 target exits. Old-POC rotation made 18 winning trades versus 83 state-loss exits and 18 targets. Both half-years, the median trade and exact winner-deletion routes failed.

Calendar 2021 was also negative even before non-price cost for both actions.

## Interpretation

Repeated outside value followed by near-edge loss contains a weak gross rotation tendency, especially toward the old POC. It is not a robust day-trading Core. The first loss of the new-value edge does not identify enough vulnerable outside inventory, nor does it prove that old-value equilibrium can be reached with cost-scale headroom before the market reaccepts migrated value.

The continuation and failed-acceptance sides of this exact developing-value event are now both closed. Do not rescue with profile bins, packet fraction, value percentage, failure count, target, stop, cost, symbol/side, session, FVG/OB/MSS gates, ML, risk or leverage. Calendar 2023 and official 2024-2026 remain unopened. No credentials or orders were used.
