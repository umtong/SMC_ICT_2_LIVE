# Broad-universe flow diffusion ML

## Profit mechanism

A coordinated return and aggressive-buying wave across a causally frozen universe of liquid Binance USD-M perpetuals is treated as external inventory pressure. The system does **not** trade the already-completed market move. It searches the four allowed Bybit instruments for a lagging instrument whose latest completed bar has underreacted to that broad wave.

The direction is rule-owned by the sign of the external diffusion state. A single pooled HGBT plus isotonic calibration may only accept or skip the trade. Entry is the next 15-minute open. The target is the pre-known prior-24-hour external liquidity extreme in the direction of delivery; the stop is the opposite recent internal range extreme. Target, stop, direction and global-slot arbitration are not selected by the model.

## Causal sequence

1. Use 2021H1 only to rank long-lived candidate contracts by coverage and median daily quote volume.
2. Freeze the selected universe.
3. Train on 2021H2-2022.
4. Calibrate on 2023H1.
5. Confirm and, only after the base 24-bp account gate, select risk/notional cap on 2023H2.
6. Freeze the complete route at 2023-12-31.
7. Open official 2024H1 immediately without feature, model, threshold, target, stop, cost, risk or leverage changes.

All rolling normalizers are shifted by one completed bar. Entry is the next bar open. Same-bar target/stop ambiguity is stop-first, adverse gaps fill at the open, and no elapsed-time liquidation exists. One global pending/open slot is enforced. The initial run is a Binance USD-M completed-bar execution proxy; exact Bybit BBO/depth/funding remains mandatory before deployment.

## Decision gate

At 24 bps, the 2023H2 base path must have positive geometric growth, at least 40 completed trades, positive median trade, PF above 1.2, MDD below 60%, and a positive exact top-10%-winner-removal rerun. Only then may the fixed risk/notional-cap search run and official 2024H1 open.
