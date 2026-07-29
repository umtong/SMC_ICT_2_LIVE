# Current state

- revision: 23
- phase: ACTIVE_RESEARCH
- current first place: `FIRST-20260730-BYBIT-DONCHIAN-ML-FULLPATH-13BPS-PROVISIONAL`
- first-place stage: `FULL_2024_2026_CAUSAL_EXACT_BYBIT_PROVISIONAL_EXPANSION_ARTIFACT_GAP`
- target_status: `NOT_MET`
- live_order_permission: none
- repository: `umtong/SMC_ICT_2_LIVE`

## Current first place

The current first place is the exact-Bybit 96-hour breakout / 48-hour opposite-channel HGBT action-value path from `RES-20260730-BYBIT-DONCHIAN-ML-FULLPATH-001`, supported by `RES-20260730-BYBIT-CHANNEL-FULLPATH-AUDIT-001`.

- information cutoff before official opening: `2023-12-31 23:59:59 UTC`
- evaluated path: `2024-01-01` through `2026-06-30`, one continuous NAV
- symbols: `BTCUSDT`, `ETHUSDT`
- one global pending/open slot
- exact Bybit one-minute execution after fixed 500 ms activation
- actual signed Bybit funding
- no elapsed-time or scheduled liquidation
- 13-bps geometric daily growth: `0.108091%`
- 18-bps geometric daily growth: `0.091876%`
- 24-bps geometric daily growth: `0.073834%`
- 13-bps final NAV: `26,784.95 USDT`
- completed trades: `80`
- PF: `1.2138`
- daily liquidation-value MDD: `57.59%`
- median completed account return: `-5.00%`
- top-five positive-PnL share: `68.98%`
- exact 13-bps top-10%-winner-deletion and slot reroute: `13,270.82 USDT`, `0.031034%/day`
- 2026H1 return: `-28.76%`
- maximum used leverage: `7.41x`
- forced liquidation: none
- target fraction at 13bp: `10.81%`
- remaining growth multiple: approximately `9.25x`

It is first because it is the strongest recorded complete account path under exact Bybit data, actual funding, fixed latency and a continuous 912-day evaluation. It is **provisional**, not deployable. The exact fitted model, scored candidate tape, trade ledgers, daily NAV and replay source are retained only as hashes and are not retrievable from the branch or workflow artifacts.

## Independent risk and reproducibility audit

The audit reproduced the exact 2,855 candidate events, annual event counts, annual resolved-label counts and final label-availability timestamps. This makes a broad signal-generation or annual-boundary bug unlikely.

The published 5% planned-loss path used at most 7.4074x leverage, below its 12x cap. Under the unchanged selected event tape and continuous sizing, reducing risk to 0.5% gives rigorous bounds:

- ordinary path: `1.103543x` to `1.228386x`, or `0.010804%` to `0.022557%/day`
- exact winner-deleted path: `1.028702x` to `1.122095x`, or `0.003103%` to `0.012632%/day`

The candidate therefore contains positive small-risk value but is an **Expansion component**, not a sufficient Core engine. The 0.108091%/day headline materially includes risk amplification.

A nearby reproducible HGBT remained positive at 0.5% risk but failed exact winner deletion at 5% risk. A bootstrap lower-confidence-bound action-value screen produced no meaningful-breadth, winner-resistant pre-2024 survivor. Exact model specification is economically decisive.

Rank does not determine research priority.

## Active causal strategy ranking

1. Exact Bybit 96/48 channel HGBT full path — `0.108091%/day` at 13bp and `0.073834%/day` at 24bp; provisional Expansion, artifact gap.
2. Official 2024H1 frozen HGBT Donchian — `0.0387317%/day` at 24bp; retired and winner-dependent.
3. CME gap competing-risk ML — `0.0334850%/day` at 24bp; pre-2024 proxy, negative median and concentrated.
4. Bybit liquidity-mass rejection — `0.0118550%/day` at 12bp; 23 trades and complete top-five concentration.
5. Official 2024H1 unfiltered Donchian — `0.0100516%/day` at 24bp.
6. 08:00 option-settlement SMT — `0.0099556%/day` at 18bp; 12 trades.
7. Bybit MMXM lifecycle — `0.00575058%/day` at 12bp.
8. KRW-relative regional SMT reversal — `0.00487483%/day` at 12bp; two trades.
9. Liquidation exhaustion reversal — `0.00358316%/day` at 18bp.

All remain structurally below 1%. None has deployment authority or incumbency protection.

## What the new first place does and does not establish

It establishes:

- a positive complete 2024-2026 exact-Bybit Expansion path exists;
- the path remains bounded positive at fixed small risk, including after exact winner deletion;
- removing invalid elapsed-time exits and using structural lifecycle rules can preserve some trend payoff;
- risk amplification explains much of the headline return and drawdown.

It does not establish:

- a frequent Core engine;
- robustness to the 2026 regime;
- exact independent reproducibility of the fitted model and selected tape;
- live readiness;
- a path close enough to reach the 1% daily objective through leverage alone.

## Current objective and next exact action

Do not retune channel lookbacks, model thresholds, 2026 regimes, risk or leverage.

1. Preserve the channel path as provisional Expansion only.
2. Require retrievable exact model, scored candidates, trades, daily NAV and replay source before stronger rank confidence or deployment consideration.
3. Direct new alpha work toward one independent, frequent Core information source.
4. Evaluate any Core candidate at fixed 0.5% risk and one global slot before combination.
5. Combine Core and Expansion only by direct incremental log-NAV value and actual slot opportunity cost.
6. Keep the 1% daily reference as the final continuous-path objective, never as a ceiling or a reason to reduce stronger sustainable performance.

Updated: 2026-07-30 ranking reconciliation
