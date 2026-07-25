# COIN-M collateral-stress transmission

Research-only implementation for `CLM-20260725-2320-COINM-COLLATERAL-001`.

## Hypothesis

A downside shock that is disproportionately severe in crypto-collateralized COIN-M perpetuals can identify either:

1. continuing collateral deleveraging, when COIN-M relative sell flow and discount persist; or
2. forced-flow exhaustion, when price makes a marginal low but COIN-M flow and discount reaccept in the opposite direction.

The signal is generated from BTCUSD_PERP or ETHUSD_PERP; execution occurs only in BTCUSDT or ETHUSDT USD-M perpetuals.

## Causal and execution contract

- completed five-minute decision bars only;
- rolling references exclude the current bar and reset at data gaps;
- next-five-minute-open entry after confirmation;
- exact official USD-M funding at `(entry, exit]` using mark open and exact contract-open fallback only;
- structural targets are invariant across 12/18/24 bps cost stress;
- stop wins same-bar ambiguity and gap stops use the adverse observed open;
- one global BTC/ETH position;
- no time stop or end-of-period forced liquidation;
- development data are fetched and read first; later stages remain unopened unless the prior gate passes;
- account compounding respects the 1% target risk and 5x gross-leverage cap.

`amendment_001_preoutcome_execution_and_stage.json` records mechanical fixes made before any strategy PnL was observed.

## Reproduction

The source is stored as an immutable Base64 tar bundle. Reconstruct it before testing:

```bash
base64 -d research/coinm_collateral_stress/source_bundle.tar.gz.b64 \
  | tar -xz -C .
python -m pip install pandas==2.2.3 numpy==2.1.3 requests==2.32.4 pytest==8.3.4
python -m py_compile research/coinm_collateral_stress/coinm_collateral_stress.py
PYTHONPATH=research/coinm_collateral_stress \
  pytest -q research/coinm_collateral_stress/test_coinm_collateral_stress.py
python research/coinm_collateral_stress/coinm_collateral_stress.py \
  --download \
  --data-root .cache/coinm_collateral \
  --output research/coinm_collateral_stress/results
```

`SOURCE_BUNDLE_MANIFEST.json` pins the Base64 blob, decoded tar and source-file SHA-256 values.

No credentials, orders, paper/live authority, risk scaling or account-allocation changes are permitted.
