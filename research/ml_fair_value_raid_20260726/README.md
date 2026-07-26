# Event-time ML fair-value raid router

Claim: `CLM-20260726-1925-ML-FAIR-VALUE-RAID-001`  
Issue: `#152`

## Trader-readable logic

Bybit's completed mark price and index price define a frozen external fair-value pool. When the completed one-second last price leaves that pool far enough to qualify as a fit-period tail event, the move is treated as a quantitative liquidity raid.

The next completed second is the earliest possible entry. One ML model reads only information already available at the decision: fair-value and last/mark gaps, premium response, short-horizon price response, open-interest creation or destruction, realized volatility, funding state and update age. It can make only one of three decisions:

1. **Rejected displacement:** fade back to the frozen fair-value pool.
2. **Accepted displacement:** follow toward a fixed 150% extension.
3. **Flat:** do nothing.

The opposite structural barrier is the stop. No elapsed-time liquidation is allowed. If the source day ends before either barrier resolves, the trade is charged its full adverse structural stop.

In SMC/ICT language, mark-index fair value is the external reference pool; the last-price departure is the raid; open-interest and premium behavior help distinguish a rejected sweep from a displacement that has been accepted and is repricing toward new external liquidity.

## Minimal ML contract

There is one `HistGradientBoostingClassifier`, one later isotonic calibration map and one fixed logistic structure comparator. There is no model-family, feature, threshold, probability, target, stop, risk or leverage grid. The model cannot invent a pattern, direction, target, stop or holding period.

A route is authorized only when its event-specific expected value remains above a two-basis-point margin after a frozen 24bp round-trip reserve. The identical selected path is replayed at 12, 18 and 24bp.

## Causal stages

- 2022-01 through 2022-06: threshold and model fit.
- 2022-07 through 2022-09: one calibration map.
- 2022-10 through 2022-12: untouched confirmation.
- 2023-01 through 2023-06: downloaded only if every confirmation gate passes.
- 2024-2026: mechanically prohibited.

BTC and ETH require complete source continuity. SOL and XRP join only if all pre-confirmation source dates are complete. One global pending/open slot is enforced across all eligible symbols.

## Economic gate

Confirmation must retain at least 20 routed trades, positive mean and median at 24bp, profit factor above 1.1, at least 1% geometric growth per sampled UTC day, positive results on at least two-thirds of dates, positive Brier skill and AUC lift over the structure-only comparator. Top-five positive PnL share must stay below 50%, boundary losses below 10%, and complete rerouting after removing the top 10% positive events must still exceed 1% per sampled day.

This is a fatal screen, not a rank-eligible result. A survivor still requires exact Bybit BBO, funding, latency, marked NAV, broader pre-2024 stability and the official sequential 2024-2026 contract.

## Reproduction

```bash
python research/ml_fair_value_raid_20260726/reconstruct.py
python -m py_compile \
  research/ml_fair_value_raid_20260726/reconstruct.py \
  research/ml_fair_value_raid_20260726/run.py \
  research/ml_fair_value_raid_20260726/test_run.py
pytest -q research/ml_fair_value_raid_20260726/test_run.py
python research/ml_fair_value_raid_20260726/run.py self-test
python research/ml_fair_value_raid_20260726/run.py run \
  --cache /tmp/ml-fair-value-raid-cache \
  --output /tmp/ml-fair-value-raid-output
```
