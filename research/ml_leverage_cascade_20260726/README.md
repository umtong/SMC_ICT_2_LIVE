# ML leverage-cascade structure-break continuation

This experiment tests one information unit and nothing else: **does leveraged positioning observed on Binance add causal, cost-surviving information about whether a completed Bybit structure break continues to the next external liquidity pool?**

## SMC/ICT translation

The setup is deliberately explainable without ML jargon:

1. A 15-minute swing is not usable until two complete bars have formed to its right.
2. The first completed close through that already-known internal swing is displacement.
3. Before entry, the target is frozen at the nearest still-unreached, already-confirmed hourly swing in the displacement direction. The stop is frozen behind the latest already-confirmed opposite 15-minute swing.
4. Binance open interest, top-trader accounts, top-trader positions, the full-account long/short ratio and taker buy/sell ratio describe who is crowded, who is trapped and whether inventory is expanding or being forcibly reduced.
5. One ML model estimates continuation to the external pool before structural invalidation. A structure-only model is the required benchmark. The positioning model may trade only when it beats both the exact cost-adjusted break-even probability and the structure-only probability by frozen margins.

Thus the model does not invent a chart pattern. It decides whether observed leveraged inventory supports **delivery after displacement**.

## Causality

All pivots are delayed until their right-side confirmation bars finish. The trigger uses only pivots known before the trigger bar. A Binance metrics row is usable only at its recorded timestamp, and entry is delayed by a full minute after both that timestamp and the completed Bybit decision bar. If target or stop is touched during that delay, the candidate disappears. The model never uses a trade's future target/stop result as an input.

Training ends March 31, 2022. April–June 2022 is used only for chronological Platt calibration. July–December 2022 is untouched fit confirmation. Calendar 2023 is not downloaded unless every preregistered model, account, cost, breadth and concentration gate passes. Code rejects 2024–2026.

## Execution model

Execution is replayed on native Bybit one-minute bars. Same-minute target/stop ambiguity is stop-first, adverse stop gaps fill at the minute open, and a source gap is charged as a full structural stop. There is one global pending/open slot across BTC and ETH, NAV-risk sizing, a five-times-NAV notional ceiling, a 0.1% prior completed-hour volume participation ceiling, 12/18/24 bp all-in cost paths, and a prorated 1 bp per eight-hour holding charge. No elapsed-time exit exists. Open positions are marked at realistic liquidation value at every UTC day boundary.

## Kill rule

This is not a parameter search. There is one model family, one fixed parameter set, one feature family and one policy. Failure to beat the structure-only model in both AUC and Brier score, or failure of any economic gate, kills the exact approach. No post-result threshold, direction, symbol, leverage, risk or sizing rescue is authorized.

## Run

```bash
python -m pip install numpy==2.1.3 pandas==2.2.3 requests==2.32.4 scikit-learn==1.6.1 pytest==8.3.4
python research/ml_leverage_cascade_20260726/reconstruct.py
PYTHONPATH=research/ml_leverage_cascade_20260726 \
  python research/ml_leverage_cascade_20260726/run.py \
  --cache /tmp/ml-leverage-cascade-cache \
  --output research_runs/ml_leverage_cascade_20260726/r11
```

The workflow records source URLs, byte sizes and SHA-256 hashes; frozen models; features; candidates; trades; UTC daily NAV; results; environment and input/output checksums. It never loads credentials and never submits an order.
