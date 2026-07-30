# One-attempt-per-liquidity-draw programization audit

- Result: `RES-20260730-ONE-ATTEMPT-PER-DRAW-AUDIT-001`
- Claim: `CLM-20260730-ONE-ATTEMPT-PER-DRAW-AUDIT-001`
- Status: `RETIRED_CORRELATED_RETRY_NOT_FAILURE_CAUSE`
- Parent: `RES-20260730-IOF-FIRST-PULLBACK-FATAL-001`
- Parent source SHA-256: `326ca2f415935167ef6f1f072ac897a625ff515d7015ba691c9f2f7e80d683eb`
- Official 2024–2026: unopened
- Orders: none

## Programization question

The parent higher-timeframe-order-flow route generated several internal-break and first-midpoint-pullback candidates while one still-unconsumed external-liquidity target remained the active draw. This audit tested whether the program incorrectly treated those correlated retries as independent trades.

The signal, 4h state, 15m displacement, first 5m pullback, protected-origin stop, external target, 500ms execution, funding, costs, risk, cap and one-slot account were unchanged.

## Fixed one-attempt policy

1. Build the full parent candidate inventory without using outcomes.
2. Sort by executable entry time, symbol and event ID.
3. Define one thesis as `(symbol, direction, target_level_id)`.
4. Consume the only attempt at the first executable candidate for that thesis.
5. Ignore every later candidate with the same thesis key, whether the first attempt later wins, loses, remains unresolved or is blocked by an already-open global-slot position.
6. For winner-deletion stress, delete the selected positive event IDs first, then rebuild both thesis-attempt consumption and the entire one-slot account from the beginning.

This is not a cooldown, retry count or outcome-dependent rearm rule.

## Candidate reduction

- Parent causal candidates: **1,940**
- One-attempt causal candidates: **1,145**
- Reduction: **40.98%**
- 2022 candidates: 629 → 369
- 2023 candidates: 604 → 386

## Principal 24bp results

| Year | Policy | Trades | NAV | PF | Median | H1 | H2 | MDD | Winner-deleted/rerouted | Median hold |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | Parent | 279 | 0.698626x | 0.6562 | −0.500000% | 0.927978x | 0.752848x | 30.72% | 0.649479x | 4.65h |
| 2022 | One attempt | 235 | **0.709470x** | 0.5922 | **−0.500000%** | 0.881496x | 0.804848x | 29.46% | **0.654549x** | 4.48h |
| 2023 | Parent | 282 | 0.713874x | 0.6551 | −0.500000% | 0.836538x | 0.853367x | 29.64% | 0.648659x | 5.09h |
| 2023 | One attempt | 241 | **0.737753x** | 0.6435 | **−0.500000%** | 0.846424x | 0.871612x | 27.25% | **0.673725x** | 4.98h |

The one-attempt policy modestly improved terminal NAV and drawdown because it removed correlated losses. It did not change the economic sign, the stop-dominated median or half-year failure.

At 24bp the one-attempt paths contained:

- 2022: 165 stops and 70 targets;
- 2023: 168 stops, 71 targets, one stop-first collision and one marked boundary position.

## Cost paths

One-attempt NAV remained negative at every tested cost:

- 2022: 0.771446x / 0.737946x / 0.709470x at 12/18/24bp;
- 2023: 0.847999x / 0.786128x / 0.737753x at 12/18/24bp.

Thus realistic cost is not hiding a strong Core. The parent observable state is broadly negative even after retry correlation is removed.

## Independent replay

One full scientific process generated the parent and reduced candidate inventories and both account paths. A second fresh process loaded the frozen candidate inventory, independently reloaded only the canonical one-minute, mark and funding data, and replayed every parent, one-attempt and winner-deleted account.

- Parent candidates: identical event/string fields; maximum numeric difference `4.44e-16`.
- One-attempt candidates: identical event/string fields; maximum numeric difference `4.44e-16`.
- Policy grid: maximum numeric difference `1.19e-11`.
- Every account ledger: identical nonnumeric state and maximum numeric difference below `1.55e-11`.

## Decision

Correlated repeated attempts were a real program-design issue, but they were not the root cause of failure. The fixed observable state—confirmed higher-timeframe swing sequence, one internal-liquidity displacement and first midpoint pullback—does not reliably identify sponsored delivery.

Retire this programization path. Do not create another cooldown, retry, rearm, confirmation, FVG/OB, target, stop, cost, risk, leverage or ML variant. A successor requires materially new contemporaneous information about direct forced flow, passive absorption/replenishment, or another causal inventory transition.
