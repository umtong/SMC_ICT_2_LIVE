# Liquidation-sweep MSS passive retest

Claim: `CLM-20260726-LIQ-SWEEP-RETEST-001`  
Branch: `agent/r11-liq-sweep-retest-001`

## SMC/ICT explanation

The preceding market-entry formulation correctly identified an external-liquidity raid, actual forced liquidation, reclaim, refill and MSS, but paid for displacement after confirmation. This study changes the order mechanism rather than loosening that signal.

1. A completed prior 5/15-minute high or low defines external liquidity.
2. Bybit trades through the level and exchange-reported liquidations confirm forced delivery.
3. Opposite aggressive flow, BBO refill, range reclaim and a completed 3/10-second MSS establish rejection.
4. Instead of chasing the MSS, a post-only order waits at either the raided liquidity level or the 50% retracement of the sweep-extreme-to-MSS-decision leg.
5. The order is acknowledged after 100/300 ms and must be non-marketable then.
6. Touch is not a fill. An actual Bybit trade must penetrate the limit by 1/2 bp. If the structural target is reached first, the pending order is cancelled.
7. A pending unfilled order occupies the single global slot until fill, target-before-fill cancellation or session-boundary cancellation.
8. Once filled, the stop remains beyond the actual sweep extreme and the objective is prior-range equilibrium or 2R. There is no elapsed-time forced exit.
9. Triggered exits use the adverse of the trigger trade and delayed executable BBO. A favorable latency rebound cannot rescue a stop. An unresolved source-boundary position receives the full stop.

In discretionary SMC/ICT language: wait for the raid, forced liquidation, reclaim and MSS; then buy or sell the mitigation of the origin/liquidity level rather than pay the displacement candle. The implementation makes every part causal and executable.

## Frozen screen

- Bybit BTCUSDT and ETHUSDT USDT-linear perpetuals;
- one global pending/open slot;
- Tardis public Bybit quotes, trades and liquidations using `local_timestamp`;
- fit: 2023-01-01, 03-01, 05-01;
- conditional development: 2023-07-01, 09-01, 11-01;
- 1,024 immutable policies;
- observed BBO spread plus 12/18/24 bp additional round-trip stress;
- 0.5% planned NAV risk and 2 bp adverse funding reserve per crossed boundary;
- largest 10% positive 12-bp event keys excluded before global rerouting;
- 2024-2026 sealed;
- no credentials or orders.

The fit gate requires at least 20 filled trades, positive 24-bp mean and median, positive 12-bp return after counterfactual winner removal, at least two positive dates at 18 bp, top-five positive contribution no more than 50%, unresolved paths no more than 10%, and MDD below 25%. Development opens only for at most twelve complete fit survivors frozen without rule changes.

This sparse screen is not rank eligible. A survivor must be expanded under the unchanged rule across every remaining pre-2024 public sample with deeper queue reconstruction and exact funding before official 2024 can open.

## Validation

- scientific implementation SHA-256: `64de228aef9825c25a5194abb47cb87a67bd044e167efcc255a5513a61a43540`;
- part, combined Base64, GZIP and raw-source verification;
- Python compilation: PASS;
- six local causal/execution tests: PASS;
- exactly 1,024 candidates;
- trade-through-only fill;
- target-before-fill cancellation;
- post-only rejection;
- pending-slot occupation;
- adverse stop-rebound handling;
- counterfactual event exclusion.
