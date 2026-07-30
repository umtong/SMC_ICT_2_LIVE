# Causal intermarket SMT control-transfer first-repricing contract

Claim: `CLM-20260730-INTERMARKET-SMT-REPRICING-001`

## Economic logic

BTCUSDT and ETHUSDT are testbeds for one correlated-market control-transfer premise.

At each UTC day open, both markets have a completed prior-day high, low, and midpoint. A raid in one market is not automatically a reversal. SMT is eligible only when the correlated peer is close enough to its corresponding same-scale boundary to confirm, but does not consume it. If the swept market then reclaims its boundary before peer confirmation and completes an internal order-flow shift away from the raid, the event is treated as contract-specific liquidity engineering rather than broad fair-value acceptance.

The strategy never chases the shift close. It places one first-repricing limit at the swept prior-day boundary. The pending order occupies the one global slot and is cancelled when the peer confirms, the source premise is reaccepted outside, the stop is crossed, or a favorable objective is consumed before fill.

After fill, 50% realizes at prior-day equilibrium and 50% targets the untouched opposite prior-day boundary. The runner can tighten only to a later causally confirmed protected five-minute pivot. There is no elapsed-time or scheduled close.

## Frozen causal state

- Canonical Bybit USDT-linear BTCUSDT and ETHUSDT 2021–2023 only.
- Previous complete UTC-day high/low/midpoint; actionable only during the immediately following UTC day.
- First strict one-minute sweep per side/day.
- Same-minute double sweep is flat.
- Peer-near condition: contemporaneous peer price within `0.50 ×` latest prior-only completed 15-minute ATR20 of its corresponding boundary, while that boundary remains unconsumed.
- Swept market must reclaim on a completed five-minute close before peer confirmation.
- Control transfer is the first later completed five-minute close through the latest causally confirmed width-two opposite five-minute pivot away from the raid.
- Midpoint preconsumption, peer confirmation, or source outside reacceptance before decision makes the event flat.

## Frozen execution and account

- Decision activation: `available_at + 500ms`.
- Limit at swept prior-day boundary; one-tick trade-through required after activation.
- Pending order occupies the global slot; no TTL.
- Initial hard stop: one tick beyond the full sweep-to-shift excursion extreme.
- Partial: 50% at prior-day midpoint.
- Runner: 50% at untouched opposite prior-day boundary.
- Later protected-pivot tightening only after partial realization.
- Same-minute fill/stop: adverse fill then stop.
- Same-minute fill/favorable objective: no fill unless strict ordering is provable.
- After fill, stop has priority. Midpoint and final target in the same minute credit midpoint only; final target requires a later minute.
- Actual signed funding; 12/18/24bp; fixed 0.5% current-NAV planned initial loss including costs and one adverse entry-known funding reserve; 3× notional cap.
- One global pending/open BTC/ETH slot.
- No elapsed-time, session, day-boundary, or research-stage strategy close.

## Required matched control

`SINGLE_ASSET_CONTROL` uses the identical swept-market reclaim, shift, first-repricing, partial, runner, stop, and source state-loss lifecycle without peer-near admission or peer-confirmation cancellation. SMT must add broad cost-net value over this control.

## Chronology and failure boundary

- 2021: mechanism diagnostic only.
- 2022: untouched deterministic fatal screen.
- 2023 and official 2024–2026 stay sealed unless 2022 passes fixed breadth, median/PF, half-year, cost, winner-deletion, and matched-control gates.
- ML, risk/leverage, alternate pairs, peer distance, shift, entry, partial, runner, target, stop, cost, session, or symbol-side rescue is prohibited after failure.
