# Exact Bybit replay and 2026H1 evaluation of ML UTC-state XRP rank one

Claim: `CLM-20260726-2235-ML-HOURWEEK-XRP-BYBIT-001`  
Issue: `#239`  
Source result: `RES-20260726-ML-HOURWEEK-XRP-001`

## Purpose

The provisional first place reports 0.223030% geometric daily growth at 24 bp on a Binance USD-M proxy, but the full source code and 58-trade ledger were not retained in the canonical repository. This scope first repairs that reproducibility defect. It does not treat the current rank as an incumbent to protect.

## Stage 0 — mandatory parity

Reconstruct the frozen pooled Ridge state machine from the registered contract:

- 24-hour return target;
- completed trend, volatility, quote-volume, taker-flow and cross-sectional state;
- asset-specific UTC hour-of-week and hour-of-day interactions;
- sequential half-year refits;
- prior-only 95th-percentile calibration;
- `UTC08-15 / BOTH / XRPUSDT / threshold 1.25` filter;
- next-hour-open entry;
- exit when signed expected edge is no longer positive or a stronger eligible action exists;
- one global slot and no elapsed-time liquidation.

No Bybit or 2026 outcome may be interpreted until the reconstructed path matches the registered 58 trades and published summary within explicit tolerances. Failure is a reproducibility failure and reduces or removes the provisional rank-one claim.

## Stage 1 — unchanged Bybit 2024-2025 replay

Only a parity-passing implementation may replay the same decisions on Bybit-native market prices, exact historical funding where available, observed or adverse spread, public-trade capacity, margin and liquidation-distance checks, and continuous UTC marked NAV. Signal decisions remain frozen; Bybit data may not change the filter or model.

## Stage 2 — official 2026H1 once

After Stage 1 code and dependencies are frozen using information available through `2025-12-31 23:59:59 UTC`, the exact version opens `2026-01-01` through `2026-06-30` once. The result is inserted immediately whether it raises, lowers or removes rank one. It is never used to revise the version claimed on that interval.

No credentials, paper orders, testnet orders or live orders are permitted.
