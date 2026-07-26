# ML CME NDOG/NWOG competing-risk router

This claim is deliberately reduced to one model and one decision.

## SMC/ICT explanation

1. The actual CME futures close and reopen define a real NDOG or NWOG.
2. Map that percentage gap onto BTCUSDT or ETHUSDT at the CME reopen.
3. Wait for exactly two completed 15-minute bars.
4. Freeze two destinations already visible at that time:
   - the mapped prior CME close, representing gap rebalancing;
   - the nearest previous-day or previous-week external liquidity in the gap direction, representing accepted delivery.
5. One shared logistic competing-risk model estimates which destination is reached first.
6. Convert that probability and the two actual distances into expected net basis points after 18 bp.
7. Enter at the next 15-minute open only when one route has positive expected value. The other destination is the stop.

There is no second strategy, model ensemble, hyperparameter grid, probability-threshold grid, FVG, order block, OTE, session filter, OI, funding signal, option signal or L2 signal.

## Chronology

- train: 2021-01-01 through 2021-08-31;
- clean fit holdout: 2021-09-01 through 2021-12-31;
- 2022 opens only after a fit-holdout pass;
- 2023 opens only after a 2022 pass;
- 2024-2026 are prohibited.

The earlier 432-rule gap grid was never executed and is superseded by `amendment_001_ml_core.json`. Its runner remains only as the source, event, funding and adverse-execution helper used by the single ML policy.

## Commands

```bash
python research/cme_opening_gap_20260726/probe.py self-test
python research/cme_opening_gap_20260726/run_ml_screen.py self-test
python research/cme_opening_gap_20260726/run_ml_screen.py run \
  --cache /tmp/cme-opening-gap-ml \
  --output artifacts/cme_opening_gap_ml
```
