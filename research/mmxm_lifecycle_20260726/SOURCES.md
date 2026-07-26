# Hypothesis sources and translation

The sources below define vocabulary only. They are not evidence that the strategy is profitable.

- **The Inner Circle Trader — Trading Plan Development 6** (`s9bg8JF7rm8`, 2017-12-24): short-term trading-plan context and the Market Maker Buy/Sell Model framework.
- **The Inner Circle Trader — Market Maker Series Vol. 3 of 5** (`i8xt0EQDjNY`, 2021-07-30): market structure, key levels and the delivery path around institutional reference points.
- **ICT Codex — Model 6 / Universal Buyside**: the four-stage lifecycle—Original Consolidation, engineering liquidity, Smart Money Reversal and liquidity hunt—was used to define the state machine.

## Frozen quantitative translation

| SMC/ICT term | Causal observable |
|---|---|
| Original Consolidation | four/eight completed 60-minute bars with bounded ATR-normalized range and low path efficiency |
| engineered liquidity curve | at least two/three confirmed, directionally ordered 5-minute pivot shelves after leaving the origin |
| terminal liquidity raid | trade beyond the last confirmed external pivot followed by a completed reclaim |
| premium/discount depth | excursion from the origin boundary measured in frozen Original-Consolidation range units |
| Smart Money Reversal | completed displacement through the final shelf, with ATR body and close-location requirements |
| first hold | first pullback that rejects the broken shelf or displacement-body midpoint |
| liquidity hunt / completion | structural target at the far boundary of the frozen Original Consolidation |

No claim about hidden dealer intent is used by the code. Only completed prices, confirmed pivots and frozen ranges are observed.
