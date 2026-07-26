# Source and dependency record

## Reused immutable data

The only market-data dependency is the already completed artifact from `RES-20260726-BYBIT-L2-RESILIENCY-FATAL-001`.

- GitHub workflow run: `30182786091`
- artifact name: `bybit-l2-resiliency-efa714dfee803544a26ba3609b0c1a14d7693831`
- artifact ID: `8626087323`
- artifact digest: `sha256:90594acc23e63e97e83347f9b07eb9ac260ba7bb1b87eb72052287a8328ad4a1`
- provider inputs in the parent result: Tardis normalized Bybit `book_snapshot_5` and `trades`, ordered by `local_timestamp`

Compact-state identities:

| role | date | file SHA-256 |
|---|---|---|
| fit | 2022-07-01 | `da8f581e64ba6f5305c57c0d76403b262d1b0ff48ad540e19302f6bf7416c38b` |
| conditional development | 2023-07-01 | `8872cd2a21960666f10f3d35c788a16faefd007d02a30389079def794e90389f` |

The workflow verifies these exact files before parsing. It never downloads a new market source.

## Model implementation

The fixed scientific environment uses NumPy, pandas, PyArrow and scikit-learn. The model family is chosen for tabular nonlinear interactions and missing-value tolerance; no external paper result is treated as evidence of profitability.
