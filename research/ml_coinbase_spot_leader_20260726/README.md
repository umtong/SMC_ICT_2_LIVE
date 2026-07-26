# ML Coinbase spot metaorder lead into Bybit BTC

Claim: `CLM-20260726-1935-ML-COINBASE-SPOT-001`

## One information unit

This study asks one economic question:

> After a completed burst of aggressive Coinbase `BTCUSD` spot demand or supply, does Bybit `BTCUSDT` reach the same-direction frozen external-liquidity pool before returning to frozen equilibrium?

Coinbase supplies direction. Bybit supplies the tradable market, target and invalidation. ML is not allowed to invent another setup, direction, target, stop, latency, risk rate or leverage.

## SMC/ICT translation

1. The previous complete Bybit fifteen-minute dealing range is frozen.
2. Its high and low are external liquidity; its midpoint is equilibrium.
3. A completed Coinbase aggressive-flow displacement must be materially larger than its own prior 15-minute flow and return scale.
4. Bybit must remain inside the frozen range and underreact in the same direction.
5. After a fixed cross-region relay delay, one calibrated nonlinear model estimates whether Bybit reaches the external-liquidity target before equilibrium.
6. The calibrated probability and actual target/stop distances must clear the full 24-bp cost contract by at least five basis points.
7. Entry is the first executable Bybit ask for a long or bid for a short after the relay delay. Target and stop remain frozen. No elapsed-time liquidation exists.

In trader language, the sequence is:

`real spot displacement -> perpetual SMT/underreaction -> accepted delivery to external liquidity or failure back to equilibrium`

## Deliberate reduction

- BTC only;
- Coinbase trades as signal data;
- Bybit quotes as the execution and account market;
- one HGBT specification;
- ten fixed features;
- one isotonic calibration;
- one EV equation;
- one global slot;
- 500-ms primary relay and 1,000-ms mandatory stress;
- 12/18/24-bp identical paths;
- no feature, model, threshold, barrier, latency, risk or leverage grid.

## Causal chronology

- train: 2022-01-01, 2022-03-01, 2022-05-01;
- calibrate once: 2022-07-01;
- untouched fit confirmation: 2022-09-01, 2022-11-01;
- conditional development: 2023-01-01, 2023-03-01, 2023-05-01;
- every 2024-2026 URL is rejected.

`local_timestamp` is the information-availability clock. Every spot feature is based on a completed one-second interval. Rolling scales are shifted by one interval. Bybit entry occurs only after the completed decision plus the frozen relay delay.

## Economic gate

Conditional development is opened only when both 500-ms and 1,000-ms paths survive the complete fit gate, including:

- prediction and calibration improvement over the exact structural-distance first-passage baseline;
- adequate independent events and trades;
- positive 24-bp mean, median, PF and total return;
- both confirmation dates positive;
- limited winner concentration;
- positive 18-bp winner-removal return;
- at least 1% sample-calendar-day geometric growth at 24 bp after winner removal.

Failure retires the exact information unit without adjacent tuning. A pre-2024 survivor is still research-only and not rank eligible.

## Execution realism

- Bybit BBO is downsampled only to completed 100-ms arrival buckets.
- Entry uses the first quote after the relay delay.
- Long exits use executable bid; short exits use executable ask.
- A quote gap greater than two seconds ends the path with the full structural stop.
- Day-boundary unresolved positions receive the full structural stop.
- Quantity is the minimum of NAV-risk size, 3x notional size and 5% of executable top-quote amount.
- The largest positive 10% of event keys in the primary 12-bp path are removed before complete chronological rerouting.
- No credentials or order endpoint exists.
