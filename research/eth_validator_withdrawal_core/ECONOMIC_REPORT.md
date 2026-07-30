# Ethereum validator-withdrawal supply/absorption economic decision

**Result:** `RES-20260730-ETH-VALIDATOR-WITHDRAWAL-ECONOMIC-001`  
**Status:** `RETIRED_PRE2024_ECONOMIC_FAILURE`  
**Official 2024–2026:** unopened  
**Orders:** none

## Economic question

EIP-4895 validator withdrawals deliver ETH from the consensus layer into execution-layer recipient balances. The fixed question was not `withdrawal = sell`. It compared:

- **supply acceptance short:** a large completed withdrawal hour is followed by downside price efficiency;
- **absorption long:** the same external ETH delivery fails to push price lower and demand absorbs it;
- **flat.**

The event was the prior-only rolling 30-day upper decile of completed hourly withdrawal amount. The source became usable after the completed source hour plus a fixed three-minute confirmation delay. Any order then waited the project-wide 500ms latency and used the first later observable ETHUSDT one-minute open.

Longs used the completed event-hour low as structural invalidation and the prior-only 24-hour high as objective. Shorts used the event-hour high and prior-only 24-hour low. Discovery risk was fixed at 0.5% of current NAV with a 3x notional cap. Exact signed funding and 13/18/24bp costs applied. There was no elapsed-time or scheduled exit.

## Source authority

The source gate passed before Bybit price was opened:

- 264 daily partitions from 2023-04-12 through 2023-12-31;
- 29,982,950 withdrawal rows;
- globally contiguous indices `0..29,982,949`;
- 6,314 completed hourly source rows;
- 8,113,549.49 ETH;
- 1,084,824 unique validators and 70,133 recipient addresses.

Three source-programization defects were corrected before economic interpretation:

1. Xatu stores ClickHouse UInt128 amounts as 16-byte little-endian fixed binary.
2. `slot_start_date_time` is physically stored as Unix seconds, not an ISO string.
3. Parquet physical row order is not guaranteed to follow withdrawal index; validation must sort the protocol key.

## Chronology

- Fit: 2023-04-12 through 2023-08-31; only actions resolved before September entered training.
- Forward development: 2023-09-01 through 2023-10-31.
- Frozen confirmation: 2023-11-01 through 2023-12-31.
- The model was not refit after the fit interval.

The final tape contained 550 shock events and 1,007 long/short counterfactual actions. Training used 388 fully resolved actions; development and confirmation contained 339 and 279 actions.

## Forward development

At 24bp, the fixed observable-response rule selected 74 global-slot trades and ended at `10,237.18 USDT`:

- total return `+2.3718%`;
- PF `1.099`;
- 28 targets and 46 structural stops;
- median trade approximately the full planned `-0.5%` loss;
- top five winners contributed `42.96%` of positive PnL.

The action-value HGBT policy did not improve this path. It selected 16 trades and ended at `9,784.50 USDT`, PF `0.502`. Removing its two largest positive event keys before full slot rerouting reduced NAV to `9,665.38 USDT`, PF `0.221`.

## Frozen confirmation

The unchanged fixed-response rule reversed sign immediately:

| Cost | Trades | End NAV | Return | PF | Targets / Stops |
|---:|---:|---:|---:|---:|---:|
| 13bp | 72 | 8,462.01 | -15.38% | 0.385 | 18 / 54 |
| 18bp | 72 | 8,346.92 | -16.53% | 0.336 | 18 / 54 |
| 24bp | 72 | 8,232.29 | -17.68% | 0.286 | 18 / 54 |

The frozen ML policy selected four confirmation trades. All four hit structural stops, leaving `9,802.84 USDT` at 24bp.

Raw confirmation long actions were relatively stronger than shorts, but this is not an admissible rescue. At 24bp the 140 long actions had positive mean account value of only `2.83bp`, a `-50bp` median and 31.43% positive share. Long actions had been negative in fit and development. Selecting long-only after observing November–December would be a post-outcome regime filter.

## Decision

The failure is not a transport failure or a hidden timestamp defect. The full source chronology, fixed latency, Bybit state, action geometry, funding, global slot and account calculations reproduced in GitHub Actions.

The economic failure is structural:

- a large validator-withdrawal hour does not identify how much ETH becomes immediate sell inventory;
- September–October's modest positive response policy did not persist for the next two months;
- the ML policy found weak rank information but no cost-surviving action policy;
- the only apparently improving post-hoc direction is inconsistent with earlier periods;
- risk or leverage would magnify a sign-unstable state rather than create alpha.

Retire this exact hourly upper-decile supply-acceptance/absorption family. Do not tune the flow threshold, source delay, objective, invalidation, cost, risk or leverage from these outcomes. The 2024–2026 interval remains unopened and the cumulative ranking is unchanged.

## Reproduction

- Full source workflow: `30514436534`; artifact `8748379469`; ZIP SHA-256 `f6c90bb97d2dd9b0d5d140b4f09822589efc51a3f0c7d704768a432595dfa001`.
- Economic authority: commit `3085f87c710cde0b2faea880d7c81d0020128028`; workflow `30516524011`; artifact `8749088855`; ZIP SHA-256 `682836da3e81ebabe20e5501ccc334ddaee048e30661ca7e240b7b6f4f0cc938`.
- Canonical Bybit pandas export ZIP SHA-256 `950ad2ee0f5d6df729c11a15b817e30e19ead754a35385e5535233d0af8e6c02`.
