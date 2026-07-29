# ML causal auction-value acceptance and rejection — decision report

**Result:** `RES-20260729-ML-AUCTION-VALUE-001`  
**Claim:** `CLM-20260729-ML-AUCTION-VALUE-001` / issue #387  
**Decision:** ECONOMIC FAIL; official 2024 was not opened.

## Mechanism tested

Each UTC day used only the completed prior UTC day's official Bybit one-minute bars to construct a turnover-at-price profile. Turnover was distributed uniformly over each observed minute range on a fixed log-price grid. The resulting POC, 70%/80% value edges, high-volume nodes and low-density corridors were frozen for the current day.

A completed five-minute close through a value edge created two counterfactual actions:

- acceptance continuation through the adjacent low-density corridor toward the next profile node, with exit on value re-entry, completed trailing-structure loss, target or stop;
- rejection reversion toward POC, with exit on POC delivery, re-acceptance outside value or stop.

ML estimated mean and 35th-percentile action value and selected continuation, reversion or flat. No elapsed-time liquidation was used.

## Fixed account and execution contract

- BTCUSDT and ETHUSDT; one global pending/open slot.
- Completed five-minute decisions; fixed 500 ms latency; first observable one-minute open after activation.
- 24 bp round-trip cost stress plus actual funding.
- Stop-first same-minute ambiguity and adverse gap execution.
- Fixed 0.5% NAV loss budget and 3x notional cap during alpha discovery.

## Economic result

The primary 5 bp / 70% profile generated 11,162 value-edge events. Raw continuation and reversion actions had negative mean and median unit returns in 2021, 2022 and 2023. Median account return was approximately -0.5%, indicating that the structural stop was the modal outcome after costs.

Every dense mean-value ML policy lost money in 2022. Across the tested profile/stop sensitivity, losses ranged from 48.28% to 65.26%, with PF between 0.47 and 0.59.

The only positive 2022 diagnostic was the 5 bp / 80% value-area lower-tail blend:

- +1.8956% total return;
- +0.005145% geometric daily growth;
- 18 trades;
- PF 1.342;
- MDD 3.70%;
- negative median trade;
- 92.81% of positive PnL in the top five trades.

It failed the non-sparse eligibility requirement. After refitting through 2022 and freezing the same policy, 2023 produced one trade and lost 0.0541%. Requiring a positive 35th-percentile action value selected zero trades.

## Decision

The prior-day turnover-profile acceptance/rejection family is closed. Its value-edge geometry did not provide a stable cost-surviving action advantage, and ML could only choose broad losses, a one-off sparse tail or no trades. Official 2024H1, risk/leverage optimization, ranking changes and order authority were not opened.

The next route must change the economic source of alpha rather than narrow profile bins, add value-edge confirmations, relax costs or increase leverage.
