# RES-20260726-INVENTORY-MAP-001 — fatal screen result

## Decision

**TESTED_BELOW_GATE; exact dependency retired.** The frozen causal vulnerable-inventory pressure-map screen passed initial hard-validity checks but produced zero development-gate survivors and zero positive candidates at 12, 18, or 24 bp.

## What was tested

- 1,296 frozen cells.
- Bybit BTCUSDT/ETHUSDT public trades, executable quotes, and derivative ticker/OI.
- 36 SHA-verified first-day 2023 source files.
- Fit: 2023-01-01, 03-01, 05-01.
- Development: 2023-07-01, 09-01, 11-01.
- One global slot; causal 100/500 ms executable BBO.
- Three state families: cluster attraction, OI-contraction cascade follow-through, and post-depletion reversal.
- Observed spread plus 12/18/24 bp additional all-in round-trip cost stress.
- 2024-2026 remained sealed.

## Decisive economics

- Gate passes: **0 / 1,296**.
- Positive candidates: **0** at 12 bp, **0** at 18 bp, **0** at 24 bp.
- Nonzero-trade cells: **666**.
- Cells with at least 40 trades: **420**.
- In the at-least-40-trade population:
  - maximum mean gross markout: **1.876582 bp**;
  - maximum direction accuracy: **55.208333%**;
  - best 12 bp total return: **-5.717669%**;
  - best 18 bp total return: **-8.178131%**;
  - best 24 bp total return: **-10.575806%**.
- Cascade follow-through generated at most five accepted development trades per cell.
- Depletion reversal generated no accepted development trades.
- Only cluster attraction was adequately sampled, and every adequately sampled cell was economically negative.

## Reporting audit

The frozen `RESULT.json` selected a zero-trade cell as `best_candidate` because zero return ranked above every negative-return active cell. This is only a reporting-order artifact. It does not affect the preregistered gate, positive-candidate counts, causal validity, or retirement decision. `ACTIVE_CANDIDATE_AUDIT.json` records the best nonzero and adequately sampled cells without changing the frozen implementation or result.

## Reusable evidence

- Scientific head: `b1b0ff9a8971396559abb79b9ce85949db2a6809`.
- Evaluation contract SHA-256: `e3418b47f158f0585ee7c87f717e230c6cf8d79dcaf4c2d3ff16a03652f55fdc`.
- Scientific implementation SHA-256: `ddc5d9c6dd22a27d5f3f86572f5c4b80780396c583f29de44ef1d175fc2bf384`.
- Source manifest SHA-256: `7256997af2a86c2c1f6854451a8e8c69498e14d1be7387bf55836cc4ac668b93`.
- Artifact SHA-256: `570b9204697b6fc5750475b884c9943b882ce7114b9b51302bd80d6079fe4c19`.
- Workflow run: `30184603824`.
- Drive artifact: `14kWaStpt4_bdSK1czaKsnp19b6yrCYhq`.

## Boundary

Retire this exact path-dependent entry-price cohort map, including its frozen OI attribution, pro-rata closure, half-lives, hazard distances, kernels, families, latency and markout contracts. Reopen only with a materially different inventory observation—such as identity-resolved positions or direct liquidation-engine state—and a new preregistered payoff.
