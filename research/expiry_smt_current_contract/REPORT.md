# 08:00 option-settlement SMT — current-contract audit

**Result:** `RES-20260730-EXPIRY-SMT-CURRENT-CONTRACT-001`  
**Decision:** **RETIRED ECONOMIC FAILURE before official 2024**.

## Why the archived headline could not be inherited

The archived 2022 proxy used Binance five-minute prices, the exact next five-minute open before the fixed 500 ms delay, fixed funding, 1% risk and no pending-order state. It returned +3.70% at 18 bp over 12 trades, but had a negative median, 95.18% top-five positive-PnL share and -2.03% after top-10% winner removal.

The archived source was reconstructed byte-for-byte (`51e2ed49...`) and selected policy `951df185862595e1` was kept unchanged. Canonical Bybit produced 13 events in 2022 and 12 in 2023.

## Corrected marketable confirmation

After two completed five-minute midpoint-reversal displacement bars, the order activates 500 ms later and fills at the first later one-minute open. At fixed 18 bp the route made +0.94% in 2022 and lost 1.75% in frozen 2023. The strategy logic therefore did not persist after replacing the proxy and entry clock.

## First causal rebalance

To test whether the idea was economically sound but entered too late, one prewritten alternative placed a maker limit at the midpoint of the completed confirmation displacement body. The level required 1 bp penetration, and the pending order occupied the global slot until fill or structural cancellation.

- 2022 actual fee path: +3.48%, 12 trades, PF 2.37.
- 2023 actual fee path: +0.66%, 11 trades, PF 1.26.
- 2023 fixed 12/18/24 bp: -0.21% / -0.82% / -1.30%.
- 2023 H2: -0.56%.
- Exact top-10%-event removal and full rerouting: -0.71%.

The apparent benefit came from a few large deliveries, not a repeatable day-trading engine. The first-rebalance correction improved entry fidelity but did not create robust cost-surviving breadth.

## Decision

No official 2024 interval, model, threshold, weekday filter, target change, risk/leverage search or live/paper order was opened. A local batch produced 2024H1 calculations after the gate failure; they are quarantined and are not authoritative evidence.

The exact option-settlement SMT family is closed. A future option route would require a materially new point-in-time information source such as causal option OI/gamma or transaction flow, not another price-only threshold around 08:00.
