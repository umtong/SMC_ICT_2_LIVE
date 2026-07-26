# ML path-continuity structural first-passage router

Claim: `CLM-20260726-1958-ML-PATH-CONTINUITY-001`  
Branch: `agent/r11-ml-path-continuity-router-001`

## SMC/ICT explanation

The system waits for a completed directional displacement, then evaluates only the **first** completed 50%-79% OTE pullback. Before entry it freezes the nearest still-unreached liquidity pools above and below price from completed 4-hour, prior-day, prior-week and rolling-30-day structure. The trade question is therefore concrete: **which already-known external liquidity pool is reached first?**

The ML layer does not invent a chart pattern. It distinguishes two delivery regimes:

- **continuous delivery** — many small, directionally consistent bars, high path efficiency, low jump concentration and supporting flow; this should favor continuation after the OTE pullback;
- **discrete delivery** — one or two bars explain most of the move, the path is inefficient or overextended, and flow/breadth do not confirm; this should favor reversal through the opposing pool.

One calibrated HGBT estimates the upper-pool-first probability. A single cost-adjusted expected-value rule chooses long, short or flat. Stops and targets are the frozen structural pools. There is no elapsed-time liquidation.

## Historical boundary

The rule is motivated only by pre-2024 continuous-information and cryptocurrency momentum/reversal evidence. The June 2026 crypto path-continuity paper is explicitly excluded from the historical rule definition. Market data from 2024 onward are code-sealed unless every pre-2024 model, cost, sample, median, concentration, period and drawdown gate passes.

## Staging

1. Download official public Bybit linear-perpetual 15-minute market bars, funding history and mark-price bars only through 2023-12-31.
2. Build causal events and frozen first-passage labels.
3. Train one model on 2021H1-2022H1, calibrate on 2022H2, confirm on 2023H1 and replay one global account on 2023H2.
4. Replay identical decisions at 12/18/24bp. Risk/leverage variants remain closed unless the unchanged 2%-risk path passes every base gate.
5. Open sequential 2024-2026H1 only for a full survivor.

No credentials or orders are used.
