# Causal SMT liquidity-sweep / FVG fatal screen

This study converts a familiar SMC/ICT chart narrative into a fully timestamped event contract.

## Trader explanation

1. **External liquidity is known first.** A high or low becomes eligible only after the right side of a five-second pivot has completed. An optional equal-high/equal-low pool requires two confirmed pivots within 6 bp.
2. **A sweep is an event, not a wick drawn after the fact.** The event is the first inside-to-outside crossing after the pool became knowable. If the level was already consumed during pivot confirmation, it is never reused.
3. **SMT divergence is literal.** BTC may take its high while ETH leaves its own high untouched, or vice versa; the same rule applies to lows.
4. **Rejection route.** The sweeping market reclaims the pool, opposite aggressor flow appears, price displaces away from the raid, and a causal one-second FVG may form. Entry is after confirmation plus 100 ms, either immediately or after a later completed bar mitigates the FVG midpoint.
5. **Liquidity-transfer route.** If the sweep is accepted instead of reclaimed, the paired market may be traded toward its still-untouched corresponding liquidity, but only with aligned flow.
6. **Invalidation and exits are structural.** Reversal risk is beyond the sweep extreme. Catch-up risk is derived from the distance to the untouched liquidity target. There is no arbitrary elapsed-time liquidation; unresolved sparse-day paths receive a full stop loss.

## Fatal-screen boundary

The screen uses six official Bybit public-trade days from 2023, 3,072 frozen policies, one global BTC/ETH slot, 100 ms latency and identical 12/18/24 bp replay. It can reject the formulation but cannot promote a strategy into the cumulative ranking. A survivor must receive broader continuous pre-2024 data, exact BBO/depth, funding, fill, capacity, risk sizing and NAV validation before 2024 is opened.

## Commands

```bash
python research/smt_fvg_liquidity_sweep_20260726/run_screen.py self-test
python research/smt_fvg_liquidity_sweep_20260726/run_screen.py run \
  --cache /tmp/bybit-smt-fvg \
  --output artifacts/smt_fvg_liquidity_sweep
```
