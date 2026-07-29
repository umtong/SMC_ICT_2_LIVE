# Perpetual–index non-confirmation liquidity sweep

**Claim:** `CLM-20260730-ML-PERP-INDEX-SWEEP-001`  
**Result:** `RES-20260730-ML-PERP-INDEX-SWEEP-001`  
**Decision:** **economic failure before the ML and official-evaluation gates**.

## Hypothesis

The study asked whether a derivative-specific stop run can be distinguished from genuine fair-value delivery. A previous completed UTC-day perpetual high or low is external liquidity. The current perpetual trade tape consumes it, but the exchange index fails to consume the index level paired with the creation of that derivative extreme. A completed close back inside creates a reversal candidate.

This is not a generic sweep/FVG checklist. The proposed information source is the disagreement between leveraged-contract execution and exchange index fair value at one causally pre-known liquidity pool.

## Material programization correction

The exploratory implementation compared a previous-day perpetual high or low with the previous-day **index extreme**. Those two extremes can form at different times, so they are not a true SMT pair.

The final implementation instead stores the index high or low in the exact completed five-minute bar that created the previous-day perpetual extreme. Current perpetual consumption is compared with that paired index level. All reported figures use the repaired semantics.

## Fixed execution and account contract

- Canonical verified Bybit BTCUSDT and ETHUSDT 2021–2023 shards; all ZIP, manifest, and internal file hashes passed.
- Completed five-minute decisions; fixed 500 ms delay; first observable one-minute open strictly after activation.
- First consumption of each previous-day high/low only.
- Stop beyond the raid extreme by 0.10 prior ATR14.
- Target at the nearest previous-day open, midpoint, or close in the reversal direction.
- Later completed trade-and-index acceptance beyond the paired levels is state loss.
- No elapsed-time liquidation or scheduled close.
- Stop-first same-minute ambiguity, adverse gap execution, exact signed funding.
- 12/18/24 bp round-trip cost diagnostics.
- Fixed 0.5% NAV planned loss and 3x notional cap.
- One global BTC/ETH slot. Earliest executable event wins; exact ties use larger causal structural reward/risk.

## Economic result

At the primary 18 bp cost:

| stage | selected trades | return | daily geometric growth | PF | MDD | median trade |
|---|---:|---:|---:|---:|---:|---:|
| 2021 development | 26 | -5.7451% | -0.01621% | 0.382 | -6.4854% | -0.5000% |
| 2022 forward gate | 20 | -4.5027% | -0.01262% | 0.348 | -5.3214% | -0.5000% |
| 2023 exposed diagnostic | 24 | -6.4660% | -0.01831% | 0.187 | -6.5885% | -0.5000% |

The 2022 result was negative at every cost: -3.9662% at 12 bp, -4.5027% at 18 bp, and -4.9357% at 24 bp. Fourteen of twenty selected trades hit structural stops; only six reached the target. Mean four-hour reversal-direction movement before costs was already -0.4542%, so execution costs were not the root cause.

The 2021–2023 diagnostic continuous path selected 70 trades and fell to 0.8419x NAV at 18 bp, with PF 0.308 and 67.85% of positive PnL supplied by the five largest winners.

## Interpretation

The repair improved semantic correctness but not economics. A perpetual-only excursion beyond the paired fair-value level did not imply rejection. In 2022, price moved farther in the sweep direction on average after the event. A single close back inside was therefore not evidence that vulnerable inventory had finished transferring or that opposing order flow had gained control.

The failure is not solved by fitting a classifier to 20 forward trades. That would turn a negative, sparse information unit into a small-sample selector. The ML gate, risk/leverage search, and official 2024–2026 interval remain closed.

## Decision

Retire this exact previous-day perpetual-versus-paired-index reversal family. A successor must change the economic information source—such as directly observing inventory transfer and post-transfer acceptance—not add FVG/OB/session gates, narrower thresholds, lower assumed costs, or larger risk.
