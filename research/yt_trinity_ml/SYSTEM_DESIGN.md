# YT Trinity unified causal SMC/ICT system

Status: `DRAFT_IMPLEMENTATION_AUDIT_REQUIRED_BEFORE_RANKING`

The system is one coherent delivery narrative. “Reversal” and “continuation” are
terminal diagnostic paths, not separately selected strategy families. A weak half-year
cannot authorize an unrelated-alpha switch until the narrative has been shown to be
causally and faithfully implemented.

## Economic narrative

Price is modeled as moving between knowable liquidity pools. A candidate exists only
when the complete causal chain is present:

1. **Context and draw** — completed higher-timeframe structure, dealing range,
   premium/discount location, session references, and a still-available external
   liquidity pool define the draw on liquidity.
2. **Liquidity event** — price either raids fresh external liquidity and closes back
   through it, or makes the first close-accepted structure break in the direction of
   the draw.
3. **Displacement and structure** — a later completed bar breaks the protected internal
   swing with directional body, range expansion, close location and displacement
   efficiency. OHLC bars that raid both sides are not ordered without finer data.
4. **PD array** — the entry zone must come from the confirming impulse: its newly
   created FVG, the last opposite candle within that impulse, or their overlap. A
   globally forward-filled arbitrary “order block” is not accepted.
5. **Mitigation and trigger** — the first return arms the entry phase. A non-rejecting
   touch does not automatically destroy the setup. Entry occurs only after a causal
   close back out of the array or a later CISD-style break of the retest candle.
6. **Structural risk and target** — reversal risk is beyond the raid extreme;
   continuation risk is beyond the protected swing. The opposing external-liquidity
   target is frozen before entry and is never chased as new pivots appear.

A setup ends only when its structural stop is breached, its frozen draw is taken before
entry, a deeper same-draw raid supersedes it, or an entry is produced. Elapsed time is
not a setup or position exit.

## Liquidity and market structure

The causal liquidity map combines confirmed equal highs/lows, confirmed internal and
external swings, previous hour/four-hour/day/week extremes, completed Asia and London
opening ranges, and completed one-hour/four-hour swing structure. A level is eligible
only after it becomes knowable and before its first subsequent taking.

Higher-timeframe bars are resampled and joined to the decision frame only at their
completion times. Pivots appear only after their right-side confirmation bars. The
feature history must remain identical when unseen future rows are appended.

## ML role

ML does not invent entries from indicators. It ranks fully formed structural narratives
and chooses among `ABSTAIN`, `MARKETABLE`, and `PASSIVE_RETEST` using action-specific,
after-cost lower-confidence expected log growth. Its inputs include liquidity quality,
raid depth, draw quality, higher-timeframe alignment, displacement efficiency,
FVG/order-block geometry, mitigation depth, CISD delay, target/stop geometry, volume,
volatility, positioning, session and execution state.

Marketable and passive outcomes have separate labels. Passive nonfill is zero return,
not a recycled market-order outcome. Training rows become available only after all
relevant outcomes resolve, chronological calibration is purged, and the previous model
remains active through the deterministic training-completion lag.

## Implementation audit before premise rejection

Every economic screen emits a stage funnel:

`external raid / first break → narrative with frozen draw → displacement/MSS → valid
impulse PD array → first mitigation → CISD/rejection → resolved action label → account`

A weak result is first classified as one of the following:

- a missing or distorted SMC narrative stage;
- wrong stop/target or draw-on-liquidity geometry;
- coarse-bar ordering, fill, fee, funding or label error;
- ML ranking or abstention error after valid candidates exist;
- economically weak behavior after the preceding items are complete.

The repair order follows that list. Reversal and continuation diagnostics may reveal
where the system is incomplete, but neither is independently selected or discarded.
Only a causally complete implementation with realistic execution can support a premise
change.

## Execution and account

Orders activate 500 ms after the last information used by the decision. Event-tape
replay uses observable bid/ask, depth-dependent impact, correct-side queue consumption,
partial fills, nonfills, funding and stop-first same-timestamp ambiguity. Targets cross
the observable book unless a reduce-only target queue is explicitly modeled.

Quantity is whole-account NAV times the selected risk fraction divided by expected
per-unit loss, including entry-to-stop distance, fees, spread, slippage, impact and
funding. All symbols share one pending-or-open entry slot. Liquidation before the
structural stop invalidates the configuration. No position is closed merely because
elapsed time reached a limit.

## Evaluation path

1. Bind the complete 186-video corpus and ontology by digest.
2. Build the unified narrative and its implementation funnel on pre-2024 canonical data.
3. Repair the earliest missing structural stage before interpreting weak economics.
4. When the causal narrative and basic after-cost possibility are present, freeze the
   system and open 2024H1 without using 2024H1 to reselect it.
5. A weak 2024H1 triggers the same implementation audit, not an automatic unrelated
   strategy switch.
6. Event-tape-valid candidates proceed through the continuous 2024-01-01 to 2026-06-30
   NAV path with no half-year reset.

The one-minute lane remains provisional and cannot alter the cumulative strategy rank.
