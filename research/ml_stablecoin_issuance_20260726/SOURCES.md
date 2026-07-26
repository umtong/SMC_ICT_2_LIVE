# Sources

## Empirical motivation

- Saggu, A. (2025), *The Intraday Bitcoin Response to Tether Minting and Burning Events: Asymmetry, Investor Sentiment, And Whale Alerts On Twitter*, arXiv:2501.05232. Reports positive Bitcoin response after USDT minting over 5–30 minute windows and state dependence.
- Chi, Y., Chu, Q., Hao, W. (2024), *Return-forecasting and Volatility-forecasting Power of On-chain Activities in the Cryptocurrency Market*, arXiv:2411.06327. Reports that USDT net inflow into exchanges positively forecasts BTC and ETH returns, strongest at the one-hour frequency.

These papers motivate a direct test but do not supply market outcomes or parameters to this source gate.

## Protocol and contracts

- Ethereum JSON-RPC methods: `eth_chainId`, `eth_blockNumber`, `eth_getCode`, `eth_getBlockByNumber`, `eth_getLogs`.
- ERC-20 `Transfer(address,address,uint256)` topic: `0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`.
- Ethereum USDT contract: `0xdAC17F958D2ee523a2206206994597C13D831ec7`, 6 decimals.
- Ethereum USDC contract: `0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48`, 6 decimals.

A mint is a `Transfer` whose indexed `from` address is zero. A burn is a `Transfer` whose indexed `to` address is zero. Every event is identified by contract, transaction hash and log index and is unavailable until the preregistered confirmation block.

## Keyless transport candidates

The source gate tries the following endpoints in a frozen order and records every failure before selecting one:

1. `https://ethereum-rpc.publicnode.com`
2. `https://eth.llamarpc.com`
3. `https://1rpc.io/eth`
4. `https://rpc.ankr.com/eth`

Endpoint success is transport evidence only. No provider is treated as an authority for market outcomes.
