# ML liquidity-sweep / crowding state transition

This claim tests one compact, explainable mechanism rather than another indicator bundle:

1. A completed Bybit 5-minute bar takes only one side of the preceding 12-hour external range.
2. Two mutually exclusive actions are constructed from the same event: forced-liquidation continuation and absorption/reversal.
3. A pooled BTC/ETH `HistGradientBoostingClassifier` estimates which structural 3R target reaches before its structural stop, using only completed price/volume state and Binance USD-M crowding/flow metrics delayed by one full 5-minute observation.
4. The higher-probability action may trade only when its probability clears the frozen threshold. BTC and ETH share one global slot.
5. The 2023 calendar account selects threshold, risk fraction, and leverage by 24bp after-cost UTC geometric daily NAV growth. A nonpositive 2023 account closes the exact route; a positive account immediately opens official 2024H1.

The executable contract is `contract.json`. `run.py` downloads and fingerprints Bybit 1-minute archives, Binance metrics, and Bybit funding; constructs causal labels and features; performs the frozen selection; and emits `result.json`, `report.md`, grid, and trade ledgers. It never submits orders.

```bash
python research/ml_sweep_crowding/test_run.py
python research/ml_sweep_crowding/run.py \
  --contract research/ml_sweep_crowding/contract.json \
  --cache-dir ~/.cache/smc_ict/ml_sweep_crowding \
  --output-dir research/results/ml_sweep_crowding
```

Execution uses fixed 500ms latency, the first observable one-minute open strictly after activation, adverse round-trip costs, stop-first intraminute ambiguity, adverse gap-through stops, actual Bybit funding, no time exit, one global position, and UTC daily NAV marks. Position size is limited only by the selected risk budget, selected leverage, and the stop-before-liquidation condition using the maintenance-margin proxy; no discretionary defensive haircut is applied.
