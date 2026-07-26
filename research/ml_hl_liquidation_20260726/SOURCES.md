# Sources — Hyperliquid finalized liquidation source gate

## Primary event source

- Dataset mirror: `gionuibk/hyperliquid-misc-events`.
- Canonical node producer: `hyperliquid-dex/node` with `--write-misc-events --batch-by-block`.
- Batched row schema: `local_time`, `block_time`, `block_number`, `events`, with `_src` preserving the originating `misc_events_by_block/hourly/YYYYMMDD/H.lz4` identity.
- The workflow resolves the dataset repository `main` SHA before any event row is read.
- The public repository stores consolidated `data/*.parquet` objects rather than guaranteeing each `_src` raw path as a separate Hub sibling. The source gate therefore addresses the Parquet object through the exact resolved commit SHA and selects only the 36 frozen `_src` values.
- DuckDB HTTP range reads use projection and Parquet predicate pushdown. A coverage query records every frozen path's row count, block range and local-time range; a second query reads only nonempty event payloads.
- Source identity includes repository metadata SHA-256, exact repository revision, Parquet sibling/blob metadata, frozen SQL hashes, coverage aggregates and output hashes.

## Canonical liquidation schema

Only explicit `LedgerUpdate` deltas with `type == "liquidation"` are accepted. Required fields:

- `liquidatedNtlPos` greater than zero;
- finite numeric `accountValue`, which may be negative at liquidation;
- `leverageType` equal to `Cross` or `Isolated`;
- nonempty `liquidatedPositions[{coin, szi}]` with finite nonzero signed size.

Signed position size is interpreted mechanically: positive `szi` is a liquidated long and forced sell flow; negative `szi` is a liquidated short and forced buy flow.

Primary schema references:

- Hyperliquid L1 data schemas, miscellaneous events and liquidation type.
- Hyperliquid node repository, batching and misc-event output flags.

## Phase-0 boundary

The source gate reads no Bybit or other market price, future return, label, model score, trade, PnL, official 2026 period, credential or order path. A source-gate failure is transport/schema evidence only and is not negative alpha evidence.
