# Stablecoin issuance ML economic continuation

This is an execution continuation of `CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001`, not a second strategy family.

## SMC/ICT explanation

A confirmed USDT/USDC mint adds deployable crypto-dollar inventory and a burn removes it. After the frozen confirmation delay, the model observes the already-known BTC/ETH 60-minute buy-side and sell-side liquidity. It estimates which side is drawn first. The selected pool is the target and the opposite pool is the structural stop; no elapsed-time liquidation exists.

## Fixed path

- train: 2021;
- calibrate: 2022H1;
- untouched confirmation: 2022H2;
- conditional development: 2023;
- one HGBT, one isotonic map, twelve named features;
- one global BTC/ETH slot;
- next-minute USD-M proxy entry;
- actual Binance funding proxy and 12/18/24-bp identical-path replay;
- exact top-10% positive-event exclusion before rerouting;
- broad risk/notional search only after the unchanged 2023 gate;
- 2024H1 must open immediately after a complete pre-2024 strategy is frozen.

The workflow waits only for a decision-ready source artifact. A source failure closes the route; a source pass executes this screen immediately. No credentials or orders are used.
