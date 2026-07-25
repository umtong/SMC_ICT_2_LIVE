# Amendment 001 — causal dollar-volume event clock pivot

Recorded after the preregistered 216-candidate five-minute development screen completed with zero development survivors. The 2024 and 2025-H1 validation intervals were not opened by that screen.

## Why the pivot is economically distinct

The five-minute screen found a small positive development trace in extreme four-hour flow-aligned continuation, but it failed PF and top-winner-removal gates and generated far too few independent trades for the project objective. Changing only stops or a nearby threshold would not solve the capital-velocity constraint.

The next hypothesis keeps the absorption/continuation/reversal mechanism but replaces arbitrary wall-clock bars with an information clock defined by completed historical quote turnover. This tests whether price delivery per unit of market activity, rather than elapsed minutes, contains the missing repeatable edge.

## Causal bar construction

For each symbol and UTC day:

- The dollar threshold is `median(daily quote volume of the prior 20 complete UTC days) / target_bars_per_day`.
- The current day never contributes to its own threshold.
- Complete one-minute source bars are indivisible; threshold overshoot remains in the closing event bar and is not allocated backward or forward.
- A bar closes when the threshold is reached or after a fixed 30-minute stale-state cap.
- Only threshold-completed bars may create new signals. Capped and day-end residual bars update state but cannot initiate trades.
- A decision exists only after the closing source minute completes; the earliest entry is the next actual one-minute open.
- Source gaps are never filled, and a bar or feature window crossing a gap is invalid.

## Frozen development search

- Clocks: 144, 288 and 576 target bars per completed day.
- Families: flow-aligned continuation, opposing-flow absorption continuation, opposing-flow absorption reversal.
- Horizons: 6, 12 and 24 completed event bars.
- Displacement regimes: `2 <= |z| < 4.5` and `|z| >= 3`.
- Terminal flow windows: 2 and 4 completed event bars.
- Net reward/risk: 1R, 2R and 4R.
- Fixed stop buffer: 0.25 event ATR for horizons 6/12; 0.50 ATR for horizon 24.
- Maximum holding: 120, 240 and 480 wall-clock minutes for 1R, 2R and 4R respectively.
- One global active slot across BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT.
- Fixed 0.5% planned risk and 5x gross leverage cap.
- Identical base-cost signals are replayed under 1.5x and 2x costs.

## Chronology

- Development: 2022-04-03 through 2023-12-31, with both years required to pass independently.
- Selection OOS: 2024; physically evaluated only for development survivors.
- Confirmation: 2025-H1; physically evaluated only for 2024 survivors.
- No later data, paper orders, live orders, risk scaling or treasury allocation.

This amendment changes the market clock and holding-time economics, not a nearby threshold chosen from failed outcomes.
