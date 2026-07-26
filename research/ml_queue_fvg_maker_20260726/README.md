# Explainable ML queue-aware Sweep–MSS–FVG maker

Claim: `CLM-20260726-ML-QUEUE-FVG-MAKER-001`  
Issue: `#157`

## One trader-readable path

1. Freeze the previous completed 60-second external high and low.
2. Require a one-sided raid and completed close back inside.
3. Require opposite one-second displacement through frozen internal structure and a completed three-bar FVG.
4. Rest one post-only order at the FVG consequent-encroachment midpoint.
5. Stop remains beyond the raid; target is the opposite external-liquidity boundary frozen before the event.
6. One multinomial logistic model estimates `NO_FILL`, `TARGET`, and `STOP`; it cannot change direction, entry, stop, or target.

This is interpretable to SMC/ICT traders as a liquidity sweep, MSS displacement, FVG mitigation, and opposing-liquidity delivery. To a quant trader it is a fixed event definition, a single probabilistic outcome model, a cost-adjusted expected-value decision, and an exact chronological queue/account replay.

## Queue and execution

- 100 ms acknowledgement and 100 ms exit latency.
- A marketable post-only order is rejected.
- Touch never fills.
- Full fill requires actual opposing aggressive trades at or through the limit to consume `1.5 × displayed queue ahead + full 10,000-USDT order quantity`.
- Cancellations never improve queue position.
- Partial fills receive no credit.
- Pending orders occupy the single global slot until structural cancellation, fill and exit, or source boundary.
- Same-timestamp ambiguity is adverse.
- Filled exits use the adverse of the structural barrier and first delayed executable BBO.
- No elapsed-time liquidation exists.

## Stages

- Fit: `2022-07-01 BTCUSDT`.
- Untouched development: `2023-07-01 BTCUSDT`.
- Every 2024–2026 URL is rejected by code.

This is a fatal screen and cannot enter the cumulative ranking. A development survivor must keep the exact event, model, EV rule, level, queue rule and execution contract while expanding to every remaining pre-2024 source before official 2024 may open.

## Commands

```bash
python research/ml_queue_fvg_maker_20260726/reconstruct.py
python -m py_compile research/ml_queue_fvg_maker_20260726/reconstructed/run.py
PYTHONPATH=research/ml_queue_fvg_maker_20260726/reconstructed pytest -q research/ml_queue_fvg_maker_20260726/reconstructed/test_run.py
python research/ml_queue_fvg_maker_20260726/reconstructed/run.py self-test
python research/ml_queue_fvg_maker_20260726/reconstructed/run.py run \
  --cache /tmp/ml-queue-fvg-cache \
  --output research_runs/ml_queue_fvg_maker_20260726
```
