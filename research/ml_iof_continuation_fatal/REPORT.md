# Scale-matched institutional order-flow first-pullback fatal screen

**Result:** `RES-20260730-IOF-FIRST-PULLBACK-FATAL-001`  
**Claim:** `CLM-20260729-ML-IOF-CONTINUATION-001`  
**Verdict:** `RETIRED_DETERMINISTIC_SUBCOST_AND_NEGATIVE_FIRST_PULLBACK`

## Question

Does an established, causally confirmed four-hour order-flow state create repeatable after-cost value when a completed fifteen-minute displacement breaks internal liquidity and the trade waits for the first five-minute midpoint pullback that respects the protected origin?

This is the pre-ML screen for the transcript-grounded internal-liquidity to scale-matched external-liquidity delivery hypothesis. FVG, OB, CISD, premium/discount and session labels are not Boolean gates.

## Frozen implementation

- BTCUSDT and ETHUSDT canonical 2021-2023 Bybit data only.
- Four-hour bullish state: the latest two fully right-confirmed swing highs and lows are HH + HL; bearish is LH + LL.
- Fifteen-minute displacement: break of the latest confirmed internal swing in the state direction, directional body efficiency at least 0.60, and range at least the prior-only 96-bar median.
- Entry: first later completed five-minute bar that trades into the displacement-body midpoint and closes back through it in the delivery direction while the latest confirmed opposite fifteen-minute pivot remains intact.
- Fixed 500 ms activation, first strictly later observed one-minute open.
- Stop: protected opposite fifteen-minute pivot plus one basis point adverse buffer.
- Target: nearest causally available and still-unconsumed confirmed four-hour or prior completed UTC-day external liquidity.
- Actual signed funding, 0.5% current-NAV planned loss, 3x cap, 12/18/24 bp total stress and 4 bp stop slippage.
- One global BTC/ETH slot. No elapsed-time, session, UTC-day or stage-boundary strategy close.

## Results

The runner generated **1,940** executable candidates. The fixed global-slot path was frequent and active in both years, but the ordinary trade distribution was stop-dominated.

| Year | Cost | Trades | NAV | PF | Median | H1 | H2 | Winner-removed NAV |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 12 bp | 279 | 0.769180x | 0.750 | -0.5000% | 0.988444x | 0.778172x | 0.713190x |
| 2022 | 18 bp | 279 | 0.731078x | 0.701 | -0.5000% | 0.956061x | 0.764677x | 0.677038x |
| 2022 | 24 bp | 279 | 0.698626x | 0.656 | -0.5000% | 0.927978x | 0.752848x | 0.649479x |
| 2023 | 12 bp | 282 | 0.838823x | 0.820 | -0.5000% | 0.904579x | 0.927308x | 0.752958x |
| 2023 | 18 bp | 282 | 0.768473x | 0.730 | -0.5000% | 0.866975x | 0.886385x | 0.694274x |
| 2023 | 24 bp | 282 | 0.713874x | 0.655 | -0.5000% | 0.836538x | 0.853367x | 0.648659x |

At 24 bp:

- 2022: 82 targets, 197 stop exits, 0 boundary marks; gross mean -8.75 bp, gross median -76.86 bp, median hold 4.65 h, top-five positive-PnL share 16.76%.
- 2023: 86 targets, 195 stop exits, 1 boundary mark; gross mean +10.41 bp, gross median -43.02 bp, median hold 5.09 h, top-five positive-PnL share 21.38%.

## Programization checks

- Two fresh-process executions reproduced `RESULT.json`, candidate inventory and cost grid byte-for-byte.
- Every entry timestamp is strictly later than pullback decision plus 500 ms.
- All candidate stop-entry-target geometry is directionally valid.
- Full global routing has no overlapping entry before the prior observed exit minute.
- Unresolved year-end exposure is marked; the mark is not represented as a strategy close.
- No elapsed-time or scheduled exit exists.

## Interpretation

This exact implementation does not fail because opportunities are too sparse or because five winners were removed. It fails because most first pullbacks do not preserve the assumed order flow: 2022 gross mean was already negative, and 2023's small positive gross mean was structurally below realistic cost. The median trade in both years is the planned stop loss.

The causal SMC/ICT narrative is reasonable, and the programization checks pass, but the chosen observable state—confirmed four-hour swing sequence plus one fifteen-minute displacement and one midpoint pullback—is insufficient to identify actual sponsored delivery. A new study would need materially new contemporaneous information such as local absorption/replenishment, index-led price discovery or a directly observed inventory transition. It may not rescue this family with another pivot span, body threshold, midpoint/FVG depth, target, cost, risk, leverage, session or ML filter.

ML, risk/leverage research and official 2024-2026 remain closed. No credentials or orders were used.
