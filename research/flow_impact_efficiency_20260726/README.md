# Flow-size and price-impact efficiency screen

This directory completes `CLM-20260726-0145-FLOW-IMPACT-TAKEOVER-001`, which supersedes an expired no-output claim. It tests whether completed one-minute USD-M trade count, average quote trade size, true taker imbalance and price response per unit flow separate informed continuation from absorption and reversal.

## Frozen scope

- BTCUSDT and ETHUSDT Binance USD-M perpetual futures;
- retained official monthly archives from the checksum-verified spot/perpetual artifact `8621251086`;
- 2021-Q4 warm-up and calendar-2022 development;
- 2023 selection opens only for frozen development survivors, 2024 only after the same candidate passes 2023, and 2025/2026 remain sealed;
- six mechanism families and 864 deterministic candidates;
- completed bars only, next contiguous one-minute open entry, one global account slot, historical funding and identical 12/18/24bp path replay;
- 0.5% planned-loss sizing, 3x notional cap and 0.1% signal-minute quote-volume participation;
- adverse stop-first same-minute ordering and adverse observed-open gap stop;
- no credentials or orders.

## Mandatory pre-result corrections

Four implementation issues were found through causal and reproducibility audits before the result was registered:

1. the account slot is released at the exit-minute open, allowing that completed minute to form the next signal;
2. no trade may inspect a maximum-hold path at or beyond the exclusive evaluation-stage end;
3. official rows with nonpositive quote volume or trade count remain on the UTC grid but are unavailable to features and execution;
4. the final artifact manifest is noncircular and is built only after all covered files are final.

All diagnostic outputs produced before the relevant correction were excluded.

## Result

The corrected development screen produced zero gate passes out of 864 candidates. The strongest raw candidate had only four trades, 0.0020533% geometric daily growth at 12bp and negative return after removing one top trade. Every candidate with at least 200 trades had negative after-cost geometric growth. The result is hard-valid reusable negative evidence, provisional rank 6 by raw target proximity, and not deployable.

Ordinary adjacent-threshold tuning of this one-minute activity/impact dependency family is retired. A future revisit requires a materially different event clock, information source, order type or payoff structure.

## Reproduction

```bash
python research/flow_impact_efficiency_20260726/reconstruct.py
python research/flow_impact_efficiency_20260726/implementation/run.py self-test
python research/flow_impact_efficiency_20260726/implementation/run.py run \
  --source /path/to/spot-perp-leadership-artifact \
  --output artifacts/flow_impact_efficiency
```

GitHub Actions downloads the registered checksum-verified source artifact, reconstructs the exact implementation, reruns the frozen screen, compares the result to `RESULT.json`, verifies causal audits and uploads a compact evidence artifact.
