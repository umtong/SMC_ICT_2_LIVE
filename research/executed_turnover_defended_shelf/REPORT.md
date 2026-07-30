# Executed-turnover defended-shelf control-transfer result

- Result: `RES-20260730-EXECUTED-TURNOVER-DEFENDED-SHELF-001`
- Claim: `CLM-20260730-EXECUTED-TURNOVER-DEFENDED-SHELF-001`
- Status: `RETIRED_2022_DETERMINISTIC_ECONOMIC_FAILURE`
- Pooled calendar-2021 defended-turnover-share q75: `0.046152640989`
- Total resolved action candidates, 2021–2022: `313`
- Official 2024–2026: unopened
- Orders: none

## Logic tested

A horizontal shelf is not treated as liquidity merely because two pivots look equal. The shelf must remain causally defended and must contain substantial **executed turnover** inside a narrow ATR-normalized band between the first and second defended pivot. The first close through that shelf consumes the defense. The first later five-minute retest chooses:

- `DEFENSE_FLIP_CONTINUE`: rejection from the broken side, delivery toward the next still-unconsumed external pool;
- `FAILED_BREAK_REVERSE`: reacceptance through the shelf into the old auction, rotation toward the frozen shelf base;
- flat otherwise.

BTCUSDT and ETHUSDT are testbeds only. FVG, OB, MSS, OTE, session and symbol identity are not gates.

## Programization and chronology

- Fifteen-minute pivots require two completed bars on each side and become usable only after the second right-side bar completes.
- The first defense must remain unconsumed through second-pivot availability.
- Defense turnover uses completed one-minute rows in `[first_pivot_available_at, second_pivot_available_at)`.
- A minute contributes only when volume is positive and `turnover/volume` lies inside the frozen shelf band.
- Distinct visits are distinct UTC 15-minute buckets with contributing turnover.
- Break, retest, target, stop and state-loss decisions use completed information only.
- Entry occurs at the first observed one-minute open strictly later than decision availability plus 500ms.
- An intervening completed minute cancels entry if target, stop or the action premise has already been consumed.
- Same-minute stop/target ambiguity is adverse stop first.
- Actual signed funding, one global slot, 0.5% current-NAV planned loss and 3x cap apply.
- No elapsed-time, session, UTC-day or research-stage strategy close is used.
- An unresolved boundary position is marked and keeps the slot.
- Exact top-five positive-event deletion removes event keys before rebuilding the full global-slot account.

Two fresh processes produced byte-identical candidate, result, report and validation hashes.

## Candidate distribution

The final action inventory contains 313 candidates across 2021–2022. The q75 state selected 32 actions in 2021 and 49 in untouched 2022. The broad all-shelf comparator produced 112 global-slot trades in 2021 and 159 in 2022.

## Untouched 2022 principal result at 24bp

| Policy | Trades | NAV multiple | PF | Median trade | H1 | H2 | Winner-deleted/rerouted | Median hold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Q75_FULL_MAP` | 49 | **0.907019x** | 0.3448 | −0.313140% | 0.951777x | 0.952975x | 0.864124x | 0.50h |
| `Q75_CONTINUE` | 31 | **0.927795x** | 0.2639 | −0.313140% | 0.974280x | 0.952288x | 0.903944x | 0.35h |
| `Q75_REVERSE` | 18 | **0.977608x** | 0.5215 | −0.321231% | 0.976903x | 1.000721x | 0.953494x | 0.625h |
| `ALL_SHELVES_CONTROL` | 159 | **0.799968x** | 0.5137 | −0.311782% | 0.950565x | 0.841572x | 0.700266x | 0.45h |

Exit composition at 24bp:

- `Q75_FULL_MAP`: 27 state exits, 13 stops, 9 targets;
- `Q75_CONTINUE`: 18 state exits, 10 stops, 3 targets;
- `Q75_REVERSE`: 9 state exits, 3 stops, 6 targets;
- `ALL_SHELVES_CONTROL`: 92 state exits, 32 stops, 35 targets.

This is a broad intraday failure rather than a sparse or multi-day-tail failure.

## Zero-cost diagnostic

At zero modeled round-trip cost in 2022:

- q75 full map: `0.978923x`;
- q75 continuation: `0.960970x`;
- q75 reversal: `1.018683x`, but median remained negative and winner-deleted/rerouted was `0.966037x`;
- all-shelf control: `1.057370x`, but median remained negative, H2 was negative and winner-deleted/rerouted was `0.884472x`.

Thus realistic costs did not destroy a strong broad edge. The q75 state itself was already negative before cost; the only positive zero-cost cells were unstable and winner-dependent.

## Calendar-2021 diagnostic

The 2021 q75 ordinary paths had positive zero-cost or low-cost headlines in some cells, but every median was negative and every exact winner-deleted path was below one. The untouched 2022 sign failure therefore did not arise from an unusually harsh 24bp assumption alone.

## Economic interpretation

Executed turnover near a repeatedly defended price band is more meaningful than geometry alone, but it still does not identify:

- whether the transacted inventory was net long or net short;
- which participants were passive defenders versus aggressive challengers;
- the entry-price distribution and leverage of the vulnerable cohort;
- hedge relationships across venues or instruments;
- whether a later OI decrease represents defender liquidation, attacker profit-taking or unrelated inventory transfer.

The shelf describes where substantial trading occurred, not who must pay after the break. That missing payer identity prevents a repeatable cost-surviving Core.

## Decision

Retire this exact executed-turnover shelf family. Do not rescue it with another pivot width, shelf tolerance, defended band, turnover quantile, retest count, target, stop, session, symbol side, cost, risk, leverage, FVG/OB gate or ML.

Calendar 2023 and official 2024–2026 remained sealed. Ranking and order authority are unchanged.
