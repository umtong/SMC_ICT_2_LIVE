# ML Funding-Settlement Hazard OCO

## One SMC/ICT-readable mechanism

1. **Scheduled liquidity transfer** — the next Bybit funding timestamp and the final pre-settlement funding rate are known before activation. Funding, mark/index premium, open-interest change and the preceding one-hour price path describe whether leverage is compressed enough for a post-transfer expansion.
2. **ML filter** — one pooled, standardized L2-logistic model estimates whether the frozen two-sided order path will finish positive after 18 bp. The eight named inputs are published with their coefficients; no model, feature or threshold family is searched.
3. **Two-sided displacement entry** — one second after settlement, symmetric STOP_MARKET-style orders are armed around the first observed price. Direction is selected only by the first causal break, not predicted in advance.
4. **OCO execution** — the opposite order remains vulnerable for a fixed one-second cancellation latency. An opposite trigger during that interval is charged as an adverse double fill. Only one pending or open order exists across BTC and ETH.
5. **Structural payoff** — trigger distance is a frozen function of the prior one-hour realized volatility and range. Target is 3.5 trigger units; stop is 1.25 units. A pending order may expire after 30 minutes, but a filled position exits only at target, structural stop or the conservative source-boundary full-stop rule.
6. **Cost and funding** — 12/18/24 bp round-turn replays are identical. Any later funding timestamp crossed by an open position is charged at the absolute rate, which is deliberately adverse.

This is materially different from the retired funding-transfer rules, which predicted continuation or reversal at fixed horizons, and from the retired hazard-OCO rules, which were activated by unscheduled own-symbol or cross-asset shocks.

## Frozen research stage

- Source: first day of each month from Tardis normalized Bybit `derivative_ticker` files.
- Information availability: Tardis `local_timestamp` in original capture order. Exchange timestamps are diagnostic only and never reorder messages.
- Symbols: `BTCUSDT`, `ETHUSDT`; one global pending/open slot.
- Fit: 2020-2021. Calibration payoff means: 2022 H1. Untouched confirmation: 2022 H2.
- 2023 opens only if every prewritten confirmation economic gate passes.
- 2024-2026, credentials and order submission are prohibited by code.
- This sparse first-day proxy is not rank eligible. A survivor requires continuous Bybit-native BBO/depth, exact funding, latency/partial-fill stress and the official walk-forward.
