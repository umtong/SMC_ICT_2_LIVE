# Auction-market prior-session volume-profile screen

## Decision

`RES-20260726-AUCTION-PROFILE-001` is **TESTED_BELOW_GATE**. The causal 2023 development screen found no positive candidate at 12, 18, or 24 bps among 72 preregistered combinations, so 2024, 2025, and 2026 were not evaluated. The project first place is unchanged.

## Why this was tested

The work translated two pre-2024 auction-market ideas into falsifiable rules rather than using them as chart narratives:

1. the prior value-area “80% rule”: outside open, subsequent acceptance inside value, then rotation across value;
2. prior point-of-control reaction: first causal touch of a completed prior-session POC.

The screen also tested the complementary one-sided continuation case when price remained accepted outside value.

## Causal contract

- Signals use only the prior completed 8-hour or 24-hour session and completed 15/30-minute confirmation brackets.
- Entry occurs at the next 5-minute open.
- One global position across BTCUSDT, ETHUSDT, SOLUSDT, and XRPUSDT.
- Same-bar stop/target ambiguity is resolved against the strategy; gap stops fill at the worse next open.
- Position quantity uses 0.5% planned NAV risk including entry/stop transaction costs, capped at 5x notional for this fatal screen.
- Identical signals are replayed at 12/18/24 bps round-trip costs.
- The final run uses a physically sliced 2023 snapshot; later periods are not used.

## Data and approximation limitation

The reusable source artifact contains checksum-registered Binance USD-M 5-minute OHLC, quote volume, and taker-buy quote volume. A price-level volume profile cannot be observed exactly from OHLCV bars, so the primary run allocates each bar’s quote volume to its HLC3 price bin. A targeted stress check used close-only and uniform-in-bar allocation. Every tested approximation remained negative.

Because the economic screen failed decisively, the work intentionally did not spend time acquiring exact trade-level volume-at-price, Bybit execution replay, or historical funding. The result therefore passes causal/execution-order checks for a preliminary screen but is not a hard-valid deployable strategy result.

## Primary development result

Best of 72 primary candidates: `c323f0bee14f8ac399dd`, 24-hour outside-value continuation, two 15-minute outside confirmations, one value-width target, stop at the re-entered value edge.

- 248 completed trades
- 12 bps: geometric daily growth -0.024146%, total return -8.44%, PF 0.911, MDD 16.44%
- 18 bps: geometric daily growth -0.056814%, total return -18.73%
- 24 bps: geometric daily growth -0.081334%, total return -25.69%
- median account return at 12 bps: -50.0 bps
- top-10%-winner-removed return at 12 bps: -54.05%
- both 2023 halves lost

The strongest profile-construction stress result was still negative: 24-hour uniform-in-bar POC rotation, 177 trades, -0.020640% daily at 12 bps and -0.039897% at 24 bps.

## Reproduction

```bash
python -m pip install numpy pandas pytest
export AUCTION_PROFILE_SNAPSHOT=/path/to/2023_snapshot
export AUCTION_PROFILE_OUTPUT=/path/to/output
python research/auction_profile_20260726/auction_profile_screen.py
pytest -q research/auction_profile_20260726/tests
```

The required snapshot schema and hashes are in `dataset_manifest.json`. The source artifact is `cross-asset-leadlag-baseline-20260725.zip` in the project Drive artifact registry.
