# Exact Bybit 96/48 all-breakout Core audit

This audit reuses the exact 2,855 candidate-event generator from PR #466 and removes ML selection. Every eligible 60-minute close outside the prior 96 completed hours competes for the single global BTC/ETH slot under the unchanged 500ms entry, 2ATR stop, opposite 48-hour channel exit and actual-funding contract.

The first workflow stage materializes and inventories the immutable audit source so the all-breakout extension can be implemented against the actual event/account interfaces rather than guessed. The final route is fixed at 0.5% current-NAV planned loss, 3x notional cap and 13/18/24bp costs.

No channel, ATR, exit, symbol, session, model, risk or leverage search is permitted. No credentials or orders are used.
