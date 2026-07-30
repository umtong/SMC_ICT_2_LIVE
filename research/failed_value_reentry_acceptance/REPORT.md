# Failed value-reentry outside-acceptance delivery Core — final report

**Status:** `RETIRED_2022_FAILED_VALUE_REENTRY_ACCEPTANCE_FAILURE`

## Logic

The parent prior-day value-area event was kept unchanged. After an outside auction first returned inside value, this paired action waited for the rotation premise to fail: a completed five-minute close reaccepted outside the same frozen VAH/VAL before POC or stop. The outside-acceptance bar became the protected origin and the still-unconsumed prior-day high/low became the external target.

## Causal funnel

- Parent failed-auction events: 2083
- First outside reacceptance found: 1288
- Prior-day external target still live: 852
- Valid entry geometry / resolved actions: 834

## 2022 fatal screen

| Cost | Trades | NAV multiple | PF | Median | H1 | H2 | Winner-deleted multiple |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 bp | 263 | 0.974439x | 0.9617 | -0.2393% | 1.23% | -3.74% | 0.774840x |
| 12 bp | 263 | 0.603446x | 0.4580 | -0.4427% | -20.27% | -24.31% | 0.515276x |
| 18 bp | 263 | 0.537975x | 0.3614 | -0.4556% | -24.96% | -28.30% | 0.470395x |
| 24 bp | 263 | 0.495705x | 0.2956 | -0.4649% | -28.10% | -31.05% | 0.440702x |

At 24 bp the path ended at 4957.05 USDT, geometric daily growth -0.192082%, MDD 50.43%, 28 wins / 235 non-wins, median hold 10.0 minutes. Exit counts were `stop=139`, `inside_reacceptance_state_loss=96`, `prior_day_external_target=28`.

## Programization and interpretation

The exact parent source, profile construction and event tape were reused. Entry starts only after the completed outside-reacceptance bar plus fixed 500 ms, actual funding is applied, same-minute ambiguity is adverse, and one global BTC/ETH slot is enforced. Two fresh complete processes produced byte-identical result, report, action ledger and both 24-bp trade ledgers.

The result is not a sparse-tail failure: 263 completed 2022 trades existed and both half-years lost. More importantly, the action was already negative at zero non-price cost. The reasoning that failed mean-reversion inventory must propel price to the prior-day external target is incomplete; outside reacceptance identifies a trapped cohort but does not prove low resistance or adequate distance to the target.

## Decision

Retire this exact failed-value-reentry acceptance family. Do not rescue with another boundary buffer, acceptance count, profile, target, stop, session, FVG/OB/MSS gate, symbol/side exception, lower cost, ML, risk or leverage. Unchanged 2023 and official 2024–2026 remain unopened. No credentials or orders were used.
