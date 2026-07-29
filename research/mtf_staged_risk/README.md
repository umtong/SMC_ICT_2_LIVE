# Fixed-total-risk staged passive-entry day-trading route

Result: `RES-20260730-MTF-STAGED-RISK-001`  
Claim: `CLM-20260730-0052-MTF-STAGED-RISK-001` / issue #431

## Hypothesis

The registered 쉽알남 actual-trading caption does not describe discretionary averaging without a limit. It fixes the maximum dollar loss first, predeclares two entry prices and one common structural stop, calculates total size from the weighted entry, and does not force the second tranche if its price is never offered.

The executable route therefore requires, before the first order:

1. completed 1h direction, with 4h/1d not jointly contradictory;
2. a genuine completed 5m full-body engulfing order block reacting at the first touch of a separate genuine 15m FVG or engulfing-body order block;
3. first passive entry at the 5m OB midpoint;
4. second passive entry at the distal quarter of the deeper 15m array;
5. one common stop beyond the full completed engulfing response and context origin;
6. a recent, prior-known and still-unconsumed 15m/1h pivot or previous-day level as the nearest target;
7. equal tranche quantity such that the loss of both filled tranches at the common stop, including costs, equals 0.5% of current NAV;
8. no entry outside the two prices, no stop widening, no time liquidation and one global BTC/ETH pending/open slot.

`SOURCE_EVIDENCE.json` binds the source hash and timestamp evidence.

## Material programization corrections

The first implementation was not faithful enough and was discarded before the final result.

- The common stop originally ignored the confirming engulfing candle's manipulation extreme. It now lies beyond the complete two-candle response.
- The first ladder split used arbitrary 25%/75% points inside one small overlap. The final route uses two distinct arrays: the 5m OB and the deeper 15m context.
- When a second pending order was cancelled after a partial, the risk denominator could shrink. Final sizing remains bound to both orders exactly as planned before the first order.
- Targets now carry causal creation and first-consumption times.
- A passive order requires one-basis-point trade-through after fixed 500ms activation, and the decision minute itself is unavailable for filling.

Eight causal, semantic, fill and risk-ledger tests pass.

## Inventory

| symbol | 15m context zones | target levels | candidates |
|---|---:|---:|---:|
| BTCUSDT | 50,108 | 40,801 | 602 |
| ETHUSDT | 45,544 | 37,442 | 512 |

Total: **1,114 candidates**.

## Deterministic event economics

### Two-tranche staged entry, full nearest target

| cost | year | events | mean R | median R | PF | win rate |
|---:|---:|---:|---:|---:|---:|---:|
| 12bp | 2021 | 264 | -0.3877 | -1.0 | 0.494 | 23.48% |
| 12bp | 2022 | 258 | -0.6168 | -1.0 | 0.243 | 17.83% |
| 12bp | 2023 | 254 | -0.6403 | -1.0 | 0.236 | 15.75% |
| 24bp | 2021 | 264 | -0.5102 | -1.0 | 0.334 | 23.48% |
| 24bp | 2022 | 258 | -0.6950 | -1.0 | 0.151 | 15.89% |
| 24bp | 2023 | 254 | -0.7297 | -1.0 | 0.130 | 13.39% |

At 12bp, 97 one-tranche fills were positive as a diagnostic, but 679 two-tranche fills were deeply negative. That split cannot be known ex post and is not treated as a strategy. A predeclared early exit at the second level also failed: 1,611.73 USDT at 12bp and 1,137.77 USDT at 24bp.

## One-slot account paths

| route | cost | final NAV | trades | daily geometric growth | PF | MDD |
|---|---:|---:|---:|---:|---:|---:|
| first price only, full target | 12bp | 1,731.24 | 683 | -0.160031% | 0.426 | 82.69% |
| two-tranche staged, full target | 12bp | 1,496.05 | 683 | -0.173344% | 0.365 | 85.04% |
| first price only, full target | 24bp | 1,208.75 | 683 | -0.192782% | 0.299 | 87.91% |
| two-tranche staged, full target | 24bp | 1,083.05 | 683 | -0.202790% | 0.246 | 89.17% |

Partial-to-breakeven and partial-with-structural-stop management were also negative. Exact winner removal with full slot rerouting worsened every path.

## Verdict

`BOTH_PROGRAMIZATION_AND_ECONOMIC_FAILURE`.

The programization corrections materially improved the initial implementation, but they did not produce positive fixed-small-risk economics. Always add, never add, midpoint-only, partial management and a predeclared early exit at the deeper level all failed in every pre-2024 year. The exact information unit is retired without ML, risk/leverage search or official 2024-2026 access.

This result does not claim that all discretionary scale-in is invalid. It establishes that the caption-grounded information available in these canonical bars is insufficient to automate the route as a profitable standalone system.

## Reproduction

```bash
python research/mtf_staged_risk/materialize.py
python research/mtf_staged_risk/run.py --self-test
pytest -q research/mtf_staged_risk/test_run.py
python research/mtf_staged_risk/generate_symbol.py BTCUSDT --data-root /path/to/alds_core
python research/mtf_staged_risk/generate_symbol.py ETHUSDT --data-root /path/to/alds_core
python research/mtf_staged_risk/evaluate_generated.py --data-root /path/to/alds_core
python research/mtf_staged_risk/winner_removal.py
```

No credentials, paper orders, testnet orders or live orders were used.
