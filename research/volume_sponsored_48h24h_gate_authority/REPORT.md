# Frozen 48h/24h sponsored-lifecycle gate and authority audit

**Result:** `RES-20260731-48H24H-GATE-AUDIT-001`  
**Status:** `HARD_INVALID_PARENT_PARITY_FAILURE_UNTRANSPORTED_DATA_TRANSFORM_AUTHORITY`  
**Target:** not met  
**Ranking/live authority:** unchanged / none  
**Orders:** none

## Why this work was opened

PR #578 retired the frozen 48h sponsored-breakout / opposite-24h-channel parent even though its 2022 and unchanged-2023 full-year accounts and exact top-five-event-deletion/full-rerouting paths were positive. It was blocked by three disconnected diagnostics: fewer than 60 completed 2022 trades, a negative median trade, and a negative 2023H2. The later Core→reactivation audit showed that a single median gate can incorrectly suppress a coherent positive account policy.

This audit therefore asked whether the exact parent had been overfiltered. It changed no strategy rule. Exact parent source/result parity was mandatory before any favorable or unfavorable economic interpretation.

## Frozen parent

- completed one-hour close beyond the prior 48 completed hours;
- prior-only completed-hour log-turnover `z168 > 2.2706072565238586`;
- BTC long, ETH long and ETH short;
- first complete one-minute open strictly later than decision availability plus 500 ms;
- 2ATR20 hard stop;
- completed opposite prior-24h channel loss as structural exit;
- actual signed funding, adverse stop execution, one global slot;
- fixed 0.5% current-NAV planned loss, 3x cap and 24 bp principal cost;
- no elapsed-time or scheduled liquidation.

## Exact reproduction sequence

1. Recovered the readable PR #578 evaluator and its frozen constants.
2. Reused the registered Drive canonical BTC/ETH partitions for 2021, 2022, 2023, 2024H1/H2, 2025H1/H2 and 2026H1. The sixteen ZIPs passed archive integrity and their internal file hashes were verified.
3. Reconstructed the 64 dependencies used by the evaluator: one-hour and one-minute trade bars, one-minute mark price and funding events for eight partitions and two products.
4. Replayed under the declared environment: CPython 3.13.5, NumPy 2.3.5, pandas 2.2.3 and PyArrow 18.1.0.
5. Executed two fresh complete processes. Result, candidate tape, parent outcome tape and selected trade tapes were byte-identical.

## Parent parity failed

| Period | PR #578 expected | Accessible canonical replay | Difference |
|---|---:|---:|---:|
| 2022, 24 bp | `1.303110760217x`, 51 trades | `1.302590490275x`, 51 trades | `-0.000520270x` |
| 2023, 24 bp | `1.199384259018x`, 75 trades | `1.193509371694x`, 75 trades | `-0.005874887x` |
| 2024–2026, 24 bp | `1.352531855524x`, 143 trades | `1.434263599877x`, 141 trades | `+0.081731744x`, two trades fewer |

The mismatch survives the exact declared runtime. It is also identical when the repository's prior pandas export is used instead of the raw registered partitions. Runtime and one local-cache implementation are therefore excluded as explanations.

## Missing authority

The PR records a 64-file tree fingerprint `62bc91ae...`, but it does not transport the exact 64 files, a per-file hash ledger or the deterministic transform that created them. The accessible registered dependencies produce a different explicit tree fingerprint, `6dbf5f3c...`, under the hash method recorded in `DATA_BINDING.json`.

There is also a schema boundary that is not represented in the PR: the accessible canonical one-hour bars expose `is_complete`, while accessible one-minute trade and mark streams expose `observed`. PR #578 names `is_complete` for all three. This audit maps `observed` only as a compatibility alias and otherwise preserves the parent semantics. That is enough to reproduce the pre-2024 trade counts but not the account values or official tape.

A repository and Drive search for the declared tree fingerprint found only registry references, not a recoverable data artifact. Therefore at least one material data snapshot or transformation dependency was not transported.

## Quarantined current-canonical diagnostic

The current registered-canonical replay is reported only to prevent lost evidence. It is **not** a ranked or fresh-OOS result because exact parent parity failed and the official interval was already exposed.

At 24 bp it produced:

| Path | Multiple | Trades | Geo/day | PF | Marked MDD |
|---|---:|---:|---:|---:|---:|
| ordinary | `1.434264x` | 141 | `0.039553%` | 1.828 | 8.09% |
| top-five parent events deleted, full reroute | `1.271006x` | 144 | `0.026298%` | 1.551 | 7.75% |
| top 10% of all selected trades deleted as parent keys, full reroute | `1.129110x` | 145 | `0.013316%` | 1.271 | 10.06% |

The holding decomposition still identifies an Expansion rather than a steady day-trading Core:

- `<=24h`: 54 trades, `-3,405.04` USDT;
- `24–48h`: 30 trades, `-1,018.40` USDT;
- `48–120h`: 37 trades, `+2,428.06` USDT;
- `>120h`: 20 trades, `+6,338.02` USDT.

Thus all positions closed within 48 hours lost in aggregate, while multi-day delivery supplied the entire surplus. This qualitative diagnosis agrees with the parent's Expansion interpretation, but it cannot repair the missing source/result authority.

## Decision

This audit cannot truthfully conclude either that the original gates were overfiltering or that the original retirement was an economic failure. The exact parent cannot be reproduced from the accessible registered canonical data under the declared runtime.

`RES-20260731-48H24H-GATE-AUDIT-001` is therefore:

`HARD_INVALID_PARENT_PARITY_FAILURE_UNTRANSPORTED_DATA_TRANSFORM_AUTHORITY`.

Consequences:

- do not rank or integrate either the PR #578 headline or this favorable current-canonical diagnostic;
- do not tune another channel, lifecycle, threshold, risk, leverage or ML filter;
- preserve the result only as a source/programization failure and qualitative Expansion diagnostic;
- recover the exact data/transform dependency only if the family becomes decision-critical; otherwise move to a materially different Core information source.

This is a programization correction, not negative-alpha evidence and not a live-trading permission.
