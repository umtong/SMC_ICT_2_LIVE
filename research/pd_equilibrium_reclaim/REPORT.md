# Previous-day equilibrium-reclaim matched-action screen

Decision: **RETIRED_STAGE1_EQUILIBRIUM_RECLAIM_NEGATIVE_AND_NON_INCREMENTAL**.

## Question

After the current UTC day consumes exactly one side of the prior completed UTC-day range, does waiting for a later completed close through the frozen prior-day midpoint improve delivery to the still-unconsumed opposite boundary versus entering at the first boundary reclaim?

The direct and equilibrium actions use the same event origin, reversal direction and opposing prior-day target. Both use fixed 500 ms activation, the first strictly later observable one-minute open, a structural stop beyond the raid extreme known at the decision, exact signed funding, adverse gap stops and stop-first same-minute ordering. There is no elapsed-time or scheduled close.

## Inventory

- UTC days considered across BTCUSDT and ETHUSDT: 2,188
- first one-sided 1 bp prior-day boundary raids: 1,695
- direct boundary-reclaim decisions: 1,530
- equilibrium-reclaim decisions: 574
- resolved direct events: 1,496
- resolved equilibrium events: 570
- unresolved/source-gap events: 5 direct / 2 equilibrium

## Overall event economics

| action | events | target rate | gross mean | gross median | 12 bp mean | 18 bp mean | 24 bp mean | 24 bp PF | median stop | median target | median RR | median raid-to-decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Direct boundary reclaim | 1,496 | 20.52% | +10.235 bp | -45.907 bp | -1.628 bp | -7.628 bp | -13.628 bp | 0.847 | 64.96 bp | 422.82 bp | 6.48 | 6 min |
| Prior-day equilibrium reclaim | 570 | 65.09% | -11.993 bp | +95.016 bp | -23.957 bp | -29.957 bp | -35.957 bp | 0.735 | 299.62 bp | 168.35 bp | 0.59 | 478 min |

The midpoint state increased target frequency but destroyed payoff geometry. By the time midpoint was recovered, the observed raid extreme was usually much farther away while little distance remained to the opposite prior-day boundary. High win rate and positive median therefore coexisted with negative mean and PF below one.

## Same-event incremental comparison

Among 562 events where both actions resolved, the direct action had 24 bp mean `+71.775 bp`, while the later equilibrium action had `-36.803 bp`. Waiting for midpoint changed the mean by `-108.578 bp`; deterministic bootstrap 95% CI `[-128.658,-87.022]`, paired p `5.85e-23`. Only 0.89% of paired decisions occurred on the same completed bar, and the median additional wait was 405 minutes.

This paired result is diagnostic rather than a direct-time trading policy because membership in the paired set is known only after the later midpoint state occurs. It nevertheless shows that the midpoint transition did not add economic value to the already-defined reversal.

## Forward-year stability

At 24 bp:

| action | 2021 | 2022 | 2023 |
|---|---:|---:|---:|
| Direct boundary reclaim | -16.172 bp | -24.052 bp | +0.558 bp |
| Equilibrium reclaim | -10.497 bp | -72.267 bp | -19.163 bp |

The direct route was near break-even only in 2023 and was negative in 2021–2022. The equilibrium route was negative in all three years.

## Programization audit: continuous accepted reclaim

A rational semantic objection is that the first reclaim should be invalidated if a later completed five-minute close is accepted back outside the swept boundary before midpoint recovery. This was tested without changing range, target, stop, costs or decision threshold.

- direct source events: 1,496
- failed reacceptance before midpoint: 1,154
- strict equilibrium decisions: 235
- resolved strict events: 234
- 24 bp mean: `-34.994 bp`
- 24 bp PF: `0.725`
- 2021: `+22.396 bp`
- 2022: `-70.255 bp`
- 2023: `-40.764 bp`

The semantic repair reduced delay and removed failed reacceptance, but did not restore persistent alpha. On the 234 same events, waiting for the strict midpoint decision worsened 24 bp mean by `-175.817 bp` versus the causal direct reclaim entry.

## Account diagnostic

This cannot rescue negative event economics, but the frozen 0.5% current-NAV / 3x one-global-slot diagnostic confirms the account consequence at 24 bp:

- direct reclaim: 843 trades, `10,000 → 4,018.74 USDT`, geometric daily `-0.083218%`, PF `0.749`, realized-NAV MDD `61.04%`;
- equilibrium reclaim: 346 trades, `10,000 → 8,835.09 USDT`, geometric daily `-0.011310%`, PF `0.798`, MDD `12.50%`.

The equilibrium route lost more slowly only because it traded less and used poor sub-1R geometry; it did not become an edge.

## Validation

Seven focused tests passed over synthetic cases and the full recorded event ledger:

1. completed decision + 500 ms cannot fill at the already-started minute;
2. same-minute stop and target resolves to stop;
3. gap-through stop uses the adverse observed open;
4. every entry is exactly the first later minute and every exit precedes its calendar-year label boundary;
5. equilibrium follows direct reclaim and preserves event direction/target;
6. every target-consumption, midpoint/boundary close and raid-extreme stop is recomputed from canonical bars;
7. every strict event has no completed five-minute close back outside before midpoint recovery.

A second full run produced byte-identical event, summary and result files.

## Decision

Stage 2 was not authorized. No FVG, OB, BPR, OI/account-ratio feature, ML policy, risk/leverage search or official 2024–2026 interval was opened.

This closes the exact information unit:

> one-sided previous-day external-liquidity consumption followed by prior-day equilibrium recovery as a reversal trigger to the opposite previous-day boundary.

The result does not say that range equilibrium has no descriptive value. It establishes that, under this causal daily lifecycle, midpoint recovery is late, payoff-compressing and economically inferior to the already-negative direct reclaim route. No adjacent midpoint, raid, decision, target, stop, cost, risk, leverage or model rescue is justified.

No credentials, paper orders or live orders were used.
