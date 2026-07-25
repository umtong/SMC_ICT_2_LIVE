# Fixed-session VWAP acceptance screen

## Decision

`RES-20260726-VWAP-ACCEPTANCE-001` is **TESTED_BELOW_GATE**. A physically isolated 2023 development screen tested 384 immediate acceptance/failed-acceptance policies and 192 accepted-band-retest pullback policies. No candidate was positive at 12 or 24 bps, so 2024, 2025, and 2026 remained unopened. The project first place and live-order permission are unchanged.

## Mechanism and causal contract

Predetermined UTC-aligned 8-hour or 24-hour session VWAP is treated as current-session volume-weighted inventory cost. Completed-bar excursions outside 1.5/2.0 dispersion bands are routed to continuation after two or three outside closes, to reversal after early or post-acceptance failure, or to continuation only after the first accepted-band retest and rejection. Directional efficiency, VWAP slope, and optional 52/48 taker-buy-share alignment are causal filters.

The final run opens only checksum-identified 2023 Binance USD-M five-minute BTCUSDT, ETHUSDT, SOLUSDT, and XRPUSDT data. Entries occur at the next five-minute open. Same-bar stop/target ambiguity is adverse; gap stops fill at the worse open. One global slot, 0.5% planned NAV risk including entry/stop costs, a 5x notional cap, and 12/18/24-bps identical-path replay apply. No elapsed-time or session-boundary forced exit is used.

This is distinct from the prior-session volume-profile result: it uses only current-session cumulative inventory cost and weighted dispersion, not historical volume-at-price. It also uses no trade-tape episodes, liquidation labels, impact thresholds, or displayed-book queues.

## Results

The primary 384-policy screen had zero positive continuation or reversal policies at 12 and 24 bps. Best primary policy `4bf78f4ec24e8e59cc7b` was an 8-hour post-acceptance reversal: 32 trades, 12-bps daily growth -0.0089765%, 24-bps daily growth -0.0170135%, 24-bps PF 0.2782, trade-close MDD 6.7174%, median trade -33.98 bps, both half-years negative, and top-10%-winner-removed return -7.4439%.

The best immediate continuation policy made 390 trades but lost 0.129301% geometrically per day at 24 bps and lost 54.94% after top-winner removal.

The materially different accepted-band-retest follow-up tested 192 policies. Zero was positive. Best policy `70a5f7c27bdd1fb59cde` made 474 trades but recorded 24-bps daily growth -0.295705%, total return -66.07%, PF 0.3642, trade-close MDD 66.16%, median trade -50 bps, and top-10%-removed return -75.48%.

Filters reduced trade count but did not create expectancy. Exact intratrade MDD, historical funding, Bybit replay, risk/leverage optimization, and later periods were not opened because all three state families failed the fatal economic screen.

## Reproduction

```bash
python research/vwap_acceptance_20260726/reconstruct.py
python -m pip install numpy pandas pytest
export VWAP_SNAPSHOT=/path/to/2023_snapshot
export VWAP_OUTPUT=/path/to/primary_output
python research/vwap_acceptance_20260726/vwap_acceptance_screen.py
export VWAP_PULLBACK_OUTPUT=/path/to/pullback_output
python research/vwap_acceptance_20260726/vwap_pullback_screen.py
pytest -q research/vwap_acceptance_20260726/tests
```

The reconstructed package contains the two screen implementations and five causality/execution tests. Local tests passed before publication.
