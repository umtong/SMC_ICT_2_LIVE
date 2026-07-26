# Source and concept boundary

## Immutable market-data dependency

The workflow reuses only the compact causal state files produced by the hard-valid PR #72 data pipeline. It does not reuse PR #72's failed model, scores, labels, signals, candidates or PnL.

- source workflow run: `30183063220`
- source artifact: `8626169763`
- artifact digest: `sha256:a6f5c943231ca4e7b22df35d5cf79c236da55dc6fe2f0be40739fb3141142841`
- 2022 state SHA-256: `da8f581e64ba6f5305c57c0d76403b262d1b0ff48ad540e19302f6bf7416c38b`
- 2023 state SHA-256: `8872cd2a21960666f10f3d35c788a16faefd007d02a30389079def794e90389f`

The states were built from Tardis normalized Bybit `book_snapshot_5` and `trades`, with `local_timestamp` as the information-availability clock. PR #72 emits every completed **100 ms** state. This study groups only exact contiguous 100 ms states and creates a new causal segment after every missing state. The first run's 500 ms interpretation is invalidated by `amendment_001_source_frequency_correction.json`.

## SMC/ICT concept translation

- displacement: completed middle-bar body and aggressive-flow direction;
- FVG: first/third-bar executable-mid non-overlap;
- inversion: later completed close through the far edge of the FVG;
- first mitigation: first later completed bar reaching the lower edge or consequent encroachment and rejecting in the inverted direction;
- external liquidity: completed pre-formation 120-second high or low, required to remain unswept through entry;
- invalidation: completed close back through the inverted zone;
- execution: next complete bar's observed Bybit ask for longs or bid for shorts.

Source vocabulary motivates the state machine only. Profitability is determined solely by the frozen after-cost replay.
