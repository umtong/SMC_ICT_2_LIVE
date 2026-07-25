# Attention and Liquidity State Research

## Disposition

`RES-20260725-001-ATTENTION-LIQUIDITY` is a causally screened **tested-below-gate** result. It is not a Champion challenger and does not grant paper or live authority.

## Scope

- Four-asset five-minute attention breakout, liquidity trap, and absorption/reacceptance: 576 configs.
- Cross-asset attention breadth switch: 96 configs.
- State-first hazard/direction separation: 288 configs.
- Cross-asset SMT divergence/catch-up: 192 configs.
- Native BBO/aggTrade absorption, vacuum, and catch-up: 384 configs.
- Total: 1,536 preregistered configurations; development gates passed: 0.

## Important corrections

1. Funding events use a mark **open** observable at the settlement time, with contract-open fallback only when the exact mark open is missing.
2. Structural targets remain cost-invariant. A prior run that moved the target with the cost multiplier is hard-invalid and retained only under `results/invalidated_run_001_cost_moved_targets`.

## Diagnostic finding

Hazard AUC ranged from 0.759331 to 0.807847; direction AUC conditional on hazard ranged from 0.544957 to 0.645932. A non-tradable perfect-direction oracle reached at most 0.501923% daily geometric growth in the weaker development segment at 1% risk, indicating that direction and execution economics remain the binding constraints.

## Verification

```bash
python research/attention_liquidity_state/tests/validate_result.py
```

## Reproducibility limitation

The original grid-generation scripts from the research session were not retained in the active runtime. The committed evidence, preregistrations, amendments, hashes, diagnostics, and validator are sufficient to reuse the negative result and avoid repeating the same hypotheses, but not to claim independent regeneration of every grid row.
