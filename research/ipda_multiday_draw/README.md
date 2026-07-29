# IPDA 20/40/60-day nested dealing-range draw audit

Result ID: `RES-20260729-IPDA-MULTIDAY-DRAW-001`  
Claim ID: `CLM-20260729-2158-IPDA-DRAW-001`  
Work Claim: #404  
Verdict: **economic failure; exact family retired**

## Hypothesis

At each 00:00 UTC boundary, freeze only completed prior-day information for the 20-, 40-, and 60-day dealing ranges. The investigated SMC/ICT draw-on-liquidity states were:

1. nested range position aligned above or below all three equilibria;
2. prior-day acceptance beyond a 20- or 40-day boundary, with the next longer-range external pool as the draw;
3. a one-sided prior-day raid and reclaim, with the opposing multi-day pool left unconsumed;
4. a programization correction for accepted expansion: wait for a causal retest and reclaim of the accepted boundary before entering toward the next pool.

Direction and target were frozen at the day boundary. Entry required the first completed five-minute displacement close through prior internal structure in the frozen direction. New orders activated 500 ms later and used the first fully observable one-minute open. Stops were causal structural invalidations; targets were the frozen IPDA external pools. There was no elapsed-time liquidation.

## Evaluation contract

- Canonical Bybit USDT-linear BTCUSDT and ETHUSDT only.
- Existing `bars_1m`, `bars_5m`, and `bars_1d` tables; no reacquisition.
- 2021 diagnostic, 2022 development, frozen 2023 confirmation.
- 24 bp all-in round-trip cost.
- One global pending/open slot.
- Fixed 0.5% planned stop-loss budget and 3x notional cap.
- Stop-first treatment inside an ambiguous minute.
- ML and official 2024-2026 evaluation were prohibited unless fixed-rule pre-2024 economics were positive, non-sparse, and persistent.

## Event economics

The broad, frequent states were consistently negative:

- `nested_position_20`: mean net R was -0.2577 in 2021, -0.3363 in 2022, and -0.5290 in 2023.
- `opposite_after_reclaim_20`: -0.7681, -0.5891, and -1.0000.
- `opposite_after_reclaim_40`: -1.0000 in every year.

The only initially interesting path was a completed prior-day acceptance beyond the 20-day range followed by delivery toward the 40-day pool:

- 2021: 14 events, mean +0.0917R, median -1R, PF 1.107.
- 2022: 20 events, mean +0.2643R, median -1R, PF 1.311.
- 2023: 14 events, mean -0.5696R, median -1R, PF 0.387.

All positive R in every yearly slice was concentrated in at most five winners. The apparent early edge did not survive 2023.

## Programization correction

The first version entered the first same-direction displacement after daily acceptance. That can chase an already extended auction, so a more faithful continuation implementation was tested:

1. prior day accepts beyond the shorter IPDA boundary;
2. current day trades back to that frozen boundary;
3. price reclaims the boundary and then displaces through internal structure;
4. entry occurs at the first observable one-minute price after 500 ms;
5. stop is beyond the actual retest excursion;
6. target is the next 40- or 60-day external pool.

This correction did not recover persistent alpha:

- 40-day target: +1.7299R mean in 2021, -0.5098R in 2022, and -1.0000R in 2023.
- 60-day target: +3.9886R mean in 2021 and -1.0000R in 2022; no 2023 route survived the entry geometry.

## One-slot account result

| Policy | Final NAV | Geometric daily growth | Trades | Max drawdown | PF | Top-five positive share |
|---|---:|---:|---:|---:|---:|---:|
| accepted boundary retest → 60-day pool | 10,517.39 | 0.004607% | 9 | 3.93% | 2.202 | 100% |
| accepted expansion → 40-day pool | 9,700.46 | -0.002780% | 39 | 6.78% | 0.826 | 100% |
| accepted boundary retest → 40-day pool | 9,830.23 | -0.001562% | 17 | 5.87% | 0.778 | 100% |
| nested position → 20-day pool | 3,264.30 | -0.1022% | 583 | 70.60% | 0.620 | 23.39% |

The nominally best account made all of its positive PnL from one 2021 trade. It had no winning trade in 2022 and no accepted-boundary-to-60-day entry in 2023. Its daily growth is about 0.46% of the 1% objective and is roughly 217 times too small on the primary growth scale.

## Decision

- Do not open official 2024-2026 for this route.
- Do not fit ML to nine concentrated trades.
- Do not rescue the route with leverage, confidence scaling, adjacent lookbacks, or looser displacement thresholds.
- Retire the exact IPDA 20/40/60-day approach-to-pool family.
- Preserve the distinction between strategy failure and programization failure: chasing acceptance was a plausible implementation defect, but the corrected boundary-retest implementation also failed economically.

`run.py` reproduces the causal state construction, event replay, and fixed-risk one-slot account. `RESULT.json`, `event_economics.csv`, and `account_summary.csv` contain the durable figures.
