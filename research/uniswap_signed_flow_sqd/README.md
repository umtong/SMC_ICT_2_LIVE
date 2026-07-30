# Signed Uniswap WETH–stablecoin inventory flow SQD takeover

This branch implements issue #556 and resumes the outcome-sealed source stage of the frozen Uniswap V3 WETH–stablecoin inventory-transfer hypothesis.

The economic information unit is the signed pool balance delta in canonical WETH–USDC and WETH–USDT Uniswap V3 `Swap` events. It is not a chart-pattern, OI, funding, account-ratio or ordinary CEX-print proxy. The original pools, event ABI, six source windows, 120-second information delay, event threshold, 13 model features, chronology, structural first-passage action and fixed small-risk account contract are unchanged from the paused PR #190.

Only transport is repaired:

- bounded keyless JSON-RPC verifies Ethereum chain identity, bytecode and immutable pool semantics;
- SQD Portal `finalized-stream` retrieves historical logs by exact pool address and Swap topic;
- stream pagination resumes from the last returned block;
- identities are `(blockHash, transactionHash, logIndex)`;
- a transport outage is recorded as `SOURCE_UNAVAILABLE_NO_ALPHA_CONCLUSION`, never as negative alpha.

The first workflow is strictly outcome sealed. It opens no CEX price, future return, label, model, trade, PnL or official 2024–2026 interval. A source PASS authorizes the already-frozen pre-2024 history and economic stage; it grants no ranking or live authority.
