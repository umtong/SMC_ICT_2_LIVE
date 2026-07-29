# YT Trinity liquidity-efficiency checklist semantic audit

Result: `RES-20260729-YT-TRINITY-CHECKLIST-AUDIT-001`  
Claim: `CLM-20260729-2312-YT-CHECKLIST-AUDIT-001` / issue #416  
Audited system: PR #374, `YT-TRINITY-LIQUIDITY-DELIVERY-ROUTER-ML-V1`  
Verdict: **both programization failure and economic failure**

## Why this audit exists

PR #374 was explicitly derived from the 쉽알남·차트브로·지표센세 corpus and therefore is a direct test of whether the project has translated the SMC/ICT essence into code. Its immutable artifact contains 24,473 deterministic candidates but no base policy positive in both 2023 and restarted 2024H1. This audit does not add another named setup. It compares the code to the source sequence, repairs only demonstrated semantic defects, and checks fixed-small-risk economics before ML.

## Source invariant

Two registered Korean caption sources were re-read rather than relying on strategy labels.

- `gcrJXbmNWFY` (`SRC-YT-INDICATORSENSEI-67ca43300be9`, caption SHA-256 `f41c4a6a...e1f220`): at 31:51–32:59 and 36:33–36:55, the analysis first identifies where liquidity remains and what has already been consumed, classifies high/low resistance, and then follows liquidity → manipulation → FVG/BPR → BPR rebalance entry → low-resistance target.
- `dHZNSbF32eA` (`SRC-YT-CHARTBRO-0e8272d3a2d4`, caption SHA-256 `68a45ea9...612663`): at 03:36–05:43, order flow is defined by the scale of liquidity already acquired and the scale-matched pool being sought. Small same-direction pools are low resistance and should be held through; continuation is external → internal → external until the scale-matched draw is met.

The source does not say that any nearest level satisfying a fixed reward/risk is the target, nor that a previously traded-through pool remains untouched.

## Programization findings

The artifact contains:

- 22,998 `ACCEPTANCE_RETEST` candidates and only 1,475 manipulation/reclaim candidates;
- 8,398 OB-only entries, despite the claimed efficiency/rebalance sequence;
- 16,690 targets whose quality rank is lower than the initiating pool;
- 5,814 auditable previous-day/week targets, of which 1,736 (29.86%) had already traded through before the decision. A discarded preliminary count used incompatible millisecond and nanosecond timestamp units; the correction was made before reporting.

The target selector chooses the nearest level satisfying at least 2R. It neither requires scale matching nor stores target-consumption state, although the narrative calls the result the next untouched external pool.

The entry is also not the stated BPR rebalance. The implementation waits for a completed five-minute rejection/hold bar and then enters at the next one-minute open. This is causal and conservative, but it is a materially different entry.

## Existing post-rejection economics

After requiring a BPR/IFVG, an open auditable target and a scale relationship, the artifact's own cost/funding outcomes remain negative:

| fixed family | final NAV | trades | PF | geometric daily growth |
|---|---:|---:|---:|---:|
| manipulation checklist | 6,095.41 | 227 | 0.461 | -0.04520% |
| low-resistance continuation | 2,508.85 | 683 | 0.562 | -0.12620% |
| union | 1,625.90 | 896 | 0.569 | -0.16576% |

All use 0.5% current-NAV planned loss, a 3x notional cap and one BTC/ETH global slot.

## Causal direct-rebalance correction

To determine whether the late entry caused the failure, the audit reconstructs the confirmation timestamp from the artifact and activates a BPR/IFVG midpoint order 500 ms later. It uses only:

- the event extreme and array boundary known at confirmation for the stop;
- previous-day or previous-week targets still unconsumed at confirmation;
- target importance at least equal to the initiating pool for manipulation;
- a higher-importance target and aligned confirmed order flow for low-resistance continuation;
- first later one-minute observation, adverse same-minute ordering, taker costs and exact signed funding.

No future retest extreme or rejection candle is used.

### Manipulation checklist

| year | eligible | filled | mean R | median R | PF |
|---|---:|---:|---:|---:|---:|
| 2021 | 6 | 6 | +1.4196 | -1.0 | 2.740 |
| 2022 | 17 | 13 | +0.0011 | -1.0 | 1.001 |
| 2023 | 11 | 7 | -1.0000 | -1.0 | 0.000 |

The one-slot account ends at **10,047.80 USDT** after 26 trades, only `0.000435%` geometric growth per day. All positive PnL comes from four winners; the largest single winner supplies the entire apparent edge. Removing it and rerouting the account ends at **9,416.33 USDT**. There are no 2023 winners.

The entry correction therefore identifies a real programization difference and improves the tiny subset, but it does not recover persistent alpha.

### Low-resistance continuation

The corrected first-rebalance route ends at **3,523.25 USDT** over 367 trades, PF 0.429. It is negative in 2021, 2022 and 2023. The transcript's scale-matched holding idea is not represented profitably by this exact candidate construction.

## Verdict

### Programization failure

PR #374 does not preserve scale-matched, still-unconsumed targets and broadens the checklist to OB-only and mostly generic acceptance events. Its post-rejection entry is later than the source's first rebalance entry.

### Economic failure

Repairing target scale/consumption and moving the entry to the first causal rebalance does not create broad, persistent cost-after alpha. The only positive account is 26 trades, completely winner-concentrated, loses every 2023 trade and is more than two thousand times short of the 1% daily-growth reference on the primary growth scale.

The exact PR #374 implementation is retired without ML, threshold, risk or leverage rescue. This result does **not** adjudicate issue #398, which is a distinct active implementation of scale-matched institutional-order-flow continuation.

## Reproduction

```bash
python research/yt_trinity_checklist_audit/audit.py \
  --artifact-root /path/to/yt-trinity-artifact \
  --core-root /path/to/canonical-export \
  --artifact-zip /path/to/artifact.zip \
  --output /tmp/yt-trinity-checklist-audit

pytest -q research/yt_trinity_checklist_audit/test_audit.py
```
