# ML Option Hedge → Bybit Liquidity Draw

This is the single surviving ML research path.

A completed five-minute Deribit option-flow window is translated into signed delta demand and dealer gamma pressure. One calibrated nonlinear model predicts whether the already-frozen Bybit buy-side or sell-side external-liquidity pool will be reached first. The calibrated probability and the two structural distances produce exactly one long, short or flat decision.

There are no named option-flow strategies, no FVG/order-block/session entry, no model family search and no elapsed-time position exit.

## Reproduce

```bash
python research/ml_option_hedge_20260726/reconstruct.py
PYTHONPATH=research/ml_option_hedge_20260726 pytest -q research/ml_option_hedge_20260726/test_run.py
PYTHONPATH=research/ml_option_hedge_20260726 python research/ml_option_hedge_20260726/run.py self-test
PYTHONPATH=research/ml_option_hedge_20260726 python research/ml_option_hedge_20260726/run.py run \
  --output research_runs/ml_option_hedge_20260726/r12 \
  --cache /tmp/ml-option-hedge-r12
```

A failed 2022 confirmation gate physically prevents 2023 downloads. Every 2024–2026 source request is rejected by code. No credentials or orders are used.
