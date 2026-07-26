# Bybit inverse-perpetual → linear-perpetual SMT displacement

Work Claim: `CLM-20260726-1102-BYBIT-INVERSE-LINEAR-001`

## Strategy in SMC/ICT language

This study treats Bybit's inverse and USDT-linear perpetuals as two correlated liquidity venues for the same underlying asset.

- **Leader displacement:** `BTCUSD` or `ETHUSD` inverse perpetual prints a completed 100 ms displacement.
- **SMT divergence:** the corresponding `BTCUSDT` or `ETHUSDT` linear perpetual has not confirmed the displacement.
- **Fair-value imbalance:** after removing only the prior-observable inverse/linear basis, the residual gap measures the inter-contract imbalance.
- **Execution:** enter the linear perpetual toward rebalancing after 100/250/500 ms only if at least half of the causal gap remains.
- **Invalidation before entry:** reject the trade if the linear contract has already repriced through more than half the gap, if spread state is excessive, or if modeled full-fill impact breaches the marketable-limit price.

This is not a visual chart annotation. Every displacement, SMT divergence, imbalance, delay and invalidation is timestamped and computable before entry.

## Economic question

The project first asks a fatal question: can even an impossible future-information upper bound survive executable Bybit quotes and 18 bp of additional round-trip friction with enough independent events?

The 30-second oracle chooses the best future executable exit only as an upper bound. It is not a strategy rule. Failure closes this exact information unit without spending time on leverage, risk-rate or exit optimization.

## Frozen contract

- venue: Bybit;
- leaders: `BTCUSD`, `ETHUSD` inverse perpetuals;
- traded targets: `BTCUSDT`, `ETHUSDT` USDT-linear perpetuals;
- signal clock: completed 100 ms Tardis `local_timestamp` buckets;
- fit dates: 2023-03-01, 2023-05-01, 2023-07-01;
- development dates: 2023-09-01, 2023-11-01, 2023-12-01, opened only after a full fit survivor;
- 2024-2026 sealed;
- 324 candidates;
- 100/250/500 ms entry latency;
- adverse equal-timestamp entry and exit resolution;
- exact target bid/ask crossing;
- convex top-quote participation impact;
- 1- or 2-spread marketable-limit rejection;
- fixed 10,000 USDT notional;
- one global BTC/ETH slot;
- identical 12/18/24 bp replay.

## Gate

A candidate must have at least 20 globally routed trades and, at 18 bp, positive oracle mean, median and top-10%-winner-removed mean, positive calendar-day performance on at least two of three dates, and positive causal fixed-10-second mean. A survivor authorizes only causal-exit development; it does not open 2024 and is not rank eligible.

## Reproduction

```bash
python research/bybit_inverse_linear_v1/reconstruct.py
python -m py_compile research/bybit_inverse_linear_v1/run.py
python research/bybit_inverse_linear_v1/run.py self-test
python research/bybit_inverse_linear_v1/run.py probe \
  --cache /tmp/bybit-inverse-linear-v1 \
  --output research_runs/bybit_inverse_linear_v1/probe
python research/bybit_inverse_linear_v1/run.py run \
  --cache /tmp/bybit-inverse-linear-v1 \
  --output research_runs/bybit_inverse_linear_v1/screen
```

No credentials, paper orders, testnet orders or live orders are used.
