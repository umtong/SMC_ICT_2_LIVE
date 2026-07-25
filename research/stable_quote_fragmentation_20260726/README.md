# Within-Binance stable-quote fragmentation screen

Claim: `CLM-20260726-0553-STABLE-QUOTE-001`  
Branch: `agent/r11-stable-quote-fragmentation-001`

## Economic hypothesis

BTC and ETH trade simultaneously against USDT and, during different historical intervals, BUSD, USDC and FDUSD. The non-USDT prices are not compared naively: each completed base/quote bar is converted into USDT with the exact same completed stablecoin/USDT bar. The screen asks whether residual price and aggressive-flow disagreement across those quote pools represents informed migration that the USDT perpetual subsequently follows, or a temporary isolated move that reverses.

This changes the information source rather than retuning a generic spot/perpetual rule. It also treats quote-listing changes as causal regime boundaries instead of forward-filling an unavailable route.

## Causal and execution contract

- Every feature is computed from a completed 15-minute bar and standardized only against earlier bars within the same exact route-composition segment.
- BUSD, USDC and FDUSD route prices require an exact same-timestamp completed stablecoin/USDT conversion bar; there is no forward fill.
- Entry is the next exact BTCUSDT/ETHUSDT perpetual open.
- At most one global BTC/ETH position exists.
- Position exits are state-defined—convergence, lead closure, migration termination, flow reversal, route change, data gap or adverse stop. There is no fixed holding-time exit.
- Evaluation-boundary marking is used only to value NAV and includes the liquidation cost.
- The same path is replayed at 12, 18 and 24 bps plus actual funding.

## Frozen staging

1. Use December 2021 only as rolling warmup.
2. Evaluate all 108 frozen candidates on 2022-2023.
3. Request 2024 only after a candidate passes every sample, cost, yearly, median, concentration and drawdown gate.
4. Keep 2025-2026 sealed.

A completed negative development screen closes adjacent route-weight, threshold, exit-level, stop, leverage and execution tuning under its dependency fingerprint. Any survivor still requires Bybit-normalized replay before ranking or deployment consideration.
