# Protected-trendline fakeout first-5m reclaim clock — final report

## Decision

`RES-20260730-PROTECTED-TRENDLINE-FAKEOUT-5M-CLOCK-001` is **`RETIRED_2022_FATAL_GATE_FAILURE`**.

The parent 15m-reclaim route had a broad gross-positive 2022 relation but was sub-cost, while a later projected-line limit introduced missed-fill/adverse-selection. This audit changed only the decision clock: after the same causal 15m protected-line break, the first completed 5m close that reclaimed the old side before break-direction external-liquidity consumption authorized the same opposite action.

No line geometry, break threshold, direction, stop, target, risk, leverage, symbol side, session or ML rule was selected from the parent outcome.

## Programization audit

The final evaluator preserves:

- the parent causal three-pivot 15m line and break tape;
- nearest still-unconsumed prior-day/prior-week/confirmed-4h break-side draw race;
- chronological first completed 5m reclaim;
- fixed 500ms latency represented by the first strictly later complete one-minute open;
- pre-entry stop/target cancellation;
- full break-to-reclaim excursion stop and reversal-side external target;
- first completed 5m reacceptance in the original break direction as state loss;
- adverse same-minute ordering, actual funding, fixed 0.5% current-NAV planned loss, 3x cap and one global slot;
- exact top-five positive-event deletion before complete rerouting.

Two independent complete processes produced byte-identical result, summary, candidate, outcome and trade files.

## Event breadth

- 2022–2023 candidates: **1,195**
- 2022 candidates: BTC **277**, ETH **302**
- 2022 completed one-slot trades: **540**
- Median decision-to-entry delay: **1 minute**
- Median holding time: **15 minutes**
- Mean holding time: **41.86 minutes**
- Exit reasons in 2022: `STATE_REACCEPT` **473**, `TARGET` **45**, `STOP` **22**

The result is not sparse.

## 2022 account result

| Added round-trip cost | Trades | NAV multiple | PF | Median trade | H1 | H2 | MDD |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 bp | 540 | 1.041783x | 1.0723 | -6.91 bp | +0.71% | +3.44% | 6.06% |
| 12 bp | 540 | 0.606442x | 0.4423 | -14.68 bp | -18.37% | -25.71% | 39.36% |
| 18 bp | 540 | 0.511020x | 0.3348 | -17.46 bp | -23.95% | -32.81% | 48.90% |
| 24 bp | 540 | **0.444520x** | **0.2654** | **-19.87 bp** | **-28.27%** | **-38.03%** | **55.55%** |
| 24 bp, top-five winners deleted and slot rerouted | 536 | **0.406882x** | **0.1702** | -20.05 bp | -33.28% | -39.02% | 59.31% |

The zero-added-cost gross mean was only about **+1.31 bp** per trade and the gross median was about **-7.22 bp**. Moving the causal confirmation from the parent 15m close to the first completed 5m reclaim recovered only a small gross tendency while increasing short-duration turnover. Realistic cost overwhelmed it immediately.

## Logic diagnosis

The parent broad gross relation was not hidden solely by a late 15m clock. Early reclaim identifies frequent, short-lived disappointment, but most actions reverse again within one 15m cycle. The underlying price response is too small relative to executable cost. The projected-line limit and first-5m market entry cover the two source-grounded entry translations; neither creates cost headroom.

Decision: retire the protected-trendline fakeout execution family. Do not rescue it with another lower-timeframe count, line buffer, passive offset, fee assumption, target, stop, session, symbol side, ML, risk or leverage. Calendar 2023 and official 2024–2026 remain sealed. No credentials or orders were used.

## Reproduction hashes

```json
{
  "implementation": "1c5cf08495f0d8768f46886cdb07007959d1a25def259ece99ec076e39831903",
  "result": "339b1e3a7c25b2583cd973265602909ee8d7456ebd8061cda69af6d5def22645",
  "summary": "5bb7fec4553683723543aaf8073c0a1f4d0e02bddef026dbd58b773ca4550ee8",
  "candidates": "f5f04f1bfbf92f8d5351eb3fa619c5ef910ed2215599740c753414af78b1d625",
  "outcomes": "64745eca6c3039d328c493269a0777ac4c14429110b82d530f567c21c4bc8b3e",
  "trades_0bp": "9d8bfb3c678d5cc94897bc425faedcd4c302ad462dde7a9be89a5e6af0858d3f",
  "trades_24bp": "13f8bcaff9a4b3daf81124d4de4105cdc77a496f4d9ad172638abdda36df0ddb",
  "trades_24bp_top5_deleted": "67cfc05fa074cc45abef7c2492c4e2dea5c8d28e3375df301863e771313d8c78"
}
```
