# ML Sweep–FVG queue-aware maker

Claim: `CLM-20260726-1837-ML-SWEEP-FVG-MAKER-001`

## One model, one route

This study tests one economic change rather than another SMC pattern family:

1. freeze already-confirmed 60-second external liquidity;
2. require a one-sided raid and completed rejection;
3. require a later completed 15-second market-structure break with 5-second displacement and a three-candle FVG;
4. measure one retracement only: 62% of the actual raid-extreme-to-displacement-close leg;
5. after the first touch, wait 200 ms and rest one post-only order at the observed Bybit best bid or ask;
6. allow the order only when one fixed multinomial logistic model estimates positive cost-adjusted expectancy from the structural setup and current queue state.

There is no OTE grid, FVG family grid, model grid, feature selector, score-threshold grid or side-specific policy.

## SMC/ICT explanation

The raid removes external liquidity. The subsequent MSS/displacement says delivery changed. The FVG records the imbalance left by that change. The first 62% mitigation is the only entry geometry. ML does not predict a generic next candle; it decides whether the passive mitigation order is likely to receive a non-toxic fill before price reaches the frozen target or invalidation.

## Queue and fill contract

- Source clock is Tardis `local_timestamp`; compact top-five state decisions are spaced at 100 ms.
- The order is acknowledged 200 ms after the first retracement touch.
- Longs rest at best bid; shorts rest at best ask.
- Queue ahead starts at the full displayed amount at that price.
- Only observed opposite aggressive trades at the order price or through it consume queue.
- Displayed cancellations never reduce queue ahead.
- Any positive partial fill is real exposure. The unfilled remainder is cancelled at the first target, stop or structural invalidation, and the filled quantity exits at delayed observed BBO.
- A trade and barrier with the same local timestamp are resolved against the strategy.
- Source-boundary exposure pays the structural stop.

## Frozen partitions

- `2022-07-01 00:00–12:00 UTC`: model fit.
- `2022-07-01 12:00–24:00 UTC`: untouched fit confirmation.
- `2023-07-01`: opened only if every fit gate passes.
- `2024`–`2026`: rejected by code.

The one-day source is a fatal information screen, not a ranking-eligible project result. A survivor requires a separate multi-date sequential Bybit replay before 2024–2026 can be opened.

## Economic gate

The confirmation half must have at least 100 order decisions and 20 filled positions. The full model must beat a structure-only baseline in multiclass log loss and Brier score. The one-slot account must remain positive at 12 and 18 bp, with positive median trade, PF above one, positive top-10%-winner-removal at 12 bp, at least two positive time blocks and no liquidation.

Failure retires this exact route without adjacent entry, feature, threshold, risk or leverage tuning.
