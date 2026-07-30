# Causal high-/low-resistance liquidity control-transfer contract

Claim: `CLM-20260730-CAUSAL-LIQUIDITY-RESISTANCE-TRANSFER-001`

## Economic logic

A price level is not called high-resistance merely because it is a pivot. It must be causally known, remain unconsumed, reject price at least twice, and generate a material favorable excursion away after each defense. The next intrusion begins a control-transfer event.

- **ACCEPT**: completed value establishes beyond the formerly defended level, the first return rejects from the new side, and delivery continues toward the nearest still-unconsumed low-resistance external pool.
- **REJECT**: price is reaccepted to the old side and completed internal order flow shifts away, trapping breakout inventory and rotating toward the nearest still-unconsumed external pool on the opposite side.
- **FLAT**: no completed control state, no fresh structural destination, or the nearest destination is itself high-resistance.

The order is a single first-repricing limit at the defended level. Confirmation closes are never chased. Entry, stop, target, pending cancellation, hold, and exit all follow the same control premise.

## Frozen data and chronology

- Canonical Bybit USDT-linear BTCUSDT and ETHUSDT only.
- Calendar 2021 is context/diagnostic; calendar 2022 is the untouched deterministic fatal screen.
- Previous completed UTC-day/week highs/lows and causally confirmed width-two 4h pivots.
- Causal 1m/5m/15m/4h availability and exact signed funding.
- Fixed activation: decision availability +500ms.
- One global pending/open slot.
- No elapsed-time, session, UTC-day, or stage-boundary strategy close.

## Frozen state definitions

- Defense zone: within `0.10 ×` prior-only 15m ATR20 of the external level.
- Defense confirmation: completed 15m close on the old side followed by at least `0.50 × ATR` favorable excursion before a completed 15m body accepts beyond.
- High resistance: two distinct confirmed defenses separated by at least one completed 15m bar.
- Wick intrusion does not itself retire a level; completed 15m body acceptance is full consumption.
- ACCEPT/REJECT route is fixed by the first completed 15m close after the event intrusion. A later failure makes the event flat, never switches route.
- First-repricing fill requires one-tick trade-through after +500ms; mere touch does not fill.
- Pending orders occupy the global slot and cancel only on target, stop, or premise consumption.
- Nearest external level is binding. The system may not skip a closer high-resistance obstacle to claim a farther target.

## Account contract

- Fixed current-NAV planned loss: 0.5%, including round-trip fee stress and one adverse entry-known funding reserve.
- Notional cap: 3× NAV.
- Costs: 12/18/24bp plus exact realized funding.
- Stop/target ambiguity after fill: adverse stop first.
- Fill/stop in the same minute: adverse fill then stop.
- Fill/target in the same minute: no fill unless strict ordering is proven.
- Unresolved year-end positions are marked and retain the slot; the mark is not a strategy close.

## Failure boundary

A negative, sparse, sub-cost, sign-unstable, or winner-dependent 2022 result retires this exact information unit. No defense-count, distance, pivot-width, target, stop, entry-offset, TTL, cost, symbol-side, ML, risk, or leverage rescue is authorized.
