# ML L2 external-liquidity raid acceptance router

Claim: `CLM-20260726-1740-ML-L2-RAID-001`

## One mechanism

An SMC/ICT trader distinguishes a liquidity raid that is **accepted** from one that is **rejected**. This study turns only that distinction into one ML problem.

1. Freeze the immediately preceding complete five-minute high and low as external liquidity.
2. In the next five-minute interval, accept only the first executable BBO crossing of exactly one side.
3. Wait for one complete second of post-raid L2 and aggressive-flow information.
4. Freeze two structural destinations:
   - acceptance: another half prior-range of delivery beyond the raided boundary;
   - rejection: the prior five-minute equilibrium.
5. One calibrated nonlinear model estimates which destination is reached first.
6. The probability and actual executable target/stop distances create one LONG/SHORT/FLAT expected-value decision after 24 bp.
7. Entry is the first valid BBO at least 100 ms after the completed decision state. There is no elapsed-time liquidation.

The model does not search for FVG, order block, breaker, OTE, CISD or candle variants. Those may describe the event to a trader, but they are not separate strategies or model features.

## Ten fixed features

Every directional feature is normalized into the raid direction.

- top-five depth imbalance;
- microprice skew;
- one-second aggressive flow;
- one-second withdrawal;
- one-second refill;
- one-second flow efficiency;
- one-second imbalance change;
- spread;
- thirty-second volatility;
- raid depth at the completed decision state.

There is one `HistGradientBoostingClassifier`, one frozen isotonic calibration and no model, feature-subset, probability-threshold, barrier, latency, risk or leverage grid.

## Data reuse and chronology

The screen reuses immutable completed 100 ms BTCUSDT top-five L2/trade states from `RES-20260726-BYBIT-L2-RESILIENCY-FATAL-001`:

- workflow run `30182786091`;
- artifact `8626087323`;
- artifact digest `sha256:90594acc23e63e97e83347f9b07eb9ac260ba7bb1b87eb72052287a8328ad4a1`;
- fit state `2022-07-01`, SHA-256 `da8f581e64ba6f5305c57c0d76403b262d1b0ff48ad540e19302f6bf7416c38b`;
- untouched development state `2023-07-01`, SHA-256 `8872cd2a21960666f10f3d35c788a16faefd007d02a30389079def794e90389f`.

The fit day is split chronologically: 00:00–12:00 train, 12:00–18:00 calibration and 18:00–24:00 confirmation. A label is admitted only when it resolves before its partition boundary. The 2023 parquet is not read unless every fit gate passes. Every 2024–2026 source is prohibited.

## Execution and account contract

- BTCUSDT only in the fatal screen and one global slot.
- Structural target and stop are frozen before entry.
- Same-state dual touch, a source gap and the day boundary receive the structural stop.
- NAV-risk quantity uses 1% planned loss including round-trip cost, a 3x notional cap and 5% of executable top-quote quantity.
- Identical actions are replayed at 12, 18 and 24 bp.
- The largest positive 10% of 12-bp event keys are excluded before complete slot and NAV replay.
- No credentials, paper/testnet/live orders or rank permission exist.

## Kill/open gate

Untouched 2023 opens only if the fit confirmation:

- has at least 40 resolved labels;
- reaches AUC at least 0.55 and beats the exact distance-only first-passage baseline by at least 0.02 AUC;
- has positive Brier skill over the distance baseline;
- produces at least 20 trades at 18 bp;
- is profitable at 18 and 24 bp;
- has a positive 12-bp median and positive 12-bp winner-removed return;
- is positive in both halves of the confirmation interval at 18 bp;
- reaches at least 1% sample-day growth at 24 bp after winner removal.

Failure retires this exact information unit. It does not authorize adjacent tuning.
