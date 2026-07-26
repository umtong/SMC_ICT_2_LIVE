# ML Uniswap inventory-transfer relay

Claim: `CLM-20260726-2315-ML-UNISWAP-INVENTORY-001`

## Economic mechanism

The Uniswap V3 USDC/WETH 0.05% pool is a large on-chain inventory venue. A completed interval in which WETH-versus-stablecoin inventory is transferred with high volume, transaction breadth and price impact can precede centralized-perpetual hedging and delivery. The same shock can also exhaust when on-chain effort fails to move the Bybit market.

The frozen system therefore separates two SMC/ICT-explainable paths around already-known Bybit external liquidity:

1. **Sponsored delivery:** on-chain WETH inventory pressure and pool-price movement agree while Bybit ETHUSDT has underreacted. The candidate path targets the nearest pre-known external pool in the pressure direction.
2. **Inventory exhaustion:** exceptional on-chain transfer effort produces weak Bybit response or a stretched pool/perpetual basis. The candidate path targets the opposing external pool after a completed structural rejection.

A single pooled HGBT plus one isotonic calibrator estimates target-first probability. Direction, entry, stop, target and exit are owned by the frozen structural rule; the model may only choose the eligible continuation path, the eligible exhaustion path, or flat.

## Causal contract

- Uniswap cumulative block state is differenced only after the block is finalized in the immutable snapshot.
- Ethereum block timestamps come from an independently immutable block table sampled every 25 blocks.
- Every hourly on-chain state becomes usable two complete hours after the hour ends; this dominates timestamp interpolation uncertainty.
- Bybit structural pools use only completed bars and confirmed pivots.
- Entry is the next exact contiguous Bybit bar open after the delayed decision.
- Same-bar target/stop ambiguity is stop-first; an adverse opening gap fills at the opening price.
- No elapsed-time liquidation is permitted. Positions leave only by frozen target, frozen stop, structural invalidation or source-failure handling; evaluation NAV marks open inventory without relabeling it a strategy exit.
- One ETHUSDT pending/open slot; 12/18/24bp identical replay; actual funding when the source is available, otherwise the route is not rank eligible.

## Sequential partitions

- training: 2021-07-01 through 2022-06-30
- calibration: 2022-07-01 through 2022-12-31
- confirmation: 2023-01-01 through 2023-06-30
- development/risk selection: 2023-07-01 through 2023-12-31
- official first interval: 2024H1 only after the complete pre-2024 gate passes

The first workflow is an outcome-sealed source gate. It verifies immutable Uniswap, block-time and Bybit archive identity and coverage but opens no market outcome, model or PnL. A source pass authorizes the already-preregistered model stage; a source failure closes this exact transport without threshold or leverage rescue.
