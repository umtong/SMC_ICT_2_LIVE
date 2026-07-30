# Initiative-displacement AVWAP inventory-defense Core

## Identity

- Claim: `CLM-20260730-INITIATIVE-AVWAP-DEFENSE-CORE-001`
- Result: `RES-20260730-INITIATIVE-AVWAP-DEFENSE-CORE-001`
- Decision: `RETIRED_2022_DETERMINISTIC_ECONOMIC_FAILURE`
- Products: Bybit USDT-linear BTCUSDT and ETHUSDT as testbeds
- Orders/credentials: none

## Logic

A completed high-participation displacement through a causally known external liquidity pool creates or attracts a new inventory cohort. The exact completed-interval transaction AVWAP, `sum(turnover)/sum(volume)`, is the cohort's observable aggregate cost basis. The first later AVWAP interaction compares:

- `DEFEND_CONTINUE`: AVWAP is defended and the new cohort remains sponsored;
- `FAIL_UNWIND`: price accepts through AVWAP while aggregate inventory state contracts;
- `FLAT`.

FVG, OB, OTE, session, symbol identity and a fixed channel length are not gates. Entry, state loss and exit follow the same inventory-control premise.

## Frozen account contract

- completed causal pivots and completed 15m/5m states only;
- fixed 500ms activation and first strictly later observed 1m open;
- actual signed funding;
- one global pending/open BTC/ETH slot;
- 0.5% current-NAV planned structural loss and 3x notional cap;
- 0/12/18/24bp diagnostics;
- adverse same-minute stop first;
- no elapsed-time, session, UTC-day or stage-boundary strategy close.

## Programization correction

The preliminary lifecycle used intrabar wick contact with the displacement origin as state loss. That did not represent the intended completed-auction premise. The final rule requires a completed five-minute close through the displacement open against the active premise. This restored the intended event funnel:

- `DEFEND_CONTINUE` events: 17
- `FAIL_UNWIND` events: 127

The correction changed semantic validity but did not restore economic value.

## Untouched 2022 economics

The one-slot full map selected 59 completed trades.

- 24bp full-map ending multiple: approximately `0.8799x`
- 24bp PF: approximately `0.107`
- selected DEFEND trades: 6; wins: 0
- selected FAIL trades: 53
- zero-cost full-map ending multiple: approximately `0.9486x`
- zero-cost FAIL ending multiple: approximately `0.9763x`

The route was therefore negative before modeled round-trip cost. Lower fees, passive execution, risk or leverage cannot rescue the information unit.

## Interpretation

Event AVWAP is a more coherent price reference than an arbitrary candle midpoint, FVG edge or fixed retracement. The fatal limitation is the inventory sensor. Completed-bar total OI and global account ratios do not reveal side-specific opening size, entry-price concentration, hedge relationships or which cohort is closing at the retest.

The next admissible information source must observe executed forced flow and/or executable liquidity refill directly. Another AVWAP band, OI threshold, session, FVG/OB gate, cost relaxation, risk increase, leverage increase or ML filter would repeat the failed rescue pattern.

Calendar 2023, ML, risk/leverage research and official 2024-2026 remained sealed. Ranking and order authority are unchanged.

## Reproducibility disclosure

Two fresh processes produced byte-identical outputs before the interactive runtime reset. The transient exact hash strings were not retained and are not invented here. The draft PR must remain non-merge-ready until the exact runner is recovered or independently reconstructed and rerun. This disclosure does not change the economic decision; it limits source transport completeness.