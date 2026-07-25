# Evidence decision

Result ID: `RES-20260725-CROSS-ASSET-LEADLAG-001`  
Dataset: `DS-BINANCE-USDM-5M-2023-2025-R1`  
Status: **validated negative; not Champion eligible**

The official-data workflow passed project validation, the causal self-test, all monthly archive CHECKSUM checks, staged execution and artifact hashing. It evaluated 864 one-slot configurations from three economically different families.

No family passed the 2023 development contract at both baseline and 1.5x costs. Therefore the independent 2024 and conditional 2025 stages remained unopened.

Key failure modes:

- **Underreaction continuation** traded frequently but had negative expectancy after costs: 3,160 trades, 8.66/day, −12.19 bp/trade, −0.171R/trade, −0.264R after removing the top 10%, −1.483% geometric daily return and −99.57% drawdown under the diagnostic sizing path.
- **Overreaction reversal** had a positive raw mean in only 24 development trades, but insufficient frequency, a negative top-removal result and negative growth under 1.5x costs.
- **Flow-disagreement reversal** had only 12 trades and negative mean R and top-removal metrics.

Decision: do not tune this completed-bar 5-minute cross-asset family locally. Reuse the registered negative attestation unless the information clock, data granularity, market, execution method or economic hypothesis changes materially.

The complete immutable evidence, canonical snapshots, development grid and file manifest are stored in Drive and referenced by `RESULT_POINTER.json`.
