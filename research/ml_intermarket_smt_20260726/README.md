# ML intermarket SMT / external-risk impulse research

Claim: `CLM-20260726-1740-ML-INTERMARKET-SMT-001`

## One mechanism

A synchronized shock in the U.S. technology and broad-equity indices can transmit through global risk appetite before BTC or ETH has completed the same liquidity delivery. In SMC/ICT language, the external market has already displaced while crypto still shows intermarket SMT and remains between two causally confirmed external-liquidity pools.

This study asks one question:

> After completed Dukascopy USA 100 Technology and USA 500 one-minute bars show a same-direction standardized shock, and BTC or ETH has materially underreacted, does one nonlinear model identify whether the shock-direction external-liquidity pool will be reached before the opposite pool?

It is not a library of SMC entries. The external shock, lag requirement, twelve features, one model, one calibration map, one cost-adjusted authorization rule and all account rules are frozen before results are read.

## Causal clock

- Dukascopy one-minute timestamps are treated as bar-open timestamps and become usable only one minute later, after completion.
- The synchronized risk impulse uses only completed `USATECHIDXUSD` and `USA500IDXUSD` bid bars.
- Bybit decisions occur at the same completed-information boundary and can enter only at the next Bybit one-minute open.
- A Bybit 15-minute pivot is usable only after two completed bars to its right.
- The nearest still-unreached upper and lower pools are frozen before entry.
- A minute touching both pools is excluded from model fitting and is a stop-first loss in account replay.
- A source gap terminates the label scan. An accepted unresolved position pays its full structural stop at the available boundary.
- There is no elapsed-time liquidation.

## Frozen information unit

An event exists only every fifth minute when:

1. the two external indices have same-sign five-minute returns;
2. each five-minute move is at least 1.25 prior-standard deviations;
3. the signed standardized BTC or ETH response trails the common risk impulse by at least 0.75;
4. causally confirmed upper and lower Bybit liquidity pools remain available;
5. the structural width is between 0.75 and 10 prior 15-minute ATRs; and
6. the symbol has not emitted another event during the previous 15 minutes.

The exactly twelve model features are the one- and five-minute standardized returns of both indices, common impulse, index dispersion, joint range expansion, BTC/ETH one- and five-minute standardized returns, signed lag, structural range position and BTC/ETH identity.

## Model and baseline

One `HistGradientBoostingClassifier` is trained on causally resolved January-June 2022 events. One isotonic map is fitted on causally resolved July-September 2022 events. The frozen model is tested on October-December 2022.

The model must beat both simple explanations:

- structural distance alone, represented by the exact zero-drift first-passage probability; and
- external shock direction alone, represented by the common standardized risk impulse.

The chosen side must equal the external shock direction. The model may only accept or reject that continuation trade. It cannot reverse the signal or search adjacent thresholds.

## Account replay

- Bybit BTCUSDT and ETHUSDT only in the initial screen.
- One global pending/open slot.
- Next-minute-open entry.
- Frozen structural target and stop.
- NAV-risk sizing at 0.5%, 3x notional cap and 0.1% of prior completed 15-minute volume.
- Identical 12, 18 and 24 bp round-trip paths.
- Counterfactual removal of the largest positive 10% of trades with global-slot re-arbitration.
- Every UTC calendar day is included in geometric growth.

## Sequential opening

The untouched 2023 source is requested only if every preregistered 2022 fit gate passes. The downloader rejects 2024, 2025 and 2026. Even a 2023 survivor remains an initial candle-data screen and cannot change the project champion or authorize trading without a separately frozen exact-execution replay.
