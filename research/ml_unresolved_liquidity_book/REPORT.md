# Dynamic unresolved-liquidity book pressure

**Claim:** `CLM-20260730-ML-UNRESOLVED-LIQUIDITY-BOOK-001`  
**Result:** `RES-20260730-ML-UNRESOLVED-LIQUIDITY-BOOK-001`  
**Decision:** **economic failure before 2023 confirmation and official 2024–2026 evaluation**.

## Why this was tested

A static liquidity level does not describe the market after that level is consumed. The route therefore maintains a causal live book of confirmed 15-minute, one-hour and four-hour swing highs and lows. A level enters only after full right-side confirmation and is removed at its first later consumption. Timeframe weight, prior-ATR distance and age decay define unresolved-liquidity mass above and below price.

The hypothesis was that a new large mass imbalance identifies the direction of current price delivery. It was deliberately separated from static prior-day/IPDA levels, individual level-survival prediction, post-touch acceptance/rejection, FVG/OB lifecycle and farther-target low-resistance continuation.

## Fixed causal and account contract

- Verified canonical Bybit BTCUSDT and ETHUSDT 2021–2023 shards only.
- Completed 15-minute state and decisions.
- Fixed 500 ms activation; because the data are one-minute, entry is the first later observed minute open.
- Nearest still-unconsumed dominant-side level is the frozen target.
- Nearest still-unconsumed opposite-side level is the frozen structural stop.
- Stop-first same-minute ambiguity and adverse gap execution.
- Exact signed funding and 12/18/24 bp round-trip stress.
- Fixed 0.5% NAV planned loss and 3x notional cap.
- One global BTC/ETH slot.
- No elapsed-time liquidation or scheduled close.

## Causality correction

The exploratory global router initially allowed a new entry at the open of the same one-minute bucket in which the previous position later hit its stop or target. That ordering is unknowable and can be overlapping. The final router treats the entire observed exit minute as occupied and requires a strictly later entry minute. Twenty-nine selected successions at the strongest threshold were affected. The correction changed results only slightly and did not change the decision.

## Deterministic economics

At the strongest fixed imbalance threshold, 5,174 candidate outcomes resolved and 77.29% reached the nearest dominant-side pool before the opposite structural level. This apparent directional skill was not economic skill: mean gross unit return was only **1.4119 bp**.

The strict continuous 2021–2023 one-slot path selected 2,066 trades:

| cost | NAV multiple | total return | geometric daily growth | PF | MDD | median trade |
|---|---:|---:|---:|---:|---:|---:|
| 12 bp | 0.5093x | -49.07% | -0.06159% | 0.737 | -52.12% | +3.36 bp |
| 18 bp | 0.3739x | -62.61% | -0.08980% | 0.625 | -63.89% | +1.87 bp |
| 24 bp | 0.2824x | -71.76% | -0.11540% | 0.532 | -72.14% | +0.73 bp |

The strategy was not failing because of one or five anomalous winners; the top-five positive-PnL share was only 5.87% at 18 bp. It failed broadly because frequent nearby targets generated small gains while less frequent opposite-level stops generated much larger losses.

## Programization audit of exits

A second replay kept the exact same strict selected entry tape but replaced an earlier target/stop only when aggregate book dominance crossed to the opposite state. It did not reuse freed slots, so the result isolated exit management rather than adding more entries.

At 18 bp the altered annual returns were -13.90% in 2021, -25.97% in 2022 and -41.35% in 2023. The 2022 path improved by about 2.07 percentage points, but 2021 and 2023 worsened. Therefore an obvious state-loss exit did not repair the entry economics.

## ML action value

A pooled causal action-value model used 56 completed features from the live liquidity book, price path, volatility, OI, account crowding, premium, mark/index fair value and synchronized BTC/ETH state. It predicted target-first probability, which was converted into deterministic cost-after account value from each candidate's frozen target, stop and position size.

- Best 2021 expanding sequential OOF AUC: **0.6793**; the OOF account gate remained negative.
- Best 2022 fixed policy AUC: **0.7079**.
- Best 2022 route: 166 trades, +1.27% at 12 bp, **-0.45% at 18 bp**, **-2.05% at 24 bp**, PF 0.989 at 18 bp.

No model/action-value route was positive at 18 bp and nonnegative at 24 bp. Frozen 2023 confirmation and official 2024–2026 were therefore not opened.

## Interpretation

The live unresolved-liquidity book contains information about **which nearby pool is likely to print first**, but not enough information about a tradeable path from the current executable price. Directional hit rate hid three economic defects:

1. the nearest dominant pool was usually too close after costs;
2. the opposite structural level was often much farther away;
3. freeing the slot sooner increased exposure to more sub-cost opportunities rather than improving account growth.

This distinction is central: predicting the next liquidity print is not equivalent to choosing a positive-value account action.

## Decision

Retire the exact standalone aggregate-book entry family. Keep its causal level lifecycle, consumption retirement, mass imbalance and target-state features available as a component for materially different strategies. Do not rescue it by extending to farther targets, inserting passive entries, assuming lower costs, increasing risk/leverage, or duplicating the active low-resistance-liquidity continuation claim.
