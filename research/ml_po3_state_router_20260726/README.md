# Minimal ML PO3 delivery-state router

This research keeps one machine-learning model, three latent states, five
features and one entry route.

## SMC/ICT explanation

The model learns the delivery sequence commonly described as Power of Three:

1. **Accumulation** — compressed range with limited directional efficiency.
2. **Manipulation** — one side of the completed accumulation box is raided and
   price closes back inside.
3. **Distribution** — the learned state changes again while candle direction
   and aggressive flow confirm delivery away from the raid.

The strategy enters only at the next completed 5-minute open after that
sequence. The stop is beyond the raid extreme. The target is the opposite side
of the frozen accumulation box. There is no elapsed-time liquidation.

## Minimality

- one shared three-state diagonal-Gaussian Markov model;
- one causal forward filter, never full-sequence Viterbi;
- five features: prior-normalized return, prior-normalized range, body
  efficiency, wick skew and taker-flow imbalance;
- one structural reversal route;
- three probability thresholds only: 0.45, 0.60 and 0.75.

2021 is the only model-training period. 2022 selects at most one threshold.
2023 opens only after a 2022 cost-and-concentration gate. 2024-2026 are
code-prohibited.

This Binance USD-M screen is an economic fatal-screen proxy and cannot enter
the project ranking. A survivor must replay the unchanged model and rule on
exact Bybit data and execution.
