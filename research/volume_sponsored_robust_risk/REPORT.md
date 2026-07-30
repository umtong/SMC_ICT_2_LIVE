# Volume-sponsored robust-risk and daytrading-core audit

**Result:** `RES-20260730-BYBIT-VOLUME-SPONSORED-ROBUST-RISK-001`  
**Decision:** robust pre-2024 sizing remains positive, but the information unit is still an **Expansion strategy**, not a repeatable intraday Core. Target not met; ranking unchanged; no live authority.

## Fixed scope

The sponsored-acceptance signal, selected BTC-long/ETH-long/ETH-short sides, 96-hour external boundary, 168-hour volume normalization, threshold `2.2706072565238586`, fixed 500 ms activation, first later one-minute execution, 2ATR20 disaster stop, opposite 48-hour channel exit, exact funding, costs, one global slot and the registered risk/cap grid were unchanged.

The new pre-2024-only selector maximized the deterministic 5th percentile of 4,000 circular 30-day block-bootstrap estimates of mean daily log-NAV growth. It selected **7.5% planned loss with a 12x cap**, rather than the raw-growth-selected 10% path.

## Programization audit

PR #472's source carrier is not self-consistent. Eight execution/account files match their manifest, while `channel_volume_pre2024_risk_select.py` has expected SHA `d203bfb8...` and observed SHA `3078a139...`; the latter is corrupted. The corrupted selection carrier was never executed. The registered grid was reconstructed with the exact matching candidate/replay/account engine.

The audit reproduced 2,855 candidates, exact annual counts, and the base 10%/12x 24-bp official path `12.241463x` over 110 trades. Two complete audit runs were byte-identical.

## Pre-2024 robust selection

- selected risk/cap: `7.5% / 12x`;
- 24-bp 2022-2023 multiple: `44.242155x`;
- geometric daily growth: `0.520484%`;
- bootstrap q05 mean log growth: `0.138583%/day`;
- trades: `87`; PF `1.356`; MDD `55.37%`;
- conservative liquidation guard: pass.

## Continuous 2024-2026

| Cost | NAV multiple | g/day | Trades | PF | Daily MDD | Median trade | Top-5 share | Winner-removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 13 bp | 19.6968x | 0.327339% | 110 | 1.288 | 67.41% | -7.40% | 59.48% | 2.0000x |
| 18 bp | 15.2815x | 0.299421% | 110 | 1.269 | 67.45% | -7.40% | 58.01% | 1.5927x |
| 24 bp | 11.4521x | 0.267701% | 110 | 1.246 | 67.50% | -7.40% | 56.76% | 1.4392x |

## Daytrading and concentration diagnosis

- 110 trades over 912 days: `0.121` trades/day;
- median hold: `42.44` hours;
- same-UTC-day exits: `24/110`; within 24 hours: `41/110`;
- all `57` trades closed within 48 hours lost; aggregate PnL `-338947.73`;
- 67 stop exits produced zero wins;
- all 31 wins came from channel exits with median hold 136 hours;
- positions held over 120 hours generated `94.05%` of positive PnL;
- top 10 winners generated `78.83%` of positive PnL.

The strategy is therefore a multi-day trend Expansion component. Forcing a short exit would remove all observed winners rather than create a Core.

## Reproduction

- workflow run `30512838437`, job `90776370030`;
- artifact `8747761382`, digest `sha256:24dcf78f85131d74c95d3bb4379383ebdfd3ba5ec2d739f7b55fe0dfb70020b1`;
- `RESULT.json` SHA-256 `3956eeb247469d7675edc91c04e0d7f7ac697f6644a2a213eaaf0d25643a4246`;
- three focused tests passed; two full runs byte-identical.

## Decision

- Keep the original 10% path as provisional rank one by target proximity only.
- Preserve the 7.5% path as a more robust sizing diagnostic, not a post-hoc replacement or deployment recommendation.
- Do not describe either as steady-compounding daytrading.
- Do not rescue the signal with time exits, extra leverage, 2026-aware filters or adjacent channel/volume thresholds.
- Search for a distinct intraday Core with positive fixed-small-risk economics and broader time contribution.
