# Account-path and source-gap correction V5D

Status: frozen before any authoritative V5D price or PnL screen.

Claim: `CLM-20260725-1850-XVENUE-001`.

V5C corrected exact-arrival stop pricing and the pilot-day denominator. Four remaining issues can still overstate performance or make account-level gates incomparable, so V5C and all earlier outputs remain diagnostic only.

## 1. Remove the arbitrary long-exit price floor

The prior mandatory-exit rule bounded a long liquidation price at 10% of the observed bid. That cap can hide terminal losses during severe top-quote depletion. V5D removes the economic floor. A machine-positive value is used only to keep logarithmic fixed-notional diagnostics finite; account NAV is allowed to reach or cross zero and is then reported as terminal account loss, -100% return and 100% drawdown.

## 2. Use one chronological marked account path

The prior summary added closed-path drawdown to maximum intratrade drawdown even though intratrade marks were already measured against the account peak. V5D uses the maximum of the chronological marked-path drawdown and closed NAV drawdown. It never adds overlapping drawdown components.

## 3. Reset state after unavailable source intervals

Tardis normalized CSV omits disconnect events. The aligned frame therefore retains the complete 100-ms wall-clock grid and marks unavailable state explicitly. Rolling basis, return and flow state is segmented at every unavailable Binance/Bybit state bucket; pre-gap observations cannot re-enter a post-gap signal window. An irregular or time-compressed grid fails closed.

An accepted position must keep finite Binance and Bybit completed state from entry through exit. The first executable entry and exit quote must arrive no more than one second after the aligned latency boundary. A position that crosses a longer unobservable interval fails closed rather than receiving a favorable delayed fill.

## 4. Rerun top-10% removal from initial NAV

Deleting stored winning returns does not release their global account slots or recompute later risk sizing. V5D identifies the baseline 5-bps top 10% event keys, excludes them before global slot competition and replays the entire 2022-2023 development path from initial NAV. This counterfactual is run only for candidates that pass every other development gate; candidates failing another gate cannot advance and do not consume the extra replay budget.

## Unchanged surfaces

Signals, venues, BTC/ETH symbols, sample dates, family definitions, parameter grid, 100/500-ms latency, 3/10-second holds, fees, top-quote participation, impact curve, 0.5% planned risk, 3x leverage cap, prospective funding-boundary exclusion and economic thresholds remain unchanged. 2024 selection, 2025 confirmation, 2026 and all order paths remain sealed.

Only V5D or a later explicitly corrected engine may challenge the strategy ranking.
