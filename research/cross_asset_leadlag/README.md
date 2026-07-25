# Causal cross-asset lead/lag baseline

This research branch is intentionally disjoint from the active transcript-extraction, single-asset absorption-flow and OI claims. It tests whether completed BTC/ETH shocks lead a delayed or overextended response in ETH/SOL/XRP.

## Economic hypotheses

1. **Underreaction continuation** — a BTC/ETH shock implies a beta-adjusted target move that has not yet occurred, while target taker flow confirms the leader direction.
2. **Overreaction reversal** — the target overshoots its prior-only beta response and its taker flow has already turned against the leader direction.
3. **Flow-disagreement reversal** — the target price follows the leader but target aggressive flow opposes the move.

No family is merged with another unless it independently passes the same evaluation contract.

## Causality and execution

- Features use completed 5-minute bars only.
- Rolling volatility and rolling cross-asset beta are shifted by one bar.
- A signal at bar `t` enters at bar `t+1` open.
- The global portfolio may have only one pending/open parent trade.
- A structural ATR stop is active from the entry bar; a gap beyond an already-known stop exits at the observed bar open.
- Baseline costs are 6 bp entry, 6 bp normal exit, 8 bp stop exit and a 1 bp funding/operational buffer. A 1.5x stress is required for independent validation.
- Position sizing uses a 1% planned-loss diagnostic with a 5x gross-notional cap; this is not a live risk recommendation.

## Search contract

- 2023: development and parameter selection.
- 2024: independent validation. Both baseline and 1.5x costs must pass.
- 2025: opened only for a family that passed 2024.
- Robustness includes trade count/frequency, positive mean R, top-10 removal, positive month breadth, positive geometric growth and a 20% cap on one-trade positive-profit concentration.

## Reproduction

```bash
python -m research.cross_asset_leadlag.download \
  --start-month 2023-01 --end-month 2025-12 \
  --destination artifacts/cross_asset_leadlag/snapshot

python -m research.cross_asset_leadlag.run_experiment \
  --snapshot-dir artifacts/cross_asset_leadlag/snapshot \
  --output-dir artifacts/cross_asset_leadlag/results
```

The GitHub Actions workflow runs tests, validates the project, downloads and verifies every official archive, executes the causal search, and uploads the manifest and results as an artifact.
