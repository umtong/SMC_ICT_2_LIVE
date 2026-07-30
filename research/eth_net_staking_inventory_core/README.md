# Ethereum net-staking inventory acceptance Core

This study tests a balance-sheet source that is economically different from aggregate validator withdrawals: ETH recognized as new beacon-chain deposits minus principal-scale ETH released to execution-layer recipients.

The source is built before market outcomes. It downloads every Xatu `canonical_beacon_block_deposit` partition from 2023-04-12 through 2023-12-31, validates amount, timestamp and event identity, then merges the completed-hour deposit stream with the already verified principal-release stream. The source authority requires 264 daily deposit files, 6,314 continuous hours and exact net-amount conservation.

The price policy does not assume `deposit = long` or `withdrawal = short`. The primary net source uses both prior-only lower and upper 720-hour tails. A fixed action-value model compares long, short and flat using the same causal Bybit ETHUSDT account engine as the deposit-only and release-only controls. Positions unresolved at fit/development boundaries are marked, not strategy-closed, and cannot become labels for the next stage.

The evidence is explicitly low-confidence because adjacent validator-flow outcomes for the same 2023 forward months are already exposed. In addition, Xatu documents canonical beacon deposit public files only through 2025-05-14; even a positive pre-2024 diagnostic would require a separately frozen full-period execution-deposit-contract source before a complete 2024-2026 claim.

No credentials or orders are used.
