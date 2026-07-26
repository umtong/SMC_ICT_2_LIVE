# Bybit reserve-wallet external collateral-flow source gate

Claim `CLM-20260726-1710-BYBIT-RESERVE-NETFLOW-001`, issue #118.

This stage reconstructs January 2023 external USDT and USDC transfers involving the four Ethereum addresses published in Bybit's first Proof-of-Reserves-era balance-checker configuration. Internal transfers among those four addresses are excluded.

It reads no market price, future return, model metric, action, trade, PnL or 2024-2026 data. Blockscout is the primary historical log transport; a bounded event-bearing block interval must be reproduced by an independent keyless JSON-RPC endpoint with the same canonical event hash.

A pass authorizes a separately frozen economic contract. A failure closes only this source dependency and is not negative-alpha evidence.
