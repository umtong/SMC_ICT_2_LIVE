# Exact Bybit 96/48 all-breakout Core audit

**Claim:** `CLM-20260730-BYBIT-CHANNEL-ALLBREAKOUT-CORE-001`  
**Result:** `RES-20260730-BYBIT-CHANNEL-ALLBREAKOUT-CORE-001`  
**Verdict:** `RETIRED_ALL_BREAKOUT_CORE_FAILURE`

## Decision

The unfiltered exact-Bybit 96-hour breakout / opposite-48-hour channel route is **not** a frequent, cost-surviving Core engine. It was weakly positive in each pre-2024 year, but the unchanged continuous 2024-01-01 through 2026-06-30 path lost at 18bp and 24bp. Exact deletion of the largest 10% positive event keys before a full global-slot reroute made every cost path materially negative.

The positive channel results retained elsewhere in the project therefore come from selecting a minority of Expansion tails rather than from a broadly profitable channel event.

## Frozen route

- Bybit USDT-linear `BTCUSDT` and `ETHUSDT`;
- completed 60-minute close outside the prior 96 completed hours;
- fixed 500ms activation and first later observable one-minute open;
- 2 completed-state ATR20 structural stop from actual entry;
- completed close through the opposite prior-48-hour channel, then first later observable one-minute exit;
- actual signed Bybit funding;
- one global pending/open slot;
- fixed 0.5% current-NAV planned loss and 3x notional cap;
- 13/18/24bp cost paths;
- no elapsed-time, scheduled or stage-boundary strategy close;
- no model, threshold, symbol, side, session, channel, ATR, risk or leverage selection.

## Event and programization parity

The exact event generator reproduced 2,855 candidates:

| Period | Candidates |
|---|---:|
| 2021 | 538 |
| 2022 | 511 |
| 2023 | 369 |
| 2024 | 578 |
| 2025 | 598 |
| 2026H1 | 261 |

Canonical source hashes, the pinned event generator, deterministic source bundle and six focused semantic tests passed. A notebook-only default output directory side effect in the imported audit module was suppressed without changing event, trade or account logic. The final GitHub Actions run completed the exact account replay and all assertions.

## Pre-2024 mechanism diagnostic

The fixed 24bp route was weakly positive in all three pre-2024 years:

| Year | Final NAV | Return | Trades | PF |
|---|---:|---:|---:|---:|
| 2021 | 10,150.51 | +1.51% | 92 | 1.0413 |
| 2022 | 10,068.50 | +0.69% | 87 | 1.0216 |
| 2023 | 10,242.08 | +2.42% | 88 | 1.0651 |

This justified a frozen full-path audit, but the margins were too small to establish durable Core economics.

## Continuous official account

| Cost | Final NAV | Daily geometric growth | Return | Trades | PF | MDD | Median trade |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 13bp | 10,286.82 | +0.003101% | +2.87% | 247 | 1.0303 | 18.87% | -0.4923% |
| 18bp | 9,878.25 | -0.001343% | -1.22% | 247 | 0.9869 | 20.22% | -0.4926% |
| 24bp | 9,442.76 | -0.006287% | -5.57% | 247 | 0.9390 | 21.69% | -0.4929% |

At 18bp, half-year returns were:

- 2024H1: +0.11%
- 2024H2: +1.97%
- 2025H1: -10.10%
- 2025H2: +11.52%
- 2026H1: -3.47%

The path completed 175 stops and 72 channel exits. Median holding time was 23.7 hours, mean holding time 51.6 hours, and the global slot was occupied 58.24% of the official period. BTC lost 1,425.39 USDT at 18bp while ETH made 1,303.64 USDT; removing BTC after seeing the outcome is not authorized.

## Few-winner dependence

At 18bp only 49 of 247 trades were positive and 198 were negative. Removing the 25 largest positive event keys before fully rerouting the slot produced:

| Cost | Final NAV | Trades | PF | MDD |
|---:|---:|---:|---:|---:|
| 13bp | 7,924.06 | 258 | 0.7690 | 34.99% |
| 18bp | 7,667.05 | 258 | 0.7369 | 36.46% |
| 24bp | 7,390.38 | 258 | 0.7012 | 38.05% |

The 24bp winner-deleted path grew **-0.033153% per UTC day**. This is not a steady-compounding Core distribution.

## Interpretation for the project

The result distinguishes two statements:

1. A high-volume or ML-selected subset of channel breakouts may contain Expansion value.
2. The underlying all-breakout event is not itself a persistent Core alpha.

The second statement is now rejected by exact full-path evidence. More risk or leverage would only magnify a weak, regime-sensitive and winner-dependent base distribution. Do not retune channel length, stop width, exit channel, symbol/side, session, model score, risk or leverage using official outcomes.

## Reproduction

- GitHub PR: `#479`
- Successful workflow run: `30512063911`
- Workflow artifact: `8747482602`
- Artifact ZIP SHA-256: `65eed083cf749a3f48a46f1928a2cce19d8425051a98a481a42d55b0a9a14a22`
- Full artifact includes candidate inventory, all ordinary and winner-deleted trade ledgers, daily NAV files, source manifests, contract and run log.
- Drive `08_RESULT_REGISTRY`: row 96

No credentials, paper orders or live orders were used. Ranking and live permission are unchanged.
