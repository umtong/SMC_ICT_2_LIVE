# Aave finalized liquidation Blockscout source gate

Claim: `CLM-20260727-0010-ML-AAVE-BLOCKSCOUT-001`

This route reopens the distinct Aave V2/V3 forced-flow information unit after the earlier keyless JSON-RPC transport failed before outcomes. It does **not** reuse or reinterpret that transport result as alpha evidence.

The new source is Ethereum Blockscout's historical log API under a fail-closed response contract. It queries the canonical Aave V2 and V3 Pool addresses and the canonical `LiquidationCall(address,address,address,uint256,uint256,address,bool)` event on seven dates frozen by the original preregistration.

Source pass requirements are fixed before queries:

- Ethereum identities match the pinned Aave address-book release;
- every returned log decodes under the frozen ABI;
- duplicate `(blockHash, transactionHash, logIndex)` identities are absent;
- at least four of seven dates contain events;
- at least 25 events total;
- both Aave V2 and V3 appear;
- every event receives a block timestamp and `+120s` availability time.

No ETH/BTC price, future return, label, model metric, action, trade, PnL, 2024-2026 interval, credential or order is opened. A pass immediately authorizes the already-defined full 2021-2023 history and one-HGBT economic stage, corrected so unresolved partition-boundary exposure is marked rather than synthetically closed. A failure closes only this Blockscout dependency.
