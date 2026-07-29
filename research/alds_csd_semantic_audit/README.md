# ALDS exact-CSD semantic, selection and execution audit

Result: `RES-20260729-ALDS-CSD-SEMANTIC-AUDIT-001`  
Claim: `CLM-20260729-2243-ALDS-CSD-AUDIT-001` / issue #408  
Audited system: PR #378, `ALDS-CSD-DELIVERY-GPT56-V1`  
Verdict: **both programization failure and economic failure**

## Question

PR #378 is one of the project paths closest to the stated SMC/ICT narrative: determine the higher-timeframe draw first, identify an exact change in state of delivery (CSD), wait for the first causal retest, invalidate at protected structure, and deliver toward causally known external liquidity. This audit asks whether its weak official path came from the trading thesis or from the way the thesis, stage selection and account routing were programmed.

The audit consumes the completed immutable workflow artifact `8712038780` and its `ALL_LABELED.pkl`; it does not reacquire or re-clean market data and does not modify PR #378.

## Selection defect

The claimed chronology was 2021 context, 2022 development and gate selection, then independent 2023 validation. The recorded winner does not satisfy that sequence:

| route | 2022 fills | 2022 sum R | 2022 H1 | 2022 H2 | stable | 2023 fills | 2023 sum R | 2023 top-5 share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| published `SRR_terminal` | 4 | -0.3690 | -0.0478 | -0.3212 | 0 | 3 | +3.6082 | 100% |

The combined objective used the three 2023 winners to make this route the headline winner even though development was negative in both halves and the route's own stability flag was zero.

This was not an isolated borderline decision:

- HGB gate routes: 948; stable routes: **0**.
- Logistic gate routes: 948; stable routes: **0**.
- Only two HGB rows were positive in both 2022 halves with at least 20 fills; they are duplicate `DPC`/`DPC_strict` representations of the same economics.
- That development route made +8.0877R over 144 fills in 2022, then lost **-59.5777R** over 136 fills in 2023, with both 2023 halves negative.

Therefore no enumerated route passed the stated development-then-independent-validation contract. The later 2024-2026 replay is causally dated before each trade, but it is a diagnostic of a gate-bypassed route—not evidence of a validated strategy.

## Semantic fixed-rule audit

Unlike the prior Swipalnam implementation, the published selected ALDS rows generally do use delayed CSD confirmation and external targets. The principal programization problem is stage selection rather than invented FVG/OB geometry. To separate this from the economic thesis, the audit freezes readable semantic invariants without model scores:

### DPC continuation

- `pullback_sweep` trigger and finite pullback depth;
- CSD body close before a later retest; no same-bar confirmation;
- higher-timeframe state agreement;
- target is a strictly more important causally known external node;
- at least 2R terminal geometry.

### SRR terminal reversal

- CSD body close before a later retest;
- terminal state transition;
- event-node importance at least 3;
- target is a strictly more important causally known external node;
- at least 2R terminal geometry.

## Event economics after recorded costs and signed funding

| year | strict fills | mean R | median R | PF | sum R |
|---|---:|---:|---:|---:|---:|
| 2021 | 382 | -0.3162 | -1.0553 | 0.595 | -120.8041 |
| 2022 | 527 | -0.2441 | -1.0699 | 0.696 | -128.6361 |
| 2023 | 391 | -0.4634 | -1.0983 | 0.457 | -181.1790 |

DPC is negative in every year. SRR is only slightly positive in 2022 (+1.1512R over 27 fills) but negative in 2021 and 2023; its top-five positive-PnL shares are 94.91%, 77.58% and 93.29%, respectively. There is no stable semantic core for ML to rank.

## Fixed-small-risk global-slot account

The strict DPC+SRR union is replayed chronologically with one pending/open slot across BTC and ETH, current-NAV 0.5% planned risk and a 3x notional cap. Unfilled orders occupy the slot until their recorded structural resolution. `net_r` already contains the artifact's execution costs and signed funding.

- start NAV: 10,000 USDT
- end NAV: **1,522.40 USDT**
- account multiple: 0.1522x
- geometric daily growth: **-0.171752%**
- completed trades: 1,114
- profit factor: 0.6170
- realized-NAV drawdown: 85.30%
- top-five positive-PnL share: 12.32%

Exact UTC intratrade marking is unnecessary for the fatal decision because the event-level expectancy is already negative in every calendar year. The account curve is included only to prove that global-slot routing and small risk do not rescue the family.

## Funding and execution observations

- The artifact records nonzero signed funding on 124/181/154 filled events in 2021/2022/2023. Funding omission is not the cause of failure.
- Every selected order activates at decision time plus 500 ms.
- The published gate excludes same-bar CSD confirmation. Its selected fills occur after later observable bars.
- The official diagnostic completes only one trade across 2024-2026, ending at 10,183.94 USDT and 0.0019986% daily growth, with 100% top-five profit share. It is about 500 times short of the 1% reference and has no breadth.

## Root-cause verdict

### Programization failure

The evaluator picked a route despite `stable=0` and negative development in both halves because the nominally independent 2023 result entered the selection objective. It also proceeded to the official diagnostic even though no enumerated route passed its own stability contract. This conflates selection and validation and makes three 2023 winners determine the route.

### Economic failure

Repairing the stage boundary and removing model selection does not reveal alpha. The readable DPC and SRR contracts have negative after-cost expectancy, negative medians, PF below one in the aggregate and a severely declining fixed-small-risk account. The exact implementation should not be rescued with thresholds, validation-aware selection, risk, leverage or later-period retuning.

This result does **not** claim that every possible CSD or SMC/ICT implementation is false. It retires the exact ALDS information construction and selection path represented by PR #378.

## Reproduction

```bash
python research/alds_csd_semantic_audit/audit.py \
  --artifact-root /path/to/alds-csd-delivery-gpt56 \
  --artifact-zip /path/to/alds-csd-delivery-artifact.zip \
  --output /tmp/alds-csd-audit

pytest -q research/alds_csd_semantic_audit/test_audit.py
```

The tests lock delayed-CSD semantics, terminal-reversal state transition, pending-order global-slot occupancy and current-NAV risk sizing.
