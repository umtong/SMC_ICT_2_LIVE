# Bybit L2 cancellation–replenishment aggressive alpha

This study starts from the return structure required by the project rather than from any previously ranked strategy. A 1% after-cost daily account objective needs an edge that is both materially larger than taker costs and repeatable many times. The primitive observation is therefore **why displayed liquidity changed**, not another candle pattern or raw imbalance threshold.

At every completed 100ms state, the evaluator separates:

- bid/ask depth consumed by observed aggressive trades;
- residual displayed-depth withdrawal attributable to cancellations or repricing;
- replenishment that replaces consumed depth;
- the resulting microprice, order-flow and price-response state.

A gradient-boosted model fitted only on July 1, 2022 forecasts executable 5/15/30-second direction and magnitude. The fixed candidate grid selects extreme forecasts and extreme liquidity events, enters at a future BBO after 100/300/500ms, applies an adverse executable stop and pays 12/18/24bp all-in cost. July 1, 2023 is untouched development data. Data from 2024 onward are rejected by code.

The first screen is intentionally narrow and fast. A zero-survivor result retires this exact information/payoff unit. A survivor must first be expanded over all available pre-2024 monthly samples without changing features, model or execution, then frozen before the official 2024 opening.

## Local checks

```bash
python research/bybit_l2_resiliency_20260726/reconstruct.py
python -m py_compile research/bybit_l2_resiliency_20260726/run_screen.py
python research/bybit_l2_resiliency_20260726/run_screen.py self-test
pytest -q research/bybit_l2_resiliency_20260726/test_run_screen.py
```

No credential or order path exists in this research package.
