# Work Claim — canonical half-year market data

- claim_id: `CLM-20260727-CANONICAL-HALFYEAR-DATA-001`
- worker: `gpt-5.6-pro`
- base revision: `22`
- scope: strategy-agnostic reusable Bybit USDT-linear market-data foundation
- symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`
- logical periods: `PRE_2024`, `2024_H1`, `2024_H2`, `2025_H1`, `2025_H2`, `2026_H1`
- non-overlap: no strategy, model, threshold, risk, leverage, order or account result; reuse compatible PR #333 output instead of duplicating it
- completion condition: every core shard is immutable in Drive with manifest, source hashes, file hashes, coverage audit and verified common loader contract
- live permission: none
