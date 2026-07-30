# True-balance manipulation to opposite-edge distribution — decision report

**Result:** `RES-20260730-TRUE-BALANCE-OPPOSITE-DISTRIBUTION-001`  
**Claim:** `CLM-20260730-TRUE-BALANCE-OPPOSITE-DISTRIBUTION-001` / issue #654  
**Decision:** `RETIRED_PRE2024_COMPLETE_AMD_PO3_TOO_SPARSE_WINNER_DEPENDENT`; no ranking or live-permission change.

## Logic tested

The symbols were only testbeds for a complete SMC/ICT auction path:

1. a genuinely two-sided completed UTC-day balance accumulates liquidity at both edges;
2. the immediately following trade day first raids one edge and later completes a five-minute close back inside;
3. the reclaim alone is not traded;
4. control transfer is confirmed only when a later completed five-minute close reaches beyond the opposite edge before the frozen raid extreme is invalidated;
5. entry follows after the fixed latency toward the nearest still-unconsumed, pre-known daily or confirmed-four-hour external pool;
6. stop, target and close-back-inside state loss all express the same premise. No elapsed-time or scheduled close exists.

This differs from the retired active-candle PO3 route and from one-packet balance acceptance/rejection. It tests the full path `completed true balance -> manipulation/reclaim -> opposite-edge distribution`.

## Programization audit

The balance identity was inherited from the corrected balance-control audit rather than treating every completed day as accumulation. A day qualified only when its open and close lay inside the completed 70% turnover value area and both UTC halves traded on both sides of the completed POC.

The final audit also enforced:

- one immediately following UTC trade day only;
- causal completed-five-minute reclaim and opposite-edge confirmation;
- frozen full raid extreme and pre-decision invalidation;
- target availability and non-consumption through executable entry;
- one-use daily/confirmed-four-hour pools;
- first strictly later one-minute execution after the 500ms activation representation;
- actual funding, adverse same-minute stop priority, one global slot and fixed-small-risk sizing;
- exact positive-event deletion followed by complete slot rerouting.

`VALIDATION_ATTESTATION.json` contains 75 passing invariants and an independent account replay.

## Event funnel

```text
symbol,year,balances,raid,reclaim,opposite_close,entry,target,geometry
BTCUSDT,2021,81,67,61,9,9,4,4
BTCUSDT,2022,70,53,48,5,5,5,5
ETHUSDT,2021,49,45,40,5,5,5,5
ETHUSDT,2022,71,58,48,2,2,1,1
```

Only six complete 2022 paths survived. The scarcity occurs at the opposite-edge control-transfer condition itself, not mainly at target selection or account routing.

## Economics

| Year / cost | Trades | Multiple | PF | Median | Winner-rerouted multiple |
|---|---:|---:|---:|---:|---:|
| 2021 / 24bp | 9 | 0.994394x | 0.139 | -0.0836% | 0.993498x |
| 2022 / 12bp | 6 | 1.001489x | 1.407 | -0.0304% | 0.996852x |
| 2022 / 18bp | 6 | 1.000777x | 1.192 | -0.0372% | 0.996251x |
| 2022 / 24bp | 6 | 1.000107x | 1.024 | -0.0437% | 0.995690x |

The ordinary 2022 path barely exceeded break-even, but deleting its largest positive event and rerouting the one global slot reduced NAV to 0.995690x. The path therefore fails both the density and winner-independence requirements for steady compounding.

## Decision

The complete AMD/PO3 sequence is coherent but too rare to serve as the missing Core. Relaxing the opposite-edge transfer, expanding the balance population, adding sessions/FVG/OB/MSS, or applying ML/risk/leverage would change or rescue the failed information unit after observing its outcome. Those routes remain prohibited.

Calendar 2023 and official 2024–2026 stayed sealed. No credentials, paper/testnet orders or live orders were used.
