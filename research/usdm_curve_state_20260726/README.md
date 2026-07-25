# USD-M dated-futures curve-state screen

Claim: `CLM-20260726-0522-USDM-CURVE-001`  
Branch: `agent/r11-usdm-curve-state-001`

## Why this information source

The current ranked strategies mostly infer direction from completed perpetual price and flow. This study adds a different state variable: the relative pricing of the perpetual, current-quarter and next-quarter USD-M contracts. A changing curve can reveal leveraged demand, inventory transfer and disagreement across holding horizons before the same state is fully reflected in the perpetual.

This is not a funding-threshold retune. Funding is only an actual cashflow in the account replay. The signal is the completed dated-futures term structure and its interaction with perpetual return and taker flow.

## Causal contract

- Signals use only a completed 15-minute bar and rolling statistics shifted by one bar.
- Entry is the next exact perpetual bar open.
- A missing source bar breaks the rolling segment; no forward fill or time compression is allowed.
- Known quarterly delivery windows are excluded by a deterministic calendar rule fixed before outcomes.
- The global account may have at most one pending/open position.
- Stops use adverse gap handling and stop-first ordering.
- The same trade path is replayed at 12, 18 and 24 bps plus actual funding.

## Staging

1. Download only 2021-2023 official Binance USD-M continuous-contract and funding data.
2. Run all 108 frozen candidates on 2022-2023.
3. Open 2024 only if a candidate passes every registered economic, sample and concentration gate.
4. Keep 2025-2026 sealed.

A failed source probe is not treated as evidence against the hypothesis. A completed negative development screen closes adjacent parameter tuning under the resulting dependency fingerprint.
