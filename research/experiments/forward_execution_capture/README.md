# Forward execution evidence layer

Observation-only primitives for causal public/private exchange capture and exact-prefix Shadow A/B.

The package provides:

- Binance USD-M and Bybit public event normalizers;
- local wall and monotonic receive clocks in each record;
- raw payload and append-only record-chain SHA-256 hashes;
- sequence, clock and normalization quality gates with `NORMAL/CAUTION/DEFENSIVE/HALT` risk states;
- environment-only Bybit private authentication;
- `execId`-authoritative execution/order/position reconciliation;
- exact capture-prefix dynamic maker/taker versus always-taker Shadow decisions.

It deliberately contains **no order-placement path**. Historical exchange timestamps alone are research-only. Paper or Live promotion requires prospective local-receive capture, same-account private executions, actual fees, partial fills, queue evidence and a separate validation cycle.
