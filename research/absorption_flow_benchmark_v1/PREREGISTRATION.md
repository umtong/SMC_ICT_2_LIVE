# ABSORPTION_FLOW_BENCHMARK_V1 preregistration

## Purpose

Create the first fresh, reproducible strategy result for `SMC_ICT_2_LIVE` on BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT USD-M perpetual futures. No inherited strategy result or Champion is imported.

## Information clock

- Source bars are one-minute bars timestamped at UTC bar open.
- Five-minute signals use only five complete one-minute bars.
- A signal exists only after the five-minute bar closes.
- The earliest entry is the next one-minute open, which is the same instant as the five-minute close.
- Confirmed missing source intervals are never filled; a feature window or trade path crossing a gap is invalid.
- Funding uses the actual historical rate and the contract one-minute open as an explicitly disclosed mark-price proxy.

## Economic families

1. **Absorption continuation:** extreme displacement persists near its terminal extreme even though terminal aggressive flow points against it.
2. **Flow-aligned continuation:** displacement, terminal flow and price holding state agree.
3. **Absorption reversal:** extreme displacement meets opposing aggressive flow and a terminal one-bar reversal; trade direction is opposite the displacement.

A separate cross-asset state requires asset-specific displacement beyond the median four-asset move.

## Search and evaluation

- Development: 2022-04-03 through 2023-12-31, with 2022 and 2023 required to pass independently.
- Validation: 2024 and 2025-H1; only development survivors are opened.
- 216 preregistered candidates; no risk, leverage, cost or validation-period fitting.
- One global pending/open slot across four symbols.
- Fixed 0.5% planned risk and 5x gross leverage cap during alpha selection.
- Base: 5.5 bp taker fee plus 2 bp adverse slippage per side.
- Stress: 1.5x and 2x the same fee/slippage assumptions, with the same signals.
- Same-minute stop/target ambiguity resolves to stop.
- Stop and target are sized to net R after fees and slippage.

## Development gate

Each of 2022 and 2023 must pass under base and 2x costs:

- at least 20 trades
- positive return and average R
- PF >= 1.10
- MDD no worse than -20%
- top-five winner share <= 55%
- return after removing top five trades > -5%

## Target gate

A candidate is Champion-eligible only when both 2024 and 2025-H1 pass the same robustness gate and the minimum 2x-cost geometric daily growth is at least 1%.
