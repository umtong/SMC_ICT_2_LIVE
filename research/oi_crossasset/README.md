# BTC OI Cross-Asset Causal Screen

Claim: `claim-20260725-001-btc-oi-crossasset`

## Outcome

No valid strategy candidate. The direct open-interest-shock screen produced 0 eligible candidates out of 128, and the materially different sequential shock-to-CISD/reclaim screen produced 0 eligible candidates out of 256. Both used 2022 as development and 2023 as independent selection; 2024 validation and the 2025 conditional holdout remained unopened.

## Information boundary

- completed Binance USD-M five-minute bars only
- latest positioning metric timestamp strictly earlier than decision time
- entry at the next five-minute open
- BTCUSDT and ETHUSDT share one global pending/open slot
- the raw signal and exit path is frozen before base and stressed-cost replay

## Exit contract

Positions close only by protective stop, fixed-R target, post-1R causal trailing structure, or confirmed opposite-flow/structure invalidation. No arbitrary elapsed-time exit is used.

## Result

The fixed-rule BTC open-interest-shock family is invalidated for dependency fingerprint `394466e12a04e46df5fe4c4be8113c5cdc1866123d4df534bb877434c41c6f8d`.

The exact next research start is funding-settlement mechanics using verified BTC/ETH funding-rate, premium-index, and price archives.
