# RUN-20260725-2045-CROSSVENUE-FWD-001 — cross-venue recovery and forward evidence layer

## Current first place

`FIRST-20260725-DYNAMIC-STATE-021FBAB6` remains the provisional strategy first place. Its 12 bp geometric daily growth is 0.0573077%, 12/18/24 bp total returns are +23.2585%/+16.7170%/+11.2649%, maximum drawdown is 4.6174% and it has 194 trades. It remains exploratory because top-10%-removed return and median trade are negative, frozen 2024 family portfolios lost, and no deployment permission exists. This run does not challenge or modify that rank.

## Identifiers

- Claim: `CLM-20260725-2045-CROSSVENUE-FWD-001`
- Historical result: `RES-20260725-2045-CROSSVENUE-HIST-001`
- Forward component: `RES-20260725-2045-CROSSVENUE-FWD-COMP-001`
- Base revision: `9`
- Clean branch: `agent/r8-crossvenue-forward-evidence-final-001`
- Pull request: `https://github.com/umtong/SMC_ICT_2_LIVE/pull/45`

## Scope and reuse

The run reused the successful Phase 35 artifact rather than rebuilding its 101 MB panel and reused the merged L1 execution-routing component. It does not overlap active spot/perpetual, flow-size-impact, positioning, COIN-M, DVOL, L2-maker or price-discovery claims.

## Historical strategy result

The recovered snapshot covers BTC on Binance Futures, Bybit and OKX from 2026-07-14 through 2026-07-23. It contains 843,634 one-second rows, 89 Bybit liquidation events and 21,200 candidate rows.

The evaluation replayed 7,760 original continuation, reclaim and venue-transfer policies plus 680 low-dimensional mechanism policies. Decisions used fixed confirmation delays and information available by each decision second; entries and exits used the next observed bid/ask; one global position was enforced; 8, 12, 16, 20 and 24 bp costs and top-trade-removal gates were applied.

Result: zero strict and zero exploratory survivors. The tested specification is valid negative evidence, not a first-place challenge.

## Forward evidence component

The readable source implements observation-only Binance/Bybit public capture and Bybit private execution/order/position evidence primitives with local wall and monotonic receive timestamps, raw payload hashes, append-only chain hashes, sequence and clock checks, environment-only authentication, execId-authoritative reconciliation, exact-capture-prefix dynamic-gate versus always-taker Shadow A/B and automatic risk-state mapping.

The implementation passed 22 tests, per-file SHA-256 and byte-size manifest verification, and compileall locally. It contains no order-placement path, no credentials and no prospective observations.

## Decision

- Historical cross-venue strategy specification: `TESTED_BELOW_GATE`.
- Forward evidence implementation: `CANDIDATE` pending real observations.
- Strategy first place: unchanged.
- Live permission and account risk: unchanged.

## Remaining evidence

1. At least 30 days of local-receive-time Binance and Bybit BTC/ETH public capture.
2. Private execution, order and position streams from the same Shadow account.
3. Actual fee, partial-fill, queue and post-fill markout calibration.
4. Exact-prefix Shadow A/B for the merged dynamic maker/taker gate and active alpha signals.
5. A separate validation cycle before any Paper or Live decision.
