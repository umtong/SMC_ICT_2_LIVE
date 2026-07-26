# Uniswap inventory-transfer ML economic continuation

Parent claim: `CLM-20260726-2110-ML-UNISWAP-HEDGE-TRANSFER-001`  
Continuation: `EXEC-20260726-ML-UNISWAP-ECONOMIC-001`  
Parent PR: #190

This branch does not introduce another strategy family. It freezes the economic stage already preregistered in PR #190 before consuming a source result.

## Trader-readable mechanism

1. A completed Uniswap V3 WETH–USDC/USDT swap bucket transfers actual WETH inventory.
2. Stablecoin inflow with WETH outflow is a completed WETH purchase; the opposite sign is a completed WETH sale.
3. After the frozen 120-second information delay, the nearest already-confirmed upper and lower ETH liquidity pools are frozen.
4. One HGBT plus the preregistered calibration rule estimates upper-pool-first probability.
5. The fixed cost-adjusted expected-value equation chooses LONG, SHORT or FLAT.
6. The selected pool is the target and the opposing pool is the stop. No elapsed-time liquidation exists.

## Chronology

- fit: 2021-05-05 through 2022-06-30;
- calibration: 2022H2;
- untouched confirmation: 2023H1;
- conditional development: 2023H2;
- official 2024H1 is not opened by this branch.

A confirmation or development failure retires the exact information unit without feature, threshold, model, cost, risk or leverage rescue. A full pre-2024 survivor proceeds to unchanged exact-Bybit reconstruction, then the preregistered risk/notional freeze and immediate official 2024H1 evaluation.

## Causal and account details

- canonical four Uniswap V3 pools and frozen Swap ABI;
- full normalized event ledger and request-response hash ledger retained;
- completed five-minute source buckets usable only after bucket end plus 120 seconds;
- first ETHUSDT minute open strictly after information availability;
- confirmed 15-minute pivots require two complete right-hand bars;
- partition-local labels cannot cross fit/calibration/confirmation/development boundaries;
- one global slot;
- adverse same-minute ordering and punitive structural source-boundary stop;
- minute-by-minute marked NAV, all UTC calendar days, and exact event-key winner-removal rerouting;
- no credentials or orders.
