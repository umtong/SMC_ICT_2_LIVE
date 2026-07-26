# Minimal ML PO3 state router

This study keeps one SMC/ICT narrative and one ML component.

**Trader explanation:** price first compresses into an accumulation box, raids one side during manipulation, then delivers toward the untouched side. The Gaussian HMM does not predict price or invent an entry. It only assigns causal probabilities to the three delivery phases from five completed-bar variables.

## What is deliberately excluded

- no FVG, order block, breaker, OTE, session, SMT, options, OI, liquidation or L2 feature;
- no strategy ensemble, parameter tournament or deep network;
- no elapsed-time exit;
- no 2024-2026 market data;
- no ranking eligibility from the Binance proxy.

## Frozen path

1. Fit one shared 3-state diagonal Gaussian HMM on 2021 BTC/ETH/SOL/XRP five-minute observations.
2. Map the three state means to accumulation, manipulation and distribution by a fixed economic mapping.
3. Run causal forward filtering through 2022.
4. Trade only the single frozen PO3 transition defined in `preregistration.json`.
5. Replay the same ledger at 12, 18 and 24 bp with actual funding, one global slot, 1% NAV risk and a 3x notional cap.
6. Open 2023 only if every 2022 gate passes.

## Reproduction

```bash
python -m pip install numpy==2.1.3 pandas==2.2.3 scipy==1.14.1 scikit-learn==1.5.2
python research/ml_po3_state_20260726/reconstruct.py
python research/ml_po3_state_20260726/run.py self-test
python research/ml_po3_state_20260726/run.py run \
  --root /tmp/ml-po3-state-r11 \
  --output research_runs/ml_po3_state_20260726
```

Deterministically reconstructed readable source SHA-256: `7e93fc5bb8f999c2a60a80eba3ba7f7d795964c4b7cd20ea1af89bbd8ef659fd`.
