# Aave V3 liquidation forced-flow — source and economic decision

**Result:** `RES-20260730-AAVE-ZENODO-LIQUIDATION-001`  
**Source result:** `RES-20260730-AAVE-ZENODO-LIQUIDATION-SOURCE-001`  
**Decision:** `RETIRED_PROGRAMIZATION_CORRECTED_Q3_ECONOMIC_FAILURE_PRE2024`  
**Work Claim:** #487

## Why the source was reopened

The prior Aave route was closed before market outcomes because keyless archive RPC endpoints could not return historical `LiquidationCall` logs. It was a transport failure, not negative-alpha evidence.

The later paper *A Cross-Chain Event-Driven Data Infrastructure for Aave Protocol Analytics and Applications* claimed a Zenodo record that does not resolve. The source gate therefore searched Zenodo independently and found the public `RED-LIQ-2026-v1` record instead:

- Zenodo record `21211303`;
- DOI `10.5281/zenodo.21211303`;
- file `red_liq_2026_v1_liquidations.jsonl.gz`;
- 2,111,476 bytes;
- Zenodo MD5 `81121c07651e59ab55844482e956a4d5` — matched;
- local SHA-256 `0f52862e275ecd09020c484eeb9be798177285a50bf60008fadaef1e6ad1b55d`.

The workflow artifact is `8738247959`, digest `sha256:962ac097266ff50089b6b1f679746bb68a4998bd1179277d5cb3c15cad02519c`.

## Source programization defect

The table contains 18,750 rows and reports 7,095 rows dated 2023. Those are not independent liquidations.

Every exact 2023 liquidation appears **fifteen times**. After exact transaction-level deduplication:

- raw 2023 rows: 7,095;
- unique 2023 liquidations: 473;
- unique blocks: 240;
- WETH/WBTC collateral-against-stable-debt five-minute event clusters: 241;
- WETH clusters: 196;
- WBTC clusters: 45.

Using the raw 7,095 rows would multiply event count and aggregate size by fifteen and manufacture false sample breadth. All economic work used only the 473 unique liquidations.

## Fixed trading interpretation

The economically readable forced-flow event was:

> Aave V3 seizes WETH or WBTC collateral while covering stablecoin debt, followed by a causally finalized five-minute Bybit response.

The strategy compared long, short and flat with:

- event availability delayed by block timestamp plus 180 seconds;
- first completed five-minute Bybit response;
- fixed 500 ms activation and the first later one-minute open;
- one global BTC/ETH slot;
- 0.5% current-NAV planned loss and 3x notional cap;
- actual Bybit funding and 12/18/24-bp execution paths;
- latest causally right-confirmed five-minute opposite pivot as the fixed protected origin;
- hard stop or completed protected-origin loss only; no elapsed-time or scheduled close.

Chronology was frozen as 2023H1 fit and 2023Q3 selection. Q4 could open only after Q3 survival.

## Raw structural economics

The H1 long path looked attractive but contained only 13 trades and had a −1R median trade:

| period/action | cost | return | trades | PF | exact winner-reroute |
|---|---:|---:|---:|---:|---:|
| 2023H1 long | 12 bp | +16.90% | 13 | 3.890 | +12.78% |
| 2023H1 long | 18 bp | +15.20% | 13 | 3.600 | +11.50% |
| 2023H1 long | 24 bp | +13.73% | 13 | 3.349 | +10.38% |

The unchanged interpretation then failed broadly in Q3:

| period/action | cost | return | trades | PF | exact winner-reroute |
|---|---:|---:|---:|---:|---:|
| 2023Q3 long | 12 bp | −9.47% | 36 | 0.423 | −9.72% |
| 2023Q3 long | 18 bp | −10.27% | 36 | 0.374 | −10.38% |
| 2023Q3 long | 24 bp | −10.89% | 36 | 0.336 | −10.89% |
| 2023Q3 short | 12 bp | −4.12% | 19 | 0.516 | −6.56% |
| 2023Q3 short | 18 bp | −4.42% | 19 | 0.482 | −6.91% |
| 2023Q3 short | 24 bp | −4.69% | 19 | 0.451 | −7.20% |

The H1 result was therefore a sparse regime-specific tail, not a persistent forced-flow engine.

## ML action-value result

Every Q3 policy was negative:

| policy | 24-bp return | trades | PF | exact winner-reroute |
|---|---:|---:|---:|---:|
| Ridge action value | −7.52% | 29 | 0.431 | −7.99% |
| HGBT action value | −5.42% | 18 | 0.345 | −9.77% |
| Logistic positive value | −7.13% | 28 | 0.445 | −7.60% |
| HGBT positive value | −3.66% | 21 | 0.619 | −4.68% |

The models did not show usable skill. Ridge/HGBT MAE was worse than action-specific constants. The long logistic AUC was 0.409 with Brier 0.180 versus 0.041 for the constant. The short logistic AUC was 0.647, but Brier remained worse than the constant and the account lost at every cost. No model passed the Q3 gate.

A Q4 long diagnostic happened to be +1.81% at 24 bp over 14 trades, but it was generated in the same local batch after Q3 had already failed. It is explicitly quarantined and is not confirmation evidence.

## Decision

The exact family is retired.

- Q4 evidence opening: **no**.
- Official 2024–2026 opening: **no**.
- Risk/leverage optimization: **no**.
- Ranking change: **no**.
- Credentials or orders: **none**.

The source was real after deduplication, but the economic effect changed sign across adjacent 2023 regimes and ML could not identify which regime would persist. More event-size thresholds, cluster windows, SMC gates, lower costs, risk or leverage would be adjacent rescue of a failed information unit.

The compact branch records source and decision evidence. The complete local evaluator and ledgers are not yet transported; do not merge it as a reusable implementation until that transport gap is resolved.
