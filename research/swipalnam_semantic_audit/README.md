# Swipalnam dual-auction semantic and execution audit

Result ID: `RES-20260729-SWIPALNAM-SEMANTIC-AUDIT-001`  
Claim ID: `CLM-20260729-2125-SWIPALNAM-AUDIT-001`  
Audited system: PR #372, V15/V16 dual-auction liquidity-delivery ML  
Verdict: **both programization failure and economic failure**

## Why this audit exists

The reported pre-2024 account grew from 10,000 to 309,613 USDT, but the same frozen system fell to 17.13 USDT in 2024H1. This audit asks whether the SMC/ICT thesis itself failed or whether the implementation stopped representing the stated thesis.

The independent replica uses the existing canonical BTCUSDT/ETHUSDT Bybit 1m and 15m tables. No market data was reacquired. It reproduces the selected V16 trade IDs exactly and then applies explicit semantic invariants.

## Semantic contract

A trade is strict only when all of the following are true:

1. a genuine three-candle FVG exists; a displacement body is not a substitute;
2. an actual opposite candle is found for the order block;
3. FVG and OB overlap; empty price between disjoint arrays is not an entry zone;
4. the target is causally known opposing liquidity, not a measured-price fallback.

## Principal findings

- All 132 reported selected trade IDs were independently reconstructed.
- Only **4/132 (3.03%)** satisfy the strict semantic contract.
- **112/132 (84.85%)** have no genuine FVG.
- **75/132 (56.82%)** enter through a union zone that contains prices belonging to neither the FVG nor the OB.
- The 2023 raw screen chosen for ML has negative mean net R in every chronological quarter in the original report.
- The original report's stricter genuine-FVG/overlap configuration is also negative in every quarter.
- Independent 24bp replay is negative for original, genuine-FVG, genuine-FVG+OB, strict-overlap and strict-all variants in 2021, 2022 and 2023.
- A deterministic strict-all one-slot account at 0.5% planned risk and 3x notional cap ends below 10,000 USDT in all three years.
- ML ranking degrades from 2023 win AUC 0.6728 to 2024H1 AUC 0.4139. In 2024H1 the highest-score quartile receives 36% planned NAV risk and produces the worst quartile result: mean -0.5461R and -8,175.55 USDT.
- Funding is not replayed from actual events. One snapshot is extrapolated at three payments per day. The signed approximation error is -1,657.39 USDT for the 2023 selected trades and -54.19 USDT for 2024H1 under a rough event replay with partial-size adjustment.

## Economic result at 24bp

| Year | Variant | Filled/resolved | Mean R | Median R | Profit factor |
|---|---:|---:|---:|---:|---:|
| 2021 | Original semantics | 3,387 | -0.5812 | -1.1385 | 0.4209 |
| 2021 | Strict all | 106 | -0.5720 | -1.1821 | 0.4494 |
| 2022 | Original semantics | 3,069 | -0.6634 | -1.1531 | 0.3664 |
| 2022 | Strict all | 93 | -1.1811 | -1.3927 | 0.1780 |
| 2023 | Original semantics | 2,875 | -1.3326 | -1.3529 | 0.1808 |
| 2023 | Strict all | 134 | -1.1121 | -1.5800 | 0.2169 |

The exact numbers are in `RESULT.json` and the two summary CSVs.

## Root-cause verdict

### Programization failure

The reported system does not faithfully represent its own SMC/ICT description. It substitutes candle bodies for missing FVGs, substitutes ordinary prior candles for missing OBs, fills the empty distance between disjoint arrays, and creates synthetic measured targets when no opposing liquidity satisfies the RR threshold. The first-mitigation limit thesis is also converted into a next-minute market-like open fill after touch discovery.

### Economic failure

Fixing those meanings does not recover alpha. Strict candidates are less frequent but still have negative cost-adjusted expectancy across 2021-2023. The correct action is therefore not to tune leverage, risk, RR or ML thresholds. The exact family is retired.

### Risk and selection failure

All 432 structural configurations were allowed to advance despite negative base screens. Structural geometry, ML policy/threshold, and account risk were then selected on the same May-December 2023 path. Confidence scaling converted a 12% base risk into 4.2%-36% planned NAV loss per trade. When the ranking inverted in 2024, the system allocated the most risk to its worst trades.

## Reproduction

The audit does not download data. Point it at an existing canonical export containing `BTCUSDT` and `ETHUSDT` directories with `bars_1m.pkl.gz` and `bars_15m.pkl.gz`.

```bash
python research/swipalnam_semantic_audit/audit.py \
  --root /path/to/canonical_export \
  --start 2023-01-01 \
  --end 2024-07-01 \
  --out candidates.pkl.gz
```

The module exposes `run_simulation(...)` for the fixed-500ms, next-observable-minute execution replay. `test_audit.py` locks the semantic invariants and the three original fallbacks as executable counterexamples.

## Decision

- No ranking change.
- No official corrected 2024-2026 run: the corrected route fails before that gate.
- No leverage or confidence-risk rescue.
- Any later SMC implementation must pass semantic invariant tests and show positive, non-sparse, fixed-small-risk event economics before ML or account sizing is explored.
