# Quarter-hour order-flow research

Claim: `CLM-20260726-0240-QHOUR-001`  
Branch: `agent/r10-quarter-hour-orderflow-001`

## Mechanism

The study treats the UTC quarter-hour as a causal event clock, not as a retrospective candle pattern. At minutes 00, 15, 30 and 45, aggressive quote-notional imbalance is accumulated only over the completed first ten seconds. The signal becomes available at second 10. The initial fatal screen waits until the next exact one-minute contract open, so it assumes neither subsecond connectivity nor a favorable intra-minute fill.

Matched windows beginning at minutes 07, 22, 37 and 52 are evaluated with the same signal and execution rules. They are controls: generic order-flow continuation is insufficient unless the quarter-hour version is materially stronger.

## Staging

1. Verify official Binance archives, adjacent CHECKSUM files, schemas and time coverage. No PnL is computed in this stage.
2. Run the frozen 2022 six-date fatal pilot.
3. Only a fatal-pilot survivor may open the disjoint six-date 2022 development sample.
4. 2023 selection, 2024 validation, 2025/2026 and exact bookTicker execution remain sealed behind their preceding gates.

## Validity and safety

- Completed ten-second information only.
- Exact next-minute entry and exit opens in the initial screen.
- Missing one-minute state invalidates the event; no time compression or forward fill.
- Stop/gap ambiguity is adverse.
- Exact historical funding uses the recorded rate and contemporaneous official mark open.
- One global directional slot or one explicitly capitalized market-neutral basket.
- Same trade path is replayed at 12, 18 and 24 bps round-trip costs.
- No credentials, private endpoints, orders or deployment bundle.

The source paper supplies a falsifiable mechanism, not accepted performance. All economic conclusions come from this repository's own data, cost and account contract.
