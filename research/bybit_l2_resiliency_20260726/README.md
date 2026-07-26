# Bybit cost-sensitive nonlinear L2 forecast alpha

This study starts from the return structure required by the project rather than from any previously ranked strategy. A 1% after-cost daily account objective needs an edge that is materially larger than taker costs and repeatable many times. The decision rule is therefore a **nonlinear forecast of future executable bid/ask returns from stationary full-book event state**, not a candle rule, raw imbalance threshold or hand-written cancellation/refill condition.

At every completed 100ms state, the evaluator constructs:

- multi-level stationary order-flow imbalance and normalized queue shape;
- bid/ask depth consumed by observed aggressive trades;
- residual displayed-depth withdrawal attributable to cancellations or repricing;
- replenishment that replaces consumed depth;
- microprice, spread, aggressive-flow, update-intensity, volatility and price-response state.

These are model inputs. No single cancellation or refill threshold authorizes a trade. Separate gradient-boosted models fitted only on July 1, 2022 forecast executable 5/15/30-second direction and magnitude. The fixed candidate grid selects extreme forecasts and independent event-strength tails, enters at a future BBO after 100/300/500ms, applies an adverse executable stop and pays 12/18/24bp all-in cost. July 1, 2023 is untouched development data. Data from 2024 onward are rejected by code.

This scope is distinct from PR #68's hand-specified 432-cell liquidity-pull continuation and pull-refill failure rules. It uses a nonlinear full-feature predictor, a 2022-only fit partition, different development data and direct executable-return labels. The first real-data run exposed only a pandas Series datetime-accessor implementation error before any model or PnL existed; reconstruction now applies that one deterministic correction after verifying the immutable original evaluator bytes.

The first screen is intentionally narrow and fast. A zero-survivor result retires this exact model/information/payoff unit. A survivor must first be expanded over all available pre-2024 monthly samples without changing features, model or execution, then frozen before the official 2024 opening.

## Local checks

```bash
python research/bybit_l2_resiliency_20260726/reconstruct.py
python -m py_compile research/bybit_l2_resiliency_20260726/run_screen.py
python research/bybit_l2_resiliency_20260726/run_screen.py self-test
pytest -q research/bybit_l2_resiliency_20260726/test_run_screen.py
```

No credential or order path exists in this research package.
