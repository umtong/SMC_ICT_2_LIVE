# Failed-channel missed-fourth-point control-transfer Core — final report

## Decision

`RES-20260730-FAILED-CHANNEL-CONTROL-CORE-001` is **`RETIRED_2022_FATAL_GATE_FAILURE`**.

The tested logic was source-grounded rather than a channel-parameter tournament: a causal three-point channel created an expected fourth boundary; the first causally confirmed opposite pivot had to miss that boundary; a nontrivial completed close then had to break the trend-side boundary; the position targeted the nearest still-unconsumed pre-known external liquidity and exited early only on reacceptance into the old channel.

BTCUSDT and ETHUSDT were test markets for the same rule. No symbol-side rule, session, FVG/OB gate, ML, risk/leverage search or official-period adaptation was used.

## Programization audit

Before interpreting economics, the implementation fixed and tested:

- width-two pivot availability only after two completed right-side bars;
- consecutive alternating three-pivot channel construction;
- seven-calendar-day channel authority;
- the first confirmed opposite pivot as the only prospective fourth point;
- retirement after expected-boundary touch or a weak trend-boundary cross;
- replacement only by a newer same-direction qualifying channel;
- target availability and one-use consumption before entry;
- fixed 500ms latency represented by the first strictly later complete minute;
- cancellation when the structural stop was touched between the decision and executable entry;
- adverse same-minute stop/target ordering, actual funding and one global slot;
- exact top-five positive-event deletion before complete slot rerouting.

Three BTC candidates were removed because their hard stop was already touched during the decision-to-entry interval. After the correction, two independent full executions produced byte-identical result, summary, candidate and outcome files.

## Event breadth

- Causal candidates, 2022–2023: **1,002**
- 2022 raw candidates: **537**
- 2022 one-slot completed trades: **393**
- 2022 BTC candidates: **264**
- 2022 ETH candidates: **273**
- Median holding time: **1.5 hours**
- Mean holding time: **6.01 hours**

The result is therefore not an event-scarcity diagnosis.

## 2022 account result

| Added round-trip cost | Trades | NAV multiple | PF | Median trade | H1 | H2 | MDD |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 bp | 393 | 0.804590x | 0.8220 | -0.4800% | -26.60% | +9.62% | 28.74% |
| 12 bp | 393 | 0.594149x | 0.6025 | -0.4888% | -34.67% | -9.06% | 40.59% |
| 18 bp | 393 | 0.536362x | 0.5322 | -0.4899% | -37.36% | -14.38% | 46.36% |
| 24 bp | 393 | **0.492092x** | **0.4747** | **-0.4910%** | **-39.54%** | **-18.60%** | **50.79%** |
| 24 bp, top-five winners deleted and slot rerouted | 390 | **0.426064x** | **0.3770** | -0.4917% | -42.22% | -26.26% | 57.39% |

The top five winners supplied only 19.11% of positive PnL at 24bp. The family failed broadly, including before added transaction cost; it was not a few-jackpot path whose tail was accidentally removed.

## Logic diagnosis

A missed projected fourth point and trend-side channel break are recognizable structure, but this geometry does not prove that meaningful defended inventory remains at the old channel or that the next external-liquidity path has low resistance. Most trades stopped or were structurally reaccepted before their external draw.

The failure is not repaired by changing channel age, pivot radius, fourth-point distance, body threshold, stop, target, session, symbol side, cost, ML, risk or leverage. Those would be adjacent optimization of a broad negative information unit.

Calendar 2023 and official 2024–2026 remained sealed. No credentials, paper orders, testnet orders or live orders were used.

## Reproduction hashes

```json
{
  "implementation": "4eb550ad6c140bb43a4225534a154a199f0a823a97f4ea364ab87a6b369e8cd0",
  "result": "96f7130600ae41d883c401d22ad5dd192ab08ca6b8020bad997d3c3745b05564",
  "summary": "344b0547ca8a9121b13cb19915d1edbe1720dd9ac29779888cf38b389623666f",
  "candidates": "162863007a29e2bce06cb522a77350994d23db7f97426e1d788a421fd08d2b26",
  "outcomes": "442050e2c06f0b1986230851ce886c7bc944996a52d85f95df965dd90923844f",
  "trades_0bp": "ec7b996637edbe941f0faa2a54c5febc8249eeb55d38263a7b0eabb9747a5971",
  "trades_24bp": "010561b5ee413506ba1fed3a03cd069ff1a1d399c4c84b717f06461a538df9f1",
  "trades_24bp_top5_deleted": "a35ed93081e50b8c78f1079070b53675d11aaf5dee8a1cce1f20404df6345fb1"
}
```
