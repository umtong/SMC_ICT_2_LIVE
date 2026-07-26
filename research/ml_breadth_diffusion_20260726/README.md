# ML broad-market breadth diffusion into Bybit targets

Claim: `CLM-20260726-2205-ML-BREADTH-DIFFUSION-001` · Issue #217

## Trader-readable route

1. Freeze the target's previous completed 60-minute high, low and equilibrium.
2. Measure a completed five-minute displacement across a fixed set of non-target Binance USD-M perpetuals.
3. Require both return breadth and aggressive taker-flow breadth to point the same way.
4. Require BTC, ETH, SOL or XRP to remain inside its frozen range and lag its prior-only beta response.
5. One calibrated HGBT estimates whether the target reaches the breadth-direction external-liquidity pool before equilibrium.
6. A single 24bp expected-value equation may authorize continuation or remain flat.
7. Entry is the next five-minute open. Target and stop are the frozen structural levels. Time alone never closes a position.

This is a quantitative intermarket SMT/liquidity-delivery test. It contains no FVG, order-block, OTE, session, model, feature, threshold, stop, target, risk or leverage library.

## Economic boundary

The same event ledger is replayed at 12, 18 and 24bp with one global slot, 1% structural-stop risk, 3x notional cap, adverse funding reserve and top-winner exclusion before rerouting. Development remains physically unopened unless the full confirmation gate passes. Every 2024–2026 source is prohibited.
