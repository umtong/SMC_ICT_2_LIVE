# Causal Bybit MMXM lifecycle

Claim: `CLM-20260726-1634-MMXM-001`

This study tests the complete ICT **Market Maker Buy Model / Market Maker Sell Model** rather than another isolated candle or PD-array entry.

## Explanation to an SMC/ICT trader

1. **Original Consolidation** — freeze the range that holds the eventual draw on liquidity.
2. **Engineering Liquidity** — require a stair-step curve with at least two confirmed lower-high shelves below the range for MMBM, or higher-low shelves above it for MMSM.
3. **Terminal Raid** — the last confirmed external low/high must be swept and reclaimed after price has travelled deeply away from the origin.
4. **Smart Money Reversal** — a completed displacement candle must produce CISD/MSS through the final engineered shelf.
5. **First Hold** — enter only after the first pullback holds either the broken shelf or the displacement-body midpoint; entry is the next 5-minute open.
6. **Delivery** — the target is the far side of the frozen Original Consolidation. The stop remains beyond the terminal raid.

No FVG, IFVG, BPR, breaker, Unicorn, OTE, Silver Bullet, SMT or arbitrary maximum-hold rule is required. Those are separate dependencies already tested or currently claimed elsewhere.

## Staging

- 2022: fit screen across 64 fixed policies.
- 2023: downloaded only after fit survivors are frozen.
- 2024–2026: prohibited by code.
- One global pending/open slot across BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT.
- Identical raw trade candidates replayed at 12/18/24 bps with risk-based sizing.

A zero-survivor result retires this exact full-lifecycle translation. A survivor still requires exact BBO/depth and actual-funding validation before ranking or practical use.
