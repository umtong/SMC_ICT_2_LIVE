# Exact Bybit Candle Range Theory

Claim: `CLM-20260726-1630-CRT-001`  
Stage: pre-2024 fatal alpha screen; not rank eligible.

## Explanation for an SMC/ICT trader

The immediately preceding completed candle is the dealing range. Its high and low are the only two external-liquidity objectives.

1. The next candle raids exactly one boundary.
2. A completed lower-timeframe candle closes back inside the old range.
3. The strict variant also requires **CISD**: the close crosses the open of the most recent opposing lower-timeframe candle.
4. Entry is the first actual trade in the next UTC second.
5. Stop is beyond the manipulation extreme.
6. Target is the untouched opposite boundary of the frozen prior candle.

This is not a discretionary chart annotation. Parent/child clocks, raid depth, CISD reference, entry, stop, target and one-global-slot arbitration are fixed before outcome access.

## Distinct scope

Every completed 5m, 15m or 30m candle creates a new range. The strategy uses no fixed session, BPR, FVG/IFVG, breaker, order block, OTE, SMT, OI, options, L2 cancellation, liquidation or OCO state.

## Frozen screen

- Official Bybit BTCUSDT/ETHUSDT public trades.
- Parent 300/900/1800 seconds; child 5/15 seconds.
- Range size 30/60bp minimum.
- One-tick or 5%-of-range raid depth.
- Reclaim or CISD confirmation; 0/0.3 flow requirement.
- 96 fixed cells, one global slot, 12/18/24bp identical-path replay.
- Fit: 2023-01-15, 03-19, 05-21.
- Conditional development: 2023-07-16, 09-17, 11-19.
- 2024-2026, exact funding, BBO audit, risk and leverage remain sealed.
