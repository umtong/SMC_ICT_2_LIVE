# Current state

- revision: 13
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260726-DONCHIAN-ALLBREAKOUT-A70626D9`
- first-place stage: `PRELIMINARY_CAUSAL_PROXY`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`
- Drive root: resolved privately through `config/project.local.toml` or `00_PROJECT_BINDING`

## Current first place

The provisional first place is the matched all-breakout comparator for specification `a70626d9e484285f2cb4` inside `RES-20260726-DONCHIAN-DEPENDENCE-001` / PR #61.

- 12 bps geometric daily growth: `0.0900854%`
- 1% target gap: `0.9099146 percentage points per calendar day`
- target fraction: `9.00854%`
- 24 bps geometric daily growth: `0.0700189%`
- former first-place growth: `0.0573077%` at 12 bps plus actual funding
- qualification: provisional only; target and economic gate not met

It is first because the cumulative ranking must compare project-level hard-valid or preliminary-causal strategy candidates even when a result-local fatal-screen record labels itself `NONE` or `non-rank-eligible`. The 24-bps comparator growth still exceeds the former first place's 12-bps growth, so disclosing weak comparison confidence is the correct treatment; omitting the candidate is not.

The rank has very low confidence. The result uses Binance USD-M completed bars rather than exact Bybit execution, omits historical funding, approximates the original stop trigger with completed 60-minute bars, opened only 2023, and persisted only comparator growth rather than its complete trade ledger. The related after-loser path has a `-50 bp` median trade and changes to `-26.31%` after removal of the largest positive 10% of trades; all 56 concentration-mitigation variants failed.

## Cumulative strategy ranking

1. `RES-20260726-DONCHIAN-DEPENDENCE-001` — matched all-breakout comparator `a70626d9e484285f2cb4`: `0.0900854%`/day at 12 bps, `0.0700189%`/day at 24 bps; very-low-confidence proxy.
2. `RES-20260725-DYNAMIC-FACTOR-001` — dynamic state-exit `021fbab613517a31ad98`: `0.0573077%`/day at 12 bps plus actual funding.
3. `RES-20260726-CME-GAP-ML-FATAL-001` — CME gap competing-risk ML `da1b9e2861d6b396b81e`: `0.0459425%`/day at 12 bps; Yahoo-CME/Binance proxy and concentrated.
4. `RES-20260725-ABS-FLOW-001` — aligned continuation `33034b092ffd271a`: `0.0227977%`/day at approximately 15 bps.
5. `RES-20260726-SPOT-PERP-LEADERSHIP-001` — perpetual overshoot reversal: `0.0118976%`/day at 12 bps.
6. `RES-20260726-LIQUIDITY-MASS-001` — liquidity-mass rejection `142f8501fcc7874fd6d2`: `0.0118550%`/day at 12 bps.
7. `RES-20260726-EXPIRY-SMT-FATAL-001` — option-settlement SMT proxy: `0.0099556%`/day at 18 bps.
8. `RES-20260726-MMXM-LIFECYCLE-001` — MMXM lifecycle: `0.00575058%`/day at 12 bps.
9. `RES-20260726-KRW-RELATIVE-FATAL-001` — KRW-relative reversal: `0.00487483%`/day at 12 bps, two trades only.
10. `RES-20260726-LIQUIDATION-REFILL-001` — liquidation exhaustion reversal: `0.00358316%`/day at 18 bps.
11. `RES-20260726-DVOL-XSEC-001` — low-VRP residual continuation: `0.0034002%`/day.
12. `RES-20260725-ALPHA-HYP-001` — high-resistance sweep: `0.0024555%`/day.
13. `RES-20260726-FLOW-IMPACT-EFFICIENCY-001` — fragmented-flow reversal: `0.0020533%`/day.
14. `RES-20260725-CAUSAL-ALPHA-WAVE1-001` — balance-to-imbalance best nonzero: approximately `-0.0719%`/day.
15. `RES-20260725-CROSS-ASSET-LEADLAG-001` — leader-shock underreaction best recorded: approximately `-1.483%`/day.

The 10-symbol cross-sectional funding account remains outside ranking because it violates the fixed four-symbol traded universe and no normalized BTC/ETH/SOL/XRP-only account path exists. Non-tradable oracles, hard-invalid outputs and source-only probes remain outside ranking.

## Ranking policy

- Project-level ranking authority overrides result-local convenience labels such as `NONE`, `fatal screen` or `non-rank-eligible`.
- Any hard-valid or preliminary-causal strategy candidate with a usable account growth metric is inserted provisionally when comparison conditions are incomplete.
- Below 1%, higher sustainable after-cost growth and smaller target gap rank ahead; the ranking does not minimize absolute distance to 1%.
- Forced liquidation or irrecoverable account damage cannot outrank a survival-qualified candidate solely through raw return.
- Drawdown/recovery, tail loss, concentration, independent trade count, execution robustness, capital efficiency and comparison confidence resolve similar or uncertain growth.
- Economic-gate failure, validation stage, deployment status and research priority remain separate from rank.
- Results are recorded once; a rank change does not trigger repeated backup or validation.

## Active work

The external U.S.-equity intermarket SMT ML path is complete and negative: model AUC `0.688665` was below the distance baseline `0.720901`, the 18-bps account lost `6.247588%`, and 2023 plus official 2024-2026 remained unopened. It is retired without model, threshold, risk or leverage rescue.

High-information active paths are:

- event-time Bybit mark/index fair-value raid routing in PR #156;
- Aave on-chain liquidation forced flow in PR #161;
- fixed 2024 one-slot portfolio reconstruction for the formerly ranked dynamic and aligned-continuation components in PR #162;
- ML path-continuity routing in PR #170.

Coinbase spot-flow PR #155 has not produced a scientific outcome; its last observed failure was source compilation before market rows. It may be repaired only mechanically under its frozen contract.

## Current blockers

Every positive ranked path remains far below 1% and fails at least one major repeatability condition. The new first place is dominated by wide-channel trend winners; CME gap is Q4- and winner-concentrated; the former first place fails winner removal and every frozen 2024 portfolio. No candidate has robust sequential 2024-2026 Bybit execution evidence.

## Current objective

Prioritize information units and payoffs capable of multiplying cost-surviving edge, not minor threshold repair. Finish the active fair-value, Aave, path-continuity and fixed-portfolio experiments to decision-ready outcomes. Insert every positive result immediately; retire every negative result immediately. Do not spend research budget polishing the newly ranked Donchian comparator merely because it is first.

## Next exact action

Complete the frozen 2024 dynamic-plus-aligned-continuation one-slot portfolio in PR #162 from its verified source artifact, while consuming PR #156, PR #161 and PR #170 as soon as their immutable results exist. The portfolio result must use raw eligible signals, actual funding, 18/24/30-bps paths and unchanged component exits; it either produces a new ranked portfolio or closes the combination without tuning.

Updated: 2026-07-26 20:28 KST
