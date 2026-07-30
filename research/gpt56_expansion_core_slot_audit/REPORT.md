# Protected-boundary Expansion × direct-utility Core slot audit

**Result:** `RES-20260730-GPT56-EXPANSION-DIRECT-CORE-SLOT-DIAGNOSTIC-001`  
**Decision:** diagnostic only; target not met; no ranking or live authority.

## Question

Could the frequent, short-holding direct-utility Core fill idle periods between the current protected-boundary Expansion trades without blocking the rare long-duration price-delivery winners?

Both families were replayed from their published source contracts in one global BTC/ETH slot. Open positions were never preempted. Exact timestamp ties were tested with both Expansion and Core priority. Costs, funding, latency, structural exits, risk and leverage were not tuned.

## Nominal result

At 15 bp, Expansion priority produced 32.1749x and 0.381338%/day over 479 trades; Core priority produced 34.9452x and 0.390429%/day over 510 trades. At 24 bp the corresponding paths were 19.1531x and 20.8158x, still far below 1%/day.

The Core contribution was economically small. At 18 and 24 bp the Core trades selected in the combined idle intervals had negative aggregate PnL; almost all account growth came from the Expansion family.

Deleting the top 10% of positive selected event keys and rebuilding the entire slot path reduced the 15-bp paths to 0.4984x and 0.3034x. More trade count did not convert the system into steady-compounding day trading.

## Programization boundary

The direct-utility source reproduced its published 685-trade 15-bp result under scikit-learn 1.7.2 and 1.8.0. An independent scikit-learn 1.6.1 replay produced a different selected quantile and materially different trade tape. The source carrier does not retain the exact fitted models, scored candidates, full trades or daily NAV used for the headline result.

A separately tested Ridge action-value control had no 24-bp score quantile that was positive and winner-reroute-positive in both 2022 and 2023. The apparent Core therefore depends on unstable nonlinear tail partitions rather than a broad repeatable economic relation.

## Decision

Do not rank or deploy the nominal hybrid. Do not tune priority, risk, leverage or winner definitions. Close this integration path and move to a common four-asset action-value Core that excludes symbol identity and must survive 24-bp costs in both 2022 and unchanged 2023 before official evaluation.

No credentials, paper orders, testnet orders or live orders were used.
