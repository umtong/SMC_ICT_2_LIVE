# Run Report — Minimal ML L2 hazard local trigger

현재 1위는 EXPLORATORY 단계의 dynamic state-exit `021fbab613517a31ad98`이며, 실제 펀딩과 12bp 비용 후 일평균 기하성장률은 0.0573077%, 1% 목표 격차는 0.9426923%p/일이다. 현재 하드 유효 후보 중 목표 격차가 가장 작아 1위를 유지하지만 경제적 게이트와 실사용 조건은 충족하지 못했다.

## Claim and decision

- Claim: `CLM-20260726-1734-HAZARD-OCO-ML-001`
- Result: `RES-20260726-ML-L2-HAZARD-LOCAL-TRIGGER-001`
- Hard validity: `PASS`
- Economic status: `FIT_BELOW_GATE`
- Ranking role: `NONE_NOT_RANK_ELIGIBLE_SINGLE_DAY_FATAL_SCREEN`
- Decision: retire the exact completed-100ms top-five L2 absolute-hazard local-trigger dependency without adjacent tuning.

## Trader-readable rule

One HGBT identifies a likely balance-to-imbalance transition from completed top-five Bybit L2 and aggressive-flow state. It does not predict direction. A high score starts one local monitoring state; no exchange entry order rests. The first exact raw Bybit trade crossing the symmetric 4bp upper or lower level reveals delivery direction, after which exactly one marketable order may enter. Same-timestamp two-sided crossings are rejected. The position exits only at its frozen structural target, stop or conservative source-boundary stop.

## Frozen minimal system

- one HGBT;
- eight features;
- one 40bp/30s movement-hazard label;
- one 99th-percentile threshold;
- one 4bp local-trigger mechanism;
- three target/stop cells: 40/20bp, 60/25bp and 80/30bp;
- 100ms and 300ms entry latency;
- one global slot, zero resting entry orders and maximum one exchange entry order;
- 1% planned risk, 3x notional cap, 0.1% prior-three-second traded-notional capacity;
- 12/18/24bp identical paths;
- no directional model, elapsed-time liquidation, risk search or leverage search.

## Causality and corrections

The initial two-live-entry-order representation was hard-invalid under the project one-new-entry-order account contract. Before a valid single-order outcome existed, it was replaced with local monitoring followed by one order after the first exact trade crossing. The runtime state schema contained `decision_us` but not `bin`; a second pre-outcome correction derived the stride from `decision_us // 100000`. Model, features, label, threshold, payoff cells, costs, dates and account risk were unchanged.

## Result

- training rows: 8,550;
- positive labels: 339;
- calibration rows: 3,430;
- HGBT AUC: 0.7507988;
- frozen 30-second volatility baseline AUC: 0.8117586;
- AUC lift: −0.0609597;
- fit-gate survivors: 0;
- untouched 2023 opened: no;
- 2024–2026 opened: no;
- orders submitted: no.

At 18bp:

| Cell | 100ms trades | 100ms return | Median | PF | 300ms return |
|---|---:|---:|---:|---:|---:|
| 40/20bp | 4 | −0.7509% | −38.89bp | 0.00 | −0.7329% |
| 60/25bp | 3 | −0.7231% | −43.76bp | 0.00 | −0.7193% |
| 80/30bp | 1 | −0.4858% | −48.00bp | 0.00 | −0.4858% |

Every 24bp path was more negative. The information target was statistically learnable but inferior to simple recent volatility and could not produce cost-sized payoff under the permitted single-order contract.

## Reproducibility

- workflow: `30197559374`;
- artifact: `8630589328`;
- artifact digest: `sha256:8b260029bb824e8fd879dafbeaf7b28c99d97bf3ce31fe9b2768e1ec5ebc8ff3`;
- result SHA-256: `065dc1ae23324b6f6cf9bd30e2c545a0a7d5238554ab645dba43878987a179cf`;
- fit-paths SHA-256: `37b7e26ed0e5cf0cefefaffb14e8283a2bda4585f2abfaa39935de5c0096a8d6`;
- evaluation contract SHA-256: `48deb555f8d6d46244c73955a25206186704ea74cecb571967f61f4795712c38`;
- corrected runner SHA-256: `46b3ba0f1875ba66c827d3e48c044dabf3108890446fba9e3f0542e4ada3bb0d`.

## Next exact start

Do not reopen this L2 absolute-hazard family through model, feature, threshold, target, stop, latency, risk or leverage changes. Consume the active external-equity intermarket SMT ML result. If it also fails, select only a materially different point-in-time information source whose lead can exceed structural-distance or recent-volatility baselines before account optimization.
