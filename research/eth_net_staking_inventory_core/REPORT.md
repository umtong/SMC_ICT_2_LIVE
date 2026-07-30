# Ethereum net-staking inventory Core

**Result:** `RES-20260730-ETH-NET-STAKING-INVENTORY-001`  
**Decision:** `RETIRED_NET_STAKING_INVENTORY_FAILURE`  
**Official 2024–2026:** unopened  
**Ranking/live authority:** unchanged / none

## Economic question

The earlier validator-withdrawal studies measured only ETH released to execution-layer recipients. This route added the opposite inventory flow and defined completed-hour net staking as:

```text
beacon deposit ETH - principal-scale withdrawal ETH
```

Positive net flow represents inventory entering the staking pipeline; negative net flow represents principal-scale release. The sign was not forced into a trade direction. A fixed HGBT action-value policy compared long, short and flat after observing completed Bybit price/OI/account-ratio/funding state.

## Source authority and programization corrections

The final source passed before economic interpretation:

- 264 Xatu daily deposit partitions;
- 564,032 deposit rows and 564,032 unique proof-aware event keys;
- 6,314 common observable source hours;
- 17,291,369 aligned deposit ETH;
- 6,518,259.31 principal-release ETH;
- 10,773,109.69 net locked ETH;
- exact integer-Gwei conservation;
- fixed completed-hour plus 180-second source availability.

Four material source/chronology defects were corrected:

1. block root, pubkey and signature were not a unique deposit identity, so the Merkle deposit-proof hash was added;
2. Xatu UInt128 amounts and Unix-second timestamps were decoded from their physical representation;
3. net inventory was computed and conserved in integer Gwei instead of floating ETH;
4. raw daily deposits before Shapella withdrawal availability were incorrectly compared with the 6,314-hour paired series. The final source conserves net flow only over the common observable chronology and retains the raw deposit total separately.

The economic evaluator also excludes unresolved fit labels and marks, rather than strategy-closes, positions at development/confirmation boundaries.

## Frozen economic contract

- source event: prior-only rolling 720-hour q10/q90 tails of net locked ETH;
- controls: deposit upper tail and principal-release upper tail;
- market: canonical Bybit ETHUSDT;
- entry: source completion +180 seconds + fixed 500ms, then first later observable one-minute open;
- actions: long, short or flat;
- invalidation: completed event-hour extreme;
- objective: still prior-known opposite 24-hour external boundary;
- actual signed funding, adverse same-minute order, one global slot;
- 0.5% current-NAV planned loss, 3x cap, 13/18/24bp;
- no elapsed-time, scheduled or stage-boundary strategy liquidation;
- fit through August 2023, September–October development, unchanged November–December confirmation;
- no model refit after fit.

## Economic result

### Net-staking stream, 24bp

| Stage | ML trades | ML NAV | PF | Winner-deleted NAV | Response NAV | Source-sign NAV |
|---|---:|---:|---:|---:|---:|---:|
| Sep–Oct development | 8 | 9,819.95 | 0.337 | 9,753.59 | 8,912.26 | 8,053.69 |
| Nov–Dec confirmation | 10 | 9,813.33 | 0.478 | 9,644.08 | 7,507.05 | 6,747.88 |

The ML median trade was almost the complete planned loss in both stages. Top-five positive-PnL share was 100%. Raw 24bp action values were also negative:

- development long `-25.98bp`, short `-13.16bp` mean account value;
- confirmation long `-7.45bp`, short `-32.00bp`.

Thus the failure is not caused only by the model threshold. The full underlying action surface is negative under this geometry.

### Controls

- deposit-only development ML made `+0.81%` from three trades, but deleting its single winner left `9,900.25` and confirmation lost `3.90%` over eight stops;
- principal-release development ML lost `1.13%`; confirmation selected one winner only, and winner deletion left zero trades and `10,000`.

Neither control is a Core, and the net stream was inferior to the best sparse control in both forward stages.

## Core versus Expansion diagnosis

This route produced more than one thousand net shock events, so the failure is not event scarcity. It failed because the event-to-action mapping did not produce repeatable positive account value:

- both directions had negative raw account value;
- broad deterministic policies lost heavily;
- ML reduced the number of trades but remained negative;
- winner deletion worsened both forward stages;
- the best controls were one-to-three-trade tails rather than repeatable engines.

This is therefore an economic failure after programization repair, not a hidden Core blocked by source transport.

## Decision boundary

Retire the exact net-staking action family. Do not rescue it by changing deposit/release definitions, the 720-hour tails, source delay, target, invalidation, cost, risk or leverage after observing the result. Official 2024–2026 remains unopened.

The current protected-boundary accepted-delivery route remains the provisional rank-one Expansion. The missing component is still a frequent, winner-resistant ML Core based on a different economic mechanism.

## Reproduction

- workflow `30520701817`;
- source artifact `8750636543`, ZIP SHA-256 `cfc782501f14577447bf279a5ae140dc90caaca8e7680016bfbddea32dcd22c9`;
- economic artifact `8750651510`, ZIP SHA-256 `486974a5b8709f1df6dab29c254fea56d8eb9683428440f54b68d6d993f4168e`;
- full artifact `RESULT.json` SHA-256 `011bdfeabe80a45796dc22233a12e5782b1360e70b3beb1f495cfae2b9b55aae`.

No credentials, paper orders or live orders were used.
