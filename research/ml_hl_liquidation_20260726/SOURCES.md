# Sources — Hyperliquid finalized liquidation source gate

## Primary event source

- Dataset mirror: `gionuibk/hyperliquid-misc-events`.
- Canonical node producer: `hyperliquid-dex/node` with `--write-misc-events --batch-by-block`.
- Batched row schema: `local_time`, `block_time`, `block_number`, `events`.
- The workflow resolves the dataset repository `main` SHA before any event file is downloaded and then addresses every file through that immutable SHA.
- Raw files are treated as LZ4-compressed JSONL. Each downloaded byte stream is SHA-256 hashed before parsing.

## Canonical liquidation schema

Only explicit `LedgerUpdate` deltas with `type == "liquidation"` are accepted. Required fields:

- `liquidatedNtlPos`;
- `accountValue`;
- `leverageType` equal to `Cross` or `Isolated`;
- nonempty `liquidatedPositions[{coin, szi}]`.

Signed position size is interpreted mechanically: positive `szi` is a liquidated long and forced sell flow; negative `szi` is a liquidated short and forced buy flow.

Primary schema references:

- Hyperliquid L1 data schemas, miscellaneous events and liquidation type.
- Hyperliquid node repository, batching and misc-event output flags.

## Phase-0 boundary

The source gate reads no Bybit or other market price, future return, label, model score, trade, PnL, official 2026 period, credential or order path. A source-gate failure is transport/schema evidence only and is not negative alpha evidence.
