# Source boundary

The evaluator reuses only the immutable causal state parquet files produced by PR #72. None of PR #72's failed model, scores, labels, signals, candidates or PnL are reused.

- source run: `30183063220`
- source artifact: `8626169763`
- artifact digest: `sha256:a6f5c943231ca4e7b22df35d5cf79c236da55dc6fe2f0be40739fb3141142841`
- 2022 state SHA-256: `da8f581e64ba6f5305c57c0d76403b262d1b0ff48ad540e19302f6bf7416c38b`
- 2023 state SHA-256: `8872cd2a21960666f10f3d35c788a16faefd007d02a30389079def794e90389f`

Tardis `local_timestamp` is the information-availability clock. PR #72 constructs every completed **100 ms** state. Only exact contiguous 100 ms states may form a bar, and a missing state begins a new causal segment. The first CISD run's 500 ms interpretation is invalidated by `amendment_001_source_frequency_correction.json`.
