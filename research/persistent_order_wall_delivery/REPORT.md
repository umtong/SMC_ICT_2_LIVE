# Persistent executable-wall delivery — final decision

Result: `RES-20260730-PERSISTENT-ORDER-WALL-DELIVERY-001`  
Claim: `CLM-20260730-PERSISTENT-ORDER-WALL-DELIVERY-001` / issue #646  
Decision: `RETIRED_PERSISTENT_ORDER_WALL_FATAL_SCREEN_FAILURE`

## Economic hypothesis

The screen deliberately stopped inferring liquidity from a candle pivot. A price tick became a wall only after unusually large top-five executable size persisted before price arrived. Actual aggressive trades had to consume at least half of the activation quantity. One completed second then distinguished:

- `ABSORB`: size replenished and executable midpoint returned to the pre-wall side;
- `ACCEPT`: size remained depleted and executable midpoint remained beyond the wall;
- otherwise flat.

The nearest pre-existing persistent wall in the selected direction was the structural target. Entries and exits used actual Bybit quotes after fixed 500 ms, actual signed funding, one global BTC/ETH slot, fixed 0.5% NAV planned loss, 3x notional cap and additional 12/18/24 bp stress. There was no elapsed-time exit.

## Programization audit before outcome

The first successful market replay was opened only after the following semantic defects were repaired and regression-tested:

1. event extremes include every actual trade from first wall contact through completed adjudication;
2. funding position value uses the first observable midpoint at the funding timestamp;
3. a partial entry second cannot become a completed state-loss observation;
4. target/stop barriers touched before a candidate state second completes have priority;
5. the target wall must still be live at actual entry;
6. equal entry and previous-exit timestamps cannot receive favorable one-slot ordering;
7. official wide `book_snapshot_5` rows are expanded to exact ask/bid level identities;
8. workflow `pipefail` prevents `tee` from hiding runner failures.

The materializer verified the frozen source bundle and all internal file hashes. The final claim-local workflow completed every step successfully.

## Funnel

| Stage | Wall intervals | Consumed | Unambiguous absorb/accept | No pre-existing target | Invalid geometry/entry | Executable actions |
|---|---:|---:|---:|---:|---:|---:|
| March context | 6,842 | 344 | 262 | 224 | 34 | 4 |
| May development | 6,365 | 257 | 188 | 160 | 28 | **0** |
| July confirmation | 7,457 | 297 | 237 | 202 | 34 | **1** |

The wall detector itself was not sparse: every sample day produced thousands of persistent intervals and hundreds of consumed walls. The scarcity appeared only when the same displayed-wall ontology was required to supply a live pre-existing structural destination and valid entry geometry.

## Account result

| Stage | Actions | 12 bp | 18 bp | 24 bp |
|---|---:|---:|---:|---:|
| March context | 4 | 0.98549x | 0.98035x | 0.98030x |
| May development | 0 | 1.00000x | 1.00000x | 1.00000x |
| July confirmation | 1 | 0.99631x | 0.99499x | 0.99499x |

All five completed actions lost. Winner deletion therefore removed nothing and could not change the result. There is neither a broad Core nor a rare profitable Expansion in this exact mapping.

## What failed

The key defect is not a missing percentile or a weak model. It is the economic translation:

> A displayed resting limit wall is a source of executable resistance, but it is not the same object as SMC/ICT external stop/liquidation liquidity.

Using persistent displayed walls as both the source event and the scale-matched destination imposed the wrong ontology. It removed nearly every otherwise unambiguous consumption event and did not produce positive economics in the few survivors.

The exact family is retired without changing q95, five-second persistence, 80% presence, 50% consumption, 50% replenishment, 25% depletion, 80% beyond-state, target, stop, cost, symbol, risk, leverage or adding ML.

## Reusable lesson

A successor should keep the causal separation:

1. **External stop/liquidation pools define location and destination.** They must represent vulnerable positions and forced orders, not merely displayed quotes.
2. **Executable order-book behavior adjudicates resistance.** Replenishment, depletion, withdrawal and price progress should help decide rejection, acceptance or wait.
3. **Internal imbalance/FVG may improve entry, not create direction.**
4. **ML may compare actions only after the fixed-rule action surface shows positive cost-after information.**

The sparse first-day L2 sample cannot establish full-calendar performance even if a component survives. Official 2024–2026, ranking, risk search and order authority remain closed. No credentials or orders were used.
