# L2 maker toxicity V4 — independent source pivot

## Reason for the pivot

The pinned third-party reconstructed depth20 source passed its internal Binance sequence audit, but the separate no-PnL alignment audit found material limitations for tiny maker edges:

- the files do not always span a full UTC day;
- some dates contain multi-hour gaps;
- with the event clock and prior depth age <=50ms, official aggressive trades are not strictly compatible with the reconstructed BBO often enough for a sub-basis-point maker claim;
- BTC compatibility is materially better than ETH, but residual 1–2bp uncertainty is still economically large relative to spread capture.

No strategy outcome was opened under the questionable alignment. V1 is hard-invalid, and V2/V3 did not produce market PnL.

## Independent discovery source

Use Tardis normalized Binance USDT Futures tick CSV samples. Tardis states that downloadable files are exported from captured exchange WebSocket feeds, are split by local receive date, preserve original capture row order, and include both exchange timestamp and local timestamp. First-of-month samples are available without an API key.

The first feasibility sample is fixed before download:

- exchange: `binance-futures`
- symbol: `BTCUSDT`
- date: `2025-08-01`
- streams: `book_ticker`, `trades`, `book_snapshot_5`
- strategy outcomes: prohibited
- order simulation: prohibited

The sample is used only to establish compressed size, row count, schema, gzip integrity, source SHA-256 and availability-clock semantics.

## Causal clock contract

- `local_timestamp` is the information-availability clock.
- CSV row position is the tie-breaker when local timestamps are equal.
- Exchange `timestamp` is retained as event time, never substituted for availability time.
- A decision can use only rows whose local timestamp is strictly before or equal to the decision boundary.
- Any source gap invalidates decisions that would require forward filling across that gap.

## Promotion boundary

A feasible sample does not establish alpha. A later V4 strategy result remains component-level until it is reproduced across several first-of-month regimes and then confirmed on an independently captured prospective stream or a second source. No paper, testnet, live, sizing or leverage permission is created by this pivot.
