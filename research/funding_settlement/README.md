# Exact BTC/ETH funding-settlement screen

Status: `INVALID / RESEARCH_ONLY`

This revision-4 study evaluates exact Binance USD-M funding-settlement mechanisms. It loads only 2021-2023 source rows for the initial gate, uses completed post-settlement five-minute bars, enters at the next five-minute open, includes actual funding cash flow when a position crosses the next settlement, and exits only by structural stop, strict target trade-through, causal flow-plus-anchor invalidation, or the next settlement state refresh.

## Candidate families

- post-settlement unwind and continuation
- premium-index dislocation reversion and breakout
- funding-flow disagreement
- BTC/ETH relative funding convergence and continuation

## Frozen grid

- z thresholds: 1.0, 1.5, 2.0, 2.5
- completed confirmation bars: 1, 3
- stops: 1.0, 1.5 ATR plus confirmation structure
- targets: 1.5R, 2.5R, 3.5R
- total: 432 candidates

## Result

- 2022 development / 2023 independent selection survivors: 0
- 2024 validation: unopened
- 2025 holdout: unopened
- best diagnostic: `eth_relative_continuation_z2.5_w3_s1.5_r3.5`
- best diagnostic 2022/2023 base multiples: `0.994405` / `1.005821`
- best diagnostic 2022/2023 1.5x-cost multiples: `0.979967` / `0.992968`

No Champion, Paper, Live, risk, leverage or account-allocation change.

## Reproduction

Rebuild the retained public-data bundle directly from official monthly Binance Vision URLs and adjacent SHA-256 files, reconstruct the runner, then execute the screen:

```bash
python research/funding_settlement/download_bundle.py \
  --root data/funding_settlement \
  --start 2021-01 --end 2025-12 \
  --symbols BTCUSDT ETHUSDT
python research/funding_settlement/restore_runner.py
python research/funding_settlement/runner.py \
  --root data/funding_settlement \
  --out artifacts/funding_settlement
```

The runner is stored in three readable, hash-registered fragments so connector writes remain deterministic. The initial gate internally stops loading source rows at the start of 2024; later archives are retained only for conditional follow-up reproduction.

## Fingerprints

- retained data bundle: `e67ed14371396192be11c06f5550e382c06abc2e3828a916eb6984a0c9ff017f`
- evaluation contract: `13717fae7c21b4a286ba472f5b1a6b05e9596c72b2888ec25b63e38ecdb5bf49`
- reconstructed runner: `bb8d25c19d5c1a5f44467f2b23b4782ba552e5ae3c8dbb93dd11fa173499f7b5`
- artifact: `2205478d98b170ee15fbab8095d0fcee9bf84845bfeace24afdf82316784db22`
- dependency: `f689c2b5341cc3d226519f57f64c1c46a1f117a0b5ef2e48ce9aeddc638a5fc1`
