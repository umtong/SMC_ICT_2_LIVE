# Independent q=0.99 direct-Core source-authority audit

**Result:** `RES-20260730-DIRECT-CORE-Q099-SOURCE-AUTHORITY-001`  
**Decision:** hard-invalid for ranking, integration, sizing and deployment because the claimed source authority is not transported.

## Why this audit was necessary

The later compact lifecycle/universality report claimed that an execution-aligned BTC/ETH direct-utility Core selected `q=0.99` and produced an official 15 bp multiple of `1.205888x` over 473 trades. The compact carrier contains no exact source, fitted model, scored tape, trade ledger or daily NAV for that path.

A separate source-preserving branch contains the SHA-identified materialized direct-Core implementation and its own frozen `pre_grid.csv`. That is the only identified executable dependency available for an independent authority check.

## Exact contradiction

The transported source's frozen grid reports:

| q | eligible | 2022 ordinary trades | 2023 ordinary trades | 2022 rerouted trades | 2023 rerouted trades |
|---:|---|---:|---:|---:|---:|
| 0.985 | true | 385 | 79 | 386 | 78 |
| 0.990 | false | 273 | 55 | 272 | 54 |

The source selection code requires all ordinary and winner-rerouted 2022/2023 growth values to be positive and both ordinary annual trade counts to be at least 60. Therefore `q=0.99` cannot be selected from this source/output pair.

This is not a small metric discrepancy. It changes the selected policy and invalidates every later official account number attributed to a `q=0.99` selection.

## Interpretation

The later result may have come from a materially different untransported scientific dependency. It may also reflect runtime-sensitive nonlinear partitions already observed in earlier audits. Neither possibility authorizes use of the compact result.

The finding is therefore not negative-alpha evidence against an unknown exact implementation. It is a **hard source-authority failure**:

- no exact source that selects `q=0.99`;
- no fitted models;
- no training-sample fingerprint;
- no scored candidate tape;
- no complete trade ledger;
- no daily NAV.

## Decision boundary

Do not combine this Core with the protected-boundary Expansion, place it in the cumulative ranking, optimize its risk/leverage, or use it for live-system design. Reopen only if the exact dependency set is recovered and two independent replays reproduce the same pre-grid, selected q, trades and daily NAV.

No strategy parameter, cost, risk, leverage, credential or order was changed or used in this audit.
