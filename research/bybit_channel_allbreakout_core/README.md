# Exact Bybit 96/48 all-breakout Core audit

This audit reuses the exact 2,855 candidate-event generator from PR #466 and removes ML selection. Every eligible 60-minute close outside the prior 96 completed hours competes for the single global BTC/ETH slot under the unchanged 500ms entry, 2ATR stop, opposite 48-hour channel exit and actual-funding contract.

The first workflow stage materializes and inventories the immutable audit source so the all-breakout extension is implemented against the actual event/account interfaces rather than guessed. The final route is fixed at 0.5% current-NAV planned loss, 3x notional cap and 13/18/24bp costs.

The source transport is a gzip archive. Because gzip header metadata can change when the same frozen files are repacked, the scientific integrity authority is the exact regular-file member set plus each extracted file's frozen byte length and SHA-256. The archive digest is retained as a transport diagnostic and is not allowed to override matching decision-source file hashes.

No channel, ATR, exit, symbol, session, model, risk or leverage search is permitted. No credentials or orders are used.
