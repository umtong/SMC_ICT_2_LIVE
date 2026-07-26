# Bybit liquidation-sweep reclaim and MSS screen

Claim: `CLM-20260726-LIQ-SWEEP-MSS-001`  
Branch: `agent/r11-liq-sweep-mss-001`

## SMC/ICT explanation

This study trades a fully observed state transition, not a candle that merely resembles a liquidity sweep.

1. **External liquidity pool** — the highest high and lowest low from a completed prior 5- or 15-minute rolling range.
2. **Liquidity raid** — Bybit trades beyond that prior high or low by a fixed dimensionless distance.
3. **Forced delivery** — exchange-reported liquidations occur in the raid direction. A low raid requires forced sells from long liquidations; a high raid requires forced buys from short liquidations.
4. **Absorption and refill** — aggressive flow turns against the raid and the depleted destination-side best quote replenishes relative to its prior-only median.
5. **Reclaim** — price returns inside the raided level.
6. **MSS/CISD** — after reclaim, completed price breaks the opposite pre-raid 3- or 10-second micro swing.
7. **Entry** — only after the completed MSS, at the first executable Bybit bid/ask available 100 or 300 ms later.
8. **Invalidation** — the protective stop is outside the actual raid extreme observed by the decision, plus the larger of one spread or 1 bp.
9. **Objective** — either internal range equilibrium or a fixed 2R structural target. There is no elapsed-time forced exit. A position unresolved at the source boundary receives the full stop rather than disappearing.

In discretionary SMC language this is: external liquidity is raided, forced participants are flushed, the market fails to continue, displacement returns through the level, micro structure shifts, and the trade targets internal liquidity. Every term above has a point-in-time exchange-data definition.

## Why this is structurally different

Prior project screens tested ordinary sweep candles, bar-based absorption, generic liquidation thresholds, inferred inventory maps, L2 cancellation/refill taker rules and movement-hazard OCO payoffs. This rule requires their intersection in a causal sequence: **actual liquidation + external-range raid + range reclaim + opposite flow + quote refill + MSS**. No single threshold authorizes a trade.

## Frozen fatal screen

- execution venue and product: Bybit USDT linear perpetual;
- initial symbols: `BTCUSDT`, `ETHUSDT`;
- one global pending/open slot;
- fit dates: 2023-01-01, 2023-03-01, 2023-05-01;
- independent development dates: 2023-07-01, 2023-09-01, 2023-11-01;
- public Tardis normalized Bybit `quotes`, `trades` and grouped `liquidations`;
- `local_timestamp` is the availability clock;
- completed one-second features; actual first post-decision quote for entry and exit;
- 768 immutable policies;
- 12/18/24 bp additional round-trip cost replay after observed spread;
- 0.5% NAV planned loss sizing;
- 2 bp adverse funding reserve per crossed settlement boundary in this fatal screen;
- largest 10% positive 12-bp event keys excluded before global rerouting;
- 2024–2026 mechanically unopened;
- no credentials or orders.

Fit thresholds are determined only from the fit dates. Development opens only if a complete fit gate survivor exists. A development survivor remains non-rank-eligible and must be expanded across every remaining pre-2024 first-day sample with exact funding and deeper execution before official 2024 can be considered.

## Validation

The immutable implementation is transported in four hash-registered Base64/GZIP parts. The loader verifies every part, combined Base64, compressed bytes and raw scientific source before execution.

Local checks completed before workflow publication:

- Python compilation: PASS;
- six causal/execution tests: PASS;
- future-prefix invariance of the signal state;
- decision-after-MSS entry;
- structural target and stop behavior;
- source-boundary full-stop accounting;
- one-global-slot arbitration;
- exactly 768 candidate cells.

Scientific implementation SHA-256: `700273530173aabc8c97af59d77349ae261d75678fd31f4bc77f35f8c4a8c072`.
