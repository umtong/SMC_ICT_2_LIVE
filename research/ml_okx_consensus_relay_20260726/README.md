# Minimal ML OKX spot–swap consensus relay

Claim: `CLM-20260726-2012-ML-OKX-CONSENSUS-001`

## One mechanism

A completed one-second displacement must appear simultaneously in OKX `BTC-USDT` spot and `BTC-USDT-SWAP`, with both aggressive-flow ratios aligned. The swap open-interest change describes whether new leveraged inventory sponsors the move or inventory is being closed. The account market is Bybit `BTCUSDT` only.

Before the event, the previous complete Bybit five-minute range is frozen. Its high and low are external liquidity. If OKX spot and swap have already displaced while Bybit remains inside that range and underreacts, the state is a measurable three-market SMT non-confirmation. One calibrated HGBT estimates whether Bybit reaches the OKX-direction boundary before the opposing boundary. The model can authorize continuation or remain flat; it cannot reverse the signal or create another pattern.

## Causal timing

- OKX trade and quote information is aggregated only after each one-second interval completes.
- Bybit range boundaries come only from the previous complete five-minute interval.
- The reference Bybit quote is strictly earlier than the decision timestamp.
- Entry waits 500 ms; the same signal is replayed at 1,000 ms.
- The first actual fresh Bybit BBO at or after the delay is used.
- A target or stop touch during the delay invalidates the entry.
- Same-state ambiguity is stop-first; source-boundary positions pay the structural stop.
- There is no elapsed-time liquidation.

## Minimal ML and account

The system contains one HGBT, one isotonic calibration map, twelve named features, one distance baseline, one target-before-stop label and one cost-adjusted continuation-or-flat equation. There is no model, feature, event, threshold, latency, payoff, risk or leverage grid.

The account begins at 10,000 USDT, risks 1% of NAV at the structural stop, uses at most 3x NAV notional, takes at most 5% of the observed top quote, and replays identical signals at 12/18/24 bp. BTC has the only pending/open slot.

## Chronology

- train: 2022-01-01, 2022-03-01, 2022-05-01;
- calibrate: 2022-07-01;
- untouched confirmation: 2022-09-01, 2022-11-01;
- conditional development: 2023-01-01, 2023-03-01, 2023-05-01;
- 2024–2026 are mechanically prohibited.

A failed confirmation gate retires this exact dependency. A survivor remains pre-2024 discovery and requires unchanged broader Bybit-native funding/depth and official sequential evaluation before ranking or practical use.
