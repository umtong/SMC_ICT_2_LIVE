# Historical liquidity-void first-reentry Core — final report

## Decision

`RES-20260730-LIQUIDITY-VOID-LIFECYCLE-TAKEOVER-001` is **RETIRED_PRE2024_NEGATIVE_EVEN_ZERO_COST_NO_ML_AUTHORITY**.

The tested logic was not “every FVG fills.” A completed directional five-minute displacement run froze the union of its genuine same-direction FVGs. After at least fifteen untouched minutes, the first later one-minute return authorized traversal only when the close was accepted inside the void, and continuation only when the close rejected outside the proximal edge with the original-direction body. Entry, stop, target and state exit followed that single premise; no elapsed-time close existed.

## Programization audit

Before the authoritative outcome, the evaluator was corrected so that:

- a delayed state-loss exit owns its execution minute instead of using later high/low from that minute to award a target;
- open positions are marked and carried across 2021/2022 rather than strategy-closed at year-end;
- a target/stop observed within a one-minute bar retains the global slot through that minute;
- entry at the exact timestamp of the prior exit is prohibited;
- all compressed outputs have deterministic headers.

Seven focused causal/execution assertions passed. Two fresh end-to-end processes produced all 61 files byte-identically; the common `RESULT.json` SHA-256 is `85e8bb66d8030f32d559cb5d02775fdc3a46756ad284a094da51bb30dababd90`.

## Event surface

- 23,732 grid-qualified action candidates from 3,438 parent displacement runs;
- 19,918 traversal actions and 3,814 continuation actions;
- 13,204 candidate rows entering in 2021 and 10,528 in 2022;
- BTC 12,842 rows and ETH 10,890 rows;
- pooled gross mean `-2.5605 bp`, pooled gross median `-4.8108 bp` before the principal cost.

The broad base grid showed the same failure in both actions. In 2022, traversal gross mean was about `-1.49 bp`; continuation gross mean was about `-5.51 bp`. Neither role labels nor product split produced a broad cost-scale state. Small positive diagnostic cells were sparse and remained negative after 24bp.

## Account results

The best 2022 path at every cost was `m1.5_w0.25_e7 / CONTINUE_ONLY`:

| All-in cost | completed trades | NAV multiple | PF | median account return | H1 | H2 | winner-deleted multiple |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 bp | 239 | 0.951265x | 0.9619 | -0.4427% | +14.13% | -16.65% | 0.751080x |
| 12 bp | 239 | 0.629212x | 0.5352 | -0.4665% | -8.30% | -31.39% | 0.534123x |
| 18 bp | 239 | 0.569051x | 0.4407 | -0.4721% | -13.94% | -33.88% | 0.494316x |
| 24 bp | 239 | 0.529068x | 0.3739 | -0.4761% | -17.78% | -35.65% | 0.467770x |

At 24bp, the best traversal-only path ended `0.047871x`; the best full-map path ended `0.026587x`. All eight formation grids failed. No 2022 24bp path had both >=60 completed trades and nonnegative mean, so the preregistered Ridge/HGBT take-flat comparison was not opened. Calendar 2023 and official 2024–2026 remained sealed.

## Failure lesson

The implementation did preserve the intended SMC/ICT distinction between acceptance and rejection. What failed was the economic premise that an aged historical imbalance remains a live payer state. The void identifies where price previously repriced quickly, but not who still holds defended inventory, whether fresh sponsorship remains, or whether current aggressive flow can force delivery. Adding another FVG width, role filter, model, session or leverage would select historical subsets rather than repair that missing cause.

Do not rescue this exact family. The next Core must observe current sponsored or vulnerable inventory/forced flow at the interaction itself, and must show cost-scale raw action separation before ML or sizing.
