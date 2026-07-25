# Cross-sectional funding crowding research

## Economic mechanism

Realized perpetual funding is used as a cross-sectional state variable for crowded long/short positioning. The study tests whether relative funding level and change, combined with completed price and true-taker-flow states, predict short-horizon market-neutral returns after the funding publication timestamp.

The strategy does not assume that extreme funding always reverts. It preregisters reversal, continuation, aligned-crowding and price/flow-disagreement families, then freezes only development survivors before opening later periods.

## Causal contract

- Funding is used only after its recorded `calc_time`.
- Price and taker-flow features use the last fully completed one-hour bar before the funding event.
- Entry is the next one-hour open after the event; no event-time open is used.
- Holds are 3h or 6h, shorter than the next regular 8h funding event.
- One market-neutral basket is opened per event; long and short gross weights are each 0.5.
- Missing bars, inadequate prior quote volume, and undersized cross sections are skipped.
- The same raw paths are replayed at 12/18/24bp round-trip costs.

## Stages

- 2021: warm-up only.
- 2022: development grid.
- 2023: opened only for one frozen survivor per economic family.
- 2024: opened only for selection survivors.
- 2025 and later: sealed.

## Promotion boundary

A development or selection result is not sufficient for strategy ranking. Ranking requires hard-valid decision-ready evidence and normalized account-level metrics. No credentials, private endpoints, paper/testnet/live orders, or deployment bundle are used.
