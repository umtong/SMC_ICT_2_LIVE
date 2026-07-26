# ML liquidity-draw first-passage audit

Work Claim: `CLM-20260726-1712-ML-FIRSTPASS-AUDIT-001`  
Target Claim: `CLM-20260726-1703-ML-LIQUIDITY-DRAW-001`

This is **not another strategy**. It is a small reusable audit harness for the
single ML system selected by the project.

## SMC/ICT explanation

At each decision time, the strategy freezes the nearest already-confirmed,
still-unreached external buy-side and sell-side liquidity pools. The model is
allowed to answer only one question:

> Which frozen pool is reached first?

The output is converted into one of three actions:

- **LONG** only when the calibrated probability of buy-side liquidity being
  drawn first, multiplied by its structural reward distance, exceeds the
  probability-weighted sell-side loss and all registered costs.
- **SHORT** by the exact mirror equation.
- **FLAT** whenever neither direction has positive frozen cost-adjusted
  expectancy.

The target and stop are the two frozen liquidity pools. The model does not
invent a separate chart-pattern entry, discretionary target, or time exit.

## What this audit enforces

1. Causally frozen upper/lower pools and explicit first-passage labels.
2. Right-censored paths are retained; they cannot be silently relabeled or
   removed. A completed bar touching both pools is `AMBIGUOUS`, never assigned
   the favorable direction.
3. Chronological, non-overlapping train, calibration, confirmation and
   untouched development partitions.
4. Exactly one model family, one frozen hyperparameter specification and one
   economic decision equation.
5. Recalculation of LONG/SHORT/FLAT from calibrated probabilities, structural
   distances and registered costs.
6. One global position slot, sealed 2024–2026 boundaries, and cost monotonicity.

## Commands

```bash
python research/ml_firstpass_audit_20260726/audit.py self-test
python -m pytest -q research/ml_firstpass_audit_20260726/test_audit.py
```

When the target Claim emits its frozen artifacts:

```bash
python research/ml_firstpass_audit_20260726/audit.py validate \
  --manifest manifest.json \
  --predictions prediction_ledger.csv \
  --ledger trade_ledger.csv \
  --cost-ledger cost_ledger.csv
```

The contract SHA-256 is `be2aff81836d7ddc7b58a7278509b67412bd55e5d08ec1bcd5a1b54edcd18a91`. No market data, strategy outcome,
credentials, paper order, testnet order or live order is opened by this
component.
