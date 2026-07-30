# First high-resistance retest after external-pool flow state

Result: `RES-20260730-EXTERNAL-POOL-FIRST-RETEST-001`  
Claim: `CLM-20260730-EXTERNAL-POOL-FIRST-RETEST-001` / issue #721  
Decision: `RETIRED_PRE2024_FIRST_SOURCE_RETEST_FAILURE`

## Logic

The retired immediate-entry family #709 proved that a five-second acceptance/rejection state should not be chased at market. This successor therefore required the consumed external-liquidity source to be touched again and to act as high resistance on its **first** retest. A failed first retest ended the setup; no second chance, FVG/OB checklist or threshold grid was allowed.

The retest had to finish on the selected side of the source with positive trade-direction progress, majority dwell and signed turnover. Entry followed the completed retest plus 500 ms. Stop was beyond the protected retest extreme and target remained the original pre-existing external pool. No elapsed-time or dynamic five-second exit was used.

## Funnel

- parent fixed-state candidates: 3,831;
- no later source retest: 459;
- first retest failed high-resistance confirmation: 3,148;
- target consumed before entry: 6;
- invalid geometry: 1;
- final retest candidates: 217.

The route remained usable rather than vanishing: development contained 80 candidates and confirmation 67.

## Account result

| Stage | Trades | Zero cost | 12 bp | 18 bp | 24 bp |
|---|---:|---:|---:|---:|---:|
| March-April development | 79 | 1.11959x | 0.87957x | 0.81771x | 0.79073x |
| May-June confirmation | 67 | 1.09664x | 0.87233x | 0.82121x | 0.80062x |

The zero-cost PF was 1.769 and 1.898. This is a real improvement over immediate entry: the first retest isolated some gross economic information in both forward stages. It still did not leave enough value after realistic execution.

## Action decomposition

Rejection was the stronger branch but did not pass the frozen cost requirement:

| Stage | Rejection 12 bp | Rejection 24 bp |
|---|---:|---:|
| Development | 0.99045x | 0.92997x |
| Confirmation | 1.03583x | 0.97861x |

Acceptance was negative after cost in both stages. Selecting rejection alone after observing these paths would be post-outcome action selection, so it is not promoted as a result.

The median distance from source to post-confirmation market entry was about 4.22 bp in development and 2.29 bp in confirmation. That alone does not explain the full 12-24 bp deficit, but it confirms the remaining programization issue: after identifying the source as high resistance, the implementation again crossed the spread only after price had moved away.

## Decision

The exact confirmed-first-retest market-entry family is retired. Do not rescue it with a second retest, different five-second rule, source radius, target, stop, cost, symbol, risk, leverage, acceptance-only/rejection-only post-selection, FVG/OB gates or ML.

A distinct action may be tested separately:

> after the original state is complete, place a resting source-level limit and require actual one-tick penetration for conservative fill; use the already-known structural stop and target.

That is a different execution hypothesis—capturing the high-resistance rebalance itself rather than confirming and chasing it—and must be frozen before outcomes. Official 2024-2026, ranking, ML and order authority remained closed. No credentials or orders were used.
