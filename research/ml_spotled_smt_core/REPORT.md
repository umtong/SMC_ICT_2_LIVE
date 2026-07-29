# Spot-led intermarket SMT Core fatal screen

Claim: `CLM-20260730-ML-SPOTLED-SMT-CORE-TAKEOVER-001`  
Result: `RES-20260730-ML-SPOTLED-SMT-CORE-001`

## Mechanism

This screen tested whether a completed Binance spot one-second acceptance through a causally confirmed 15-second external pivot precedes a tradable Bybit perpetual delivery.

The implementation does **not** compare Tardis provider `local_timestamp` values across Binance and Bybit. The Binance event is completed on exchange time, followed by a fixed conservative two-second cross-provider availability delay and the project-fixed 500ms order latency. Entry is the first later retained Bybit 100ms BBO.

The Bybit target is the nearest still-unconsumed, confirmed 60-second same-side external pivot; the stop is the nearest confirmed opposite 15-second internal pivot. The account uses fixed 0.5% current-NAV planned loss, a 3x notional cap, one global slot and no elapsed-time liquidation.

## Programization audit

Before the outcome run, the following defects were corrected without changing the economic hypothesis:

1. The stale issue #147 would have encouraged direct comparison of different provider-local capture clocks. The takeover replaces that with exchange time plus a fixed two-second source delay.
2. The portable runtime artifact manifest contained an `artifact/` packaging prefix absent after extraction. The workflow now verifies the immutable ZIP and runtime tar hashes directly.
3. The Bybit artifact input manifest referenced source-code paths absent from the output ZIP. The workflow now verifies the registered ZIP SHA-256 and every internal output using its own `SHA256SUMS.txt`.

Five focused tests passed: delayed pivot availability, source delay plus order latency, adverse same-state handling, exit-bucket slot blocking and exclusion of provider-local timestamps from the feature contract.

## Source and event breadth

| Stage | Spot seconds | Spot acceptance events | Bybit structural candidates | Bybit states |
|---|---:|---:|---:|---:|
| 2022-07-01 fit | 83,199 | 914 | 126 | 863,401 |
| 2023-07-01 forward | 78,141 | 614 | 196 | 835,851 |

The forward day had enough raw events to test the economic mechanism, but only 49 one-slot actions were selected by deterministic chronology because earlier positions occupied the slot.

## Economic result

The forward candidate surface had mean gross movement **−0.0493bp**. The strict one-slot ledger had mean gross movement only **+0.0762bp** per routed trade—far below even the 12bp adverse cost path.

| Cost | Trades | Final NAV | Return | PF | MDD | Median account return |
|---:|---:|---:|---:|---:|---:|---:|
| 12bp | 49 | 8,663.09 | −13.37% | 0.000 | 13.37% | −23.31bp |
| 18bp | 49 | 8,439.40 | −15.61% | 0.000 | 15.61% | −28.65bp |
| 24bp | 49 | 8,330.90 | −16.69% | 0.000 | 16.69% | −32.38bp |

At 24bp there were 21 structural-stop exits, 27 target exits and one unresolved boundary mark. Even target exits were too small to cover realistic cost, so all completed account actions were non-positive and PF was zero.

Both UTC half-days lost money at every cost. Winner deletion removed no event because there were no positive 24bp account winners.

## ML decision

ML was not opened. The fit stage contained 126 resolved or marked actions, below the frozen 200-row model-estimation minimum. More importantly, the forward gross headroom was already negative and the deterministic account failed at all costs.

Training a more complex model on this information unit would either choose no trades or select a small noisy subset. It would not repair the missing economic movement.

## Verdict

`RETIRED_SUBCOST_GROSS_HEADROOM` / `SPOT_LEAD_ASSOCIATION_TOO_SMALL_FOR_REALISTIC_COST`.

The exact spot-led structural delivery unit is retired. Do not rescue it with a shorter source delay, smaller pivot, different target, probability threshold, lower cost, greater risk or leverage. The failure is at gross price-delivery magnitude before model complexity.

Calendar 2024–2026 remained unopened. Ranking and live-order permission are unchanged. No credentials, paper orders or live orders were used.

## Durable evidence

- workflow run: `30483480739`
- workflow artifact: `8736653513`
- artifact ZIP SHA-256: `23c7c0b29ff12195480d16d57a281fc8e761e8b1d4453912d546ac7a9bb22fd6`
- immutable Bybit dependency artifact: `8626087323`
- Bybit artifact ZIP SHA-256: `90594acc23e63e97e83347f9b07eb9ac260ba7bb1b87eb72052287a8328ad4a1`
- Binance spot 2022 source SHA-256: `228d3c77cfa924620255836aac8e6ec8cf8fe4ba91a22130d0ed56db4da45846`
- Binance spot 2023 source SHA-256: `8e466a4e0fe8bed6c661fa8b35b34f7f2c0d6a004760514d73980628670e6b52`
