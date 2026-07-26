# Bybit BTC-to-ETH event-time residual screen

Claim: `CLM-20260726-0952-XASSET-MICROSHOCK-001`  
Result: `RES-20260726-XASSET-MICROSHOCK-ETH-001`

## Economic question

Can a completed 1/2/5-second BTCUSDT price-and-aggressive-flow shock reveal a still-unincorporated ETHUSDT response large enough to trade after 100 ms latency and 12/18/24 bp round-trip costs?

This is not the reported completed-bar lead-lag family. It uses Bybit-native public trades, prior-only one-second beta and realized volatility, completed event-time windows and an explicit residual-gap floor.

## Causal amendments before PnL

`preregistration_v1.json` was committed before any archive member or PnL was read. A formula-only diagnostic then exposed a zero-denominator defect in the original rolling-median shock scale and showed that unconditional expected ETH responses were generally smaller than costs. Before any strategy PnL or frozen validation access, `preregistration_v2.json` replaced the scale with prior realized variance and required a 12/18/24 bp direction-aligned residual gap.

## Fatal result

The two fit dates produced only two events under the loosest full economic filter. The two development dates produced zero events with a residual gap of even 12 bp before cooldown, entry, exit or global-slot logic. Consequently every one of 2,592 frozen cells has zero possible development trades versus the preregistered minimum of 20.

No strategy PnL was computed because the information unit failed before trade construction. The frozen September and November 2023 dates, all 2024–2026 data, funding, bid/ask execution, risk and leverage search remained unopened.

## Decision

`RETIRE_BTC_TO_ETH_SUBMINUTE_RESIDUAL_INFORMATION_UNIT`

Do not retune neighboring BTC/ETH z, flow, activity, underreaction, gap or catch-up thresholds on these source partitions. The mechanism may be reopened only with a materially less efficient follower such as SOL/XRP, an independent queue/depth state or another information source.
