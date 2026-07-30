# BTC–ETH relative network-demand allocation Core — stage-1 decision

- Claim: `CLM-20260730-RELATIVE-NETWORK-DEMAND-CORE-001`
- Status: `RETIRED_PRE_ACCOUNT_SUBCOST_OR_BASELINE_INFERIOR`
- Official 2024–2026: unopened
- ML/risk grid: unopened
- Credentials/orders: none

Pinned Coin Metrics BTC/ETH native-fee, transaction and active-address data passed source verification. Each day was delayed 48 hours. The on-chain score selected only the contract; broad direction came only from the completed prior 24-hour common BTC/ETH return.

| Period | Daily decisions | 24bp mean | Median | PF | Winner-removed mean |
|---|---:|---:|---:|---:|---:|
| 2022 | 365 | -23.71bp | -57.88bp | 0.845 | -71.23bp |
| 2023 | 364 | -12.38bp | -33.02bp | 0.859 | -39.83bp |

The on-chain selector beat the price-only allocator by only `+2.75bp` gross in 2022 and `+7.67bp` in 2023; both increments became negative after removing positive tails. It underperformed the peer control in 2022 and only modestly beat it in 2023. All four half-year 24bp means were negative.

This is a dense, broad economic failure rather than a source or implementation failure. No allocation threshold, weighting, delay, common-direction rule, holding horizon, ML, risk/leverage or chart-state rescue is authorized.
