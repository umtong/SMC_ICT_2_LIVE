# Hourly ICT macro-time matched-control screen

Decision: **RETIRED_STAGE1_NON_INCREMENTAL_OR_SUBCOST**.

The transcript-defined `50–10` interval was treated only as context. The exact same causal pre-40m one-sided raid/reclaim reversal action was measured in `10–30`, `30–50` and `50–10` phases before any FVG/BPR or ML extension.

## Failure lesson applied

Earlier studies repeatedly built complete SMC/ICT checklists, models and account engines before establishing that the underlying context had incremental value. This study reversed the order: first compare the same event and action against matched clock controls; open FVG/BPR first-rebalance or ML only after a material, broad, cost-relevant increment.

## Overall phase economics

| phase | events | target rate | gross mean | gross median | 12bp mean | 18bp mean | 24bp mean | 24bp PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL_10_30 | 20,031 | 28.36% | +2.498bp | -8.323bp | -9.502bp | -15.502bp | -21.502bp | 0.321 |
| CONTROL_30_50 | 20,424 | 27.89% | +1.608bp | -8.604bp | -10.392bp | -16.392bp | -22.392bp | 0.307 |
| MACRO_50_10 | 20,103 | 26.06% | -0.488bp | -9.004bp | -12.488bp | -18.488bp | -24.488bp | 0.257 |

The macro phase was not merely sub-cost. It was worse than both controls.

## Matched-control 24bp comparison

- versus `10–30`: macro minus control `-2.871bp`; bootstrap 95% CI `[-3.742, -1.991]`; 20,103 matched pairs;
- versus `30–50`: macro minus control `-2.155bp`; bootstrap 95% CI `[-3.007, -1.288]`; 20,103 matched pairs;
- clustered regression controlling symbol, year, side, anchor hour and causal range/volatility geometry: macro coefficient `-2.838bp`, SE `0.590bp`, p-value `1.51e-6`.

## Programization audit

Five focused tests passed:

1. minute-50 windows map to the next anchor hour;
2. a completed reclaim decision cannot fill at the already-started next minute; the first observable 1m entry is decision plus two bars under fixed 500ms latency;
3. both-side boundary consumption before a reclaim invalidates the event;
4. same-minute stop/target ambiguity is stop-first;
5. gap-through stops execute at the adverse observed open.

The run produced 157,674 windows, 152,418 complete windows and 60,558 resolved events. Only eight events were unresolved or interrupted by source gaps. BTC and ETH invalid-geometry counts were recorded rather than silently coerced.

## Year and hour diagnostics

The macro phase remained negative at 24bp in 2021, 2022 and 2023. No UTC anchor hour produced positive macro net economics in every pre-2024 year. One hour showed a positive relative increment in all years, but its absolute 24bp result remained approximately `-21bp`, so no session subset was eligible for rescue.

## Decision

Stage 2 was not authorized. No BPR/FVG filter, passive first-rebalance action, ML model, risk/leverage search or official 2024–2026 evaluation was opened.

The transcript statement may still be useful as a discretionary observation schedule, but under this causal implementation it is not a standalone positive context for the same raid/reclaim action. The exact hourly macro-time family is retired without window, range, raid, target, session, cost, risk, leverage or ML rescue.

No credentials, paper orders or live orders were used.
