# Minimal ML movement-hazard OCO

Claim: `CLM-20260726-1730-ML-HAZARD-OCO-001`

## One model, one payoff

This study predicts whether near-term movement will be large enough to reach either already-known external liquidity boundary. It does **not** predict direction.

In SMC/ICT language:

1. completed 30-second and 120-second highs/lows define nearby external buy-side and sell-side liquidity;
2. a nonlinear movement-hazard model decides whether price is likely to leave the current dealing range;
3. when the model accepts the state, independent conditional orders are armed above and below the frozen liquidity boundaries;
4. the first realized displacement selects direction;
5. the opposite order remains exposed through a modeled non-atomic cancellation interval;
6. a second trigger before cancellation flattens adversely;
7. a single trigger exits only at its frozen target or protective stop;
8. no elapsed-time position liquidation exists.

The economic question is whether movement-hazard information can pay for two conditional orders, trigger-to-fill delay, cancellation risk, spread, fees and whipsaw losses.

## Deliberate minimalism

- one `HistGradientBoostingClassifier` plus a logistic baseline;
- no direction model;
- no FVG, order block, breaker, OTE, session, sweep-entry or cross-venue route library;
- BTCUSDT only in the initial fatal screen;
- four score tails, two structural barrier scales, two target/stop payoffs and four pending TTLs: 128 immutable policies;
- no risk/leverage rescue of a non-positive base edge;
- conditional 2023 opens only after every frozen fit gate passes;
- 2024-2026 are rejected by code.

## Frozen data and chronology

The workflow reuses completed 100-ms BTCUSDT states from parent artifact `8626087323`:

- fit source: `2022-07-01_BTCUSDT_state.parquet`;
- conditional untouched source: `2023-07-01_BTCUSDT_state.parquet`;
- parent digest: `sha256:90594acc23e63e97e83347f9b07eb9ac260ba7bb1b87eb72052287a8328ad4a1`.

The fit day is split chronologically before outcomes:

- `00:00-12:00`: model fit;
- `12:00-18:00`: threshold calibration;
- `18:00-24:00`: untouched fit confirmation.

## Execution contract

- completed-state decisions only;
- independent upper/lower conditional orders around frozen structural liquidity;
- explicit acknowledgement, trigger-to-fill latency and non-atomic opposite cancellation;
- one global pending/open slot;
- adverse double-trigger flattening;
- unresolved accepted positions receive the full planned stop;
- identical 12/18/24-bp cost paths;
- counterfactual top-10% winner exclusion reroutes the full global slot path;
- no credentials or orders.

## Result

`RES-20260726-HAZARD-OCO-V2-001` is a hard-valid negative fatal screen.

- fit event rows: **10,236**;
- frozen policies: **128**;
- HGBT ROC AUC: **0.8529**;
- HGBT average precision: **0.00840**;
- positive movement-hazard prevalence: **0.04885%**;
- candidate trade-count range: **4–207**;
- positive policies at 12/18/24 bps: **0 / 0 / 0**;
- fit-gate survivors: **0**;
- conditional 2023 opened: **no**;
- 2024-2026 opened: **no**;
- orders: **none**.

The strongest 24-bp policy used HGBT's 98.5th percentile, slow structural barriers, a 20-bp trigger, 40-bp target, 20-bp stop and 30-second pending TTL. It made 96 trades but returned **−0.5712%**, with mean **−5.946 bp**, median **−23.703 bp**, PF **0.7723**, and **−1.4182%** after the largest 10% winners were removed.

Movement hazard was statistically distinguishable, but the tradable payoff was not. The model identified extremely rare large moves; two-sided trigger friction, whipsaw and costs consumed the effect. Direction-free prediction did not solve the economic problem.

The original runner wrote a complete zero-survivor result and exited with code 2. Workflow `30198062051` changed only result handling: exit code 2 is accepted only when the exact frozen output proves zero survivors, no later-period opening and no order path. The successful artifact is `8630758968`, digest `sha256:d72265a92191ee97eff6f1851bb83db4f920cc8d2fd3ca3aa774aa02d63b9763`.

## Decision

Retire this exact nonlinear movement-hazard two-sided OCO family. Do not tune score quantiles, trigger barriers, targets, stops, pending TTLs, cancellation assumptions, risk rate or leverage under the same information unit. Reopen only with a materially different source of directional information or an order mechanism that changes the payoff rather than polishing this negative family.
