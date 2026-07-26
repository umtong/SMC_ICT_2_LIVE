# Sources

## Empirical motivation

- Saggu, A. (2025), *The Intraday Bitcoin Response to Tether Minting and Burning Events: Asymmetry, Investor Sentiment, And Whale Alerts On Twitter*, arXiv:2501.05232. Reports positive Bitcoin response after USDT minting over 5–30 minute windows and state dependence.
- Chi, Y., Chu, Q., Hao, W. (2024), *Return-forecasting and Volatility-forecasting Power of On-chain Activities in the Cryptocurrency Market*, arXiv:2411.06327. Reports that USDT net inflow into exchanges positively forecasts BTC and ETH returns, strongest at the one-hour frequency.

These papers motivate a direct test but do not supply market outcomes or parameters to this source gate.

## Protocol, contracts and token-specific supply events

- Ethereum JSON-RPC methods: `eth_chainId`, `eth_blockNumber`, `eth_getCode`, `eth_getBlockByNumber`, `eth_getLogs`.
- ERC-20 `Transfer(address,address,uint256)` topic: `0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`.
- Ethereum USDT contract: `0xdAC17F958D2ee523a2206206994597C13D831ec7`, 6 decimals.
- Ethereum USDC proxy contract: `0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48`, 6 decimals.
- Tether's verified `TetherToken` implementation defines `Issue(uint256)` and `Redeem(uint256)` as the supply-change events emitted by `issue()` and `redeem()`. It does not emit zero-address ERC-20 `Transfer` from those functions.
- USDT `Issue(uint256)` topic: `0xcb8241adb0c3fdb35b70c24ce35c5eb0c17af7431c99f827d44a445ca624176a`.
- USDT `Redeem(uint256)` topic: `0x702d5967f45f6513a38ffc42d6ba9bf230bd40e8f53b16363c7eb4fd2deb9a44`.
- Circle's FiatToken implementation is ERC-20 compatible and its canonical mint/burn path emits zero-address `Transfer`; USDC therefore retains the zero-address Transfer definition.

USDT mint/burn amounts and USDC Transfer values are decoded from the non-indexed `uint256` data field. Every event is identified by canonical contract, transaction hash and log index and remains unavailable until the frozen confirmation block. Ordinary USDT transfers are explicitly excluded from the supply-event population.

## Keyless transport candidates

The retired generic RPC transport tried the following endpoints but is no longer authoritative after the token-specific USDT event-schema correction:

1. `https://ethereum-rpc.publicnode.com`
2. `https://eth.llamarpc.com`
3. `https://1rpc.io/eth`
4. `https://rpc.ankr.com/eth`

The active authority is the Blockscout Ethereum per-instance API, queried only for pre-2024 source identities. Endpoint success is transport evidence only. No provider is treated as an authority for market outcomes.
