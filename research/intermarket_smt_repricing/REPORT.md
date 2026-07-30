# Causal intermarket SMT control-transfer first-repricing Core — final report

Result ID: `RES-20260730-INTERMARKET-SMT-REPRICING-001`

Verdict: `RETIRED_PROGRAMIZATION_CORRECTED_SPARSE_AND_BASELINE_INFERIOR`

## Question

Does a same-scale prior-day external-liquidity raid in one correlated perpetual market become materially more informative when the peer is close enough to confirm but refuses to consume its corresponding boundary?

The tested thesis was:

```text
one market consumes prior-day external liquidity
→ peer is near the corresponding pool but does not confirm
→ swept market reclaims and completes causal internal shift
→ first repricing at the swept boundary
→ 50% to equilibrium, 50% to opposite external boundary
```

BTC and ETH were testbeds. The intended mechanism was product-neutral intermarket non-confirmation, not a symbol-specific direction rule.

## Final programization

The final authority used:

- completed prior-day high/low/midpoint known at UTC day open;
- first strict one-minute sweep, with same-minute dual sweeps flat;
- peer distance normalized by its prior-only completed 15-minute ATR20;
- reclaim before peer confirmation;
- a completed five-minute close through the latest causally confirmed opposite five-minute pivot;
- a one-tick-through first-repricing limit at the swept boundary rather than confirmation chasing;
- pending-order one-slot occupation and causal cancellation;
- a full sweep-to-shift hard stop;
- 50% equilibrium realization and a structurally protected runner to the opposite prior-day boundary;
- actual funding, cost-inclusive risk sizing, fixed 500ms activation, adverse ambiguity, and no elapsed-time close.

Two complete fresh executions (`output4` and `output5`) produced all 26 scientific output files byte-identically.

## Programization correction before the verdict

The preliminary replay contaminated the required matched control. Peer same-side confirmation cancelled both SMT and `SINGLE_ASSET_CONTROL` positions. That would make the control partly inherit the information being tested.

The final authority created two separate outcome tapes:

- `CONTROL`: no peer-near admission and no peer-confirmation cancellation;
- `SMT`: peer-near/non-confirmed candidates only, with peer confirmation cancelling pending or open exposure.

Every preliminary control and SMT account result was invalidated before the corrected replay.

## Event funnel

| Item | 2021 | 2022 | Total |
|---|---:|---:|---:|
| Single-market reclaim/shift candidates | 219 | 251 | 470 |
| SMT-eligible candidates | 4 | 7 | 11 |
| SMT fills after one-slot/pending logic | 2 | 5 | 7 |
| Profitable SMT fills, even at zero added cost | 0 | 0 | 0 |

The single-market family was broad. The exact peer-near/non-confirmation state was genuinely sparse.

## Matched single-asset control

### 2021 diagnostic

| Cost | Trades | NAV multiple | PF | Median trade | Positive trades | Top-five positive-PnL share |
|---:|---:|---:|---:|---:|---:|---:|
| 0bp | 134 | 0.84063x | 0.173 | -0.0802% | 18 | 91.04% |
| 12bp | 134 | 0.77006x | 0.0839 | -0.1367% | 8 | 99.39% |
| 18bp | 134 | 0.75294x | 0.0683 | -0.1566% | 4 | 100% |
| 24bp | 134 | 0.73892x | 0.0575 | -0.1785% | 4 | 100% |

The control was negative before cost in 2021.

### Untouched 2022 forward screen

| Cost | Trades | NAV multiple | PF | Median trade | Positive trades | Top-five positive-PnL share |
|---:|---:|---:|---:|---:|---:|---:|
| 0bp | 149 | 1.01665x | 1.062 | -0.0962% | 27 | 72.70% |
| 12bp | 149 | 0.85723x | 0.574 | -0.1802% | 13 | 73.00% |
| 18bp | 149 | 0.81863x | 0.480 | -0.2102% | 11 | 71.92% |
| 24bp | 149 | 0.78958x | 0.413 | -0.2322% | 11 | 70.96% |

At 24bp:

- MDD: 21.59%;
- both realized half-year PnL blocks were negative;
- exact deletion of the five largest positive parent events before complete rerouting produced 145 trades, `0.69409x`, PF `0.1186`;
- the zero-cost path was barely positive and still had a negative median trade.

Thus the broad single-market reclaim/shift/first-repricing family had no realistic cost headroom.

## Intermarket SMT subset

### 2021 diagnostic

Four events passed SMT admission. Only two filled and both lost.

- 0bp: `0.99150x`, PF zero, median `-0.4261%`;
- 24bp: `0.99102x`, PF zero, median `-0.4501%`.

### Untouched 2022 forward screen

Seven events passed SMT admission. Five filled and every one lost.

| Cost | Trades | NAV multiple | PF | Median trade | Positive trades |
|---:|---:|---:|---:|---:|---:|
| 0bp | 5 | 0.98116x | 0 | -0.4732% | 0 |
| 12bp | 5 | 0.97849x | 0 | -0.4867% | 0 |
| 18bp | 5 | 0.97823x | 0 | -0.4885% | 0 |
| 24bp | 5 | 0.97801x | 0 | -0.4899% | 0 |

Winner deletion is unchanged because there were no winners.

## Economic interpretation

The SMT premise failed in both necessary ways:

1. **No incremental evidence:** the matched single-market family was itself broad but cost-negative. SMT did not improve it.
2. **No breadth:** exact peer-near/non-confirmation produced only eleven candidates over two years and all seven filled trades lost even before added cost.

A peer that has not yet swept its own prior-day boundary is not enough to establish that the swept market's move was false. The peer may differ in volatility, beta, inventory, or timing while the broad market is still delivering in the swept direction. Reclaim plus local shift also did not prove that trapped inventory would fund equilibrium rotation.

This is not a hidden ML opportunity. The SMT state is too sparse and its observed forward fills have the wrong sign; the broad parent action is already negative after realistic costs.

## Decision

Retire the exact prior-day sweep → peer-near non-confirmation → reclaim/shift → first-repricing → midpoint/runner family.

Do not rescue it with:

- another peer-distance threshold;
- other correlated pairs or symbol/side exceptions;
- alternate reclaim or shift clocks;
- FVG, OB, OTE, session, or premium/discount gates;
- target, partial, runner, stop, entry offset, or TTL changes;
- lower costs, ML selection, risk, or leverage.

Calendar 2023, ML, risk/leverage work, and official 2024–2026 remained sealed. No credentials or orders were used.

## Reproducibility

- Implementation SHA-256: `386780ed587bfa9ffe2fd8b8b413ad7a71df10687662ac6ef078174ebf6fc388`
- Result SHA-256: `21ddc2389e2effe70d90e5c7757301647cb93bcfbb176e7b3c2738e72328a082`
- Determinism manifest: `DETERMINISM_SHA256.json`
- Fresh runs: `output4` and `output5`, all 26 common files byte-identical.
