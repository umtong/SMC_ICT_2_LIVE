# Bybit L2 ephemeral-wall spoofing-proxy fatal screen

**Result:** `RES-20260730-L2-EPHEMERAL-WALL-CORE-001`  
**Status:** `RETIRED_SPARSE_OR_SUBCOST_OR_WINNER_DEPENDENT`  
**Account / ML / official period:** unopened  
**Orders:** none

## Mechanism and limitation

Recent Bitcoin order-book research reports return predictability associated with spoofing intensity, while separate Level-3 work emphasizes that placement distance and individual-order history are important. The registered source is only completed top-five L2 snapshots plus public trades. The event is therefore a conservative **ephemeral displayed-wall proxy**, not a manipulation label or proof of spoofing.

The test asks whether an extreme displayed wall that disappears without enough opposite aggressive trading to explain the lost depth leaves a tradable same-side price effect.

## Frozen source and proxy

- immutable artifact `8626087323`;
- 2022-07-01 distribution fit only;
- 2023-07-01 untouched fatal screen;
- completed 100ms states;
- side depth divided by prior-only 30-second median;
- fit-day q99 boundaries: bid `6.144210x`, ask `5.962833x`;
- at least 75% of excess depth disappears inside one second;
- opposite aggressive amount explains less than 25% of disappeared displayed quantity;
- bid-wall disappearance -> long; ask-wall disappearance -> short;
- primary diagnostic: executable 15-second return, then 12/18/24bp costs.

## Untouched 2023 result

The proxy produced 64 non-overlapping events across 17 UTC hours:

- bid wall: 38;
- ask wall: 26.

At the fixed 15-second direction:

| Measure | Result |
|---|---:|
| Directional midpoint mean | -0.4338 bp |
| Directional midpoint median | 0.0000 bp |
| Executable gross mean | -0.4664 bp |
| Executable gross median | -0.0329 bp |
| Gross positive fraction | 29.69% |
| Gross positive UTC hours | 6 / 17 |
| Top-10%-positive-event-deleted gross mean | -0.7646 bp |
| 12bp net mean / median | -12.4664 / -12.0329 bp |
| 18bp net mean / median | -18.4664 / -18.0329 bp |
| 24bp net mean / median | -24.4664 / -24.0329 bp |

The 5-second and 30-second executable gross means were also negative (`-0.2734 bp` and `-0.4998 bp`). The prescribed sign therefore failed before realistic fees and slippage. This is not a case where a statistically useful markout was merely too small to trade.

## Decision

Retire this exact top-five ephemeral-wall proxy. Do not reverse the signal, lower the q99 boundary, change the 75%/25% cancellation test, alter the one-second window, choose another horizon, add ML, or combine it with an SMC gate after observing the result.

The negative result does not dispute Level-3 spoofing research. It shows that this public top-five snapshot proxy neither identifies the same latent order behavior nor creates cost-net Bybit Core alpha on the untouched day. A genuine successor would require immutable Level-3 order identities and placement distance, not another threshold on these top-five states.
