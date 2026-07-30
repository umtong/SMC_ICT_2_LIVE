# Minimal repeated prior-day liquidity survival Core — final report

## Decision

`RES-20260730-MINIMAL-REPEATED-LEVEL-CORE-001` is **`RETIRED_PRE2024_SPARSE_MODEL_ONLY_EDGE_NOT_CORE`**.

The exact information unit is retired before calendar 2023. Calendar 2023 and the official 2024-2026 interval were not opened. No risk, leverage, threshold, geometry, model or SMC-checklist rescue is authorized.

## Research basis

This study operationalizes the four registered project sources as one research contract:

- market logic precedes indicators and pattern names;
- a liquidity interaction starts competing acceptance and rejection hypotheses rather than prescribing reversal;
- ML predicts direct action value and may choose flat;
- fixed small risk separates alpha from position-size amplification;
- Core breadth and Expansion tails are diagnosed separately;
- a negative or sparse base policy is retired rather than rescued by filters or leverage.

## Frozen mechanism

The previous completed UTC-day high and low are frozen for the immediately following day. A completed 15-minute interaction can be the first touch or a causally rearmed later touch. Rearming requires at least four completed 15-minute bars and a retreat of at least half the structural scale established before the new interaction bar.

At the same executable entry, two symmetric counterfactual actions compete:

- `BREAK`: trade through the level toward one structural scale beyond it;
- `REJECT`: trade back through the level toward one structural scale inside it.

The structural scale is one quarter of the previous-day range. Fixed latency is 500 ms, execution is the first strictly later observed one-minute open, costs are 12/18/24 bp plus actual signed funding, risk is 0.5% of current NAV, notional is capped at 3x, and the account has one global pending/open slot. There is no elapsed-time or scheduled strategy close.

## Programization audit

Two material semantic defects were found before the final result was accepted:

1. A wide 15-minute bar could both establish the required inside retreat and trigger a new interaction, although the intrabar order was unknown. Rearming now requires evidence from a prior completed bar.
2. The current interaction penetration was included in both current and prior-history features. Prior penetration and rejection now end strictly before the current event.

Completed OI/account-ratio changes were also aligned from the latest causally available five-minute observations. The final strict JSON output excludes non-standard infinity values.

## Event inventory

- 2021 events: **1,107**
- 2022 events: **1,256**
- total action outcomes: **4,410**
- 2022 touch distribution: touch 1 = 703, touch 2 = 344, touch 3 = 140, touch 4 = 50, touch 5 = 13, touch 6 = 6

The event family was not sparse. The failure occurred in the economic action distribution and the model's useful breadth.

## Deterministic 2022 economics

| Policy | Cost | Trades | NAV multiple | PF | Median trade | MDD |
|---|---:|---:|---:|---:|---:|---:|
| Always BREAK | 12 bp | 687 | 0.69257x | 0.796 | -0.480% | 32.58% |
| Always BREAK | 24 bp | 687 | 0.49595x | 0.608 | -0.492% | 50.62% |
| Always REJECT | 12 bp | 687 | 0.53638x | 0.635 | -0.022% | 46.49% |
| Always REJECT | 24 bp | 687 | 0.40719x | 0.476 | -0.072% | 59.28% |

Both unconditional actions are deeply negative. Repeated level interaction is not itself a Core signal.

## ML direct-action-value result

The pooled HGBT was fit on 2,056 resolved 2021 actions and scored 2,354 resolved 2022 actions.

- model MAE: **0.00388622**
- action-specific constant MAE: **0.00393476**
- relative MAE improvement: **1.23%**
- model MSE improvement versus constant: **0.23%**
- prediction/return Spearman: **0.0406**
- positive action predictions: **40 / 2354 (1.70%)**

The model was only marginally better than an action-specific constant and had almost no ranking skill. It avoided most losing actions rather than learning a broad positive policy.

| Cost | Completed trades | NAV multiple | PF | Median trade | MDD | Slot occupancy |
|---:|---:|---:|---:|---:|---:|---:|
| 12 bp | 32 | 1.027071x | 1.490 | 0.236% | 1.14% | 1.41% |
| 18 bp | 32 | 1.020731x | 1.374 | 0.226% | 1.18% | 1.41% |
| 24 bp | 32 | 1.015002x | 1.270 | 0.205% | 1.30% | 1.41% |

The 24-bp point estimate corresponds to approximately **0.004080% per calendar day during 2022**, but this is not a credible Core:

- only **32** completed trades, below the frozen 100-trade gate;
- top-five positive-PnL share **43.59%**;
- removing the two largest positive event keys and rerouting leaves only **1.000721x**, PF **1.017**;
- monthly-block bootstrap q05 multiple **0.99006x**;
- event bootstrap q05 multiple **0.97530x**.

The lower-tail diagnostics were not used for selection. They show that the weak positive point estimate is not stable enough to justify opening another year.

## Future-information upper bound

The same event/action tape has a large ex-post oracle upper bound at 24 bp: **7.295x** over **635** trades with only **4.08%** top-five concentration.

This does not validate a strategy. It shows that BREAK versus REJECT outcomes are separable after the fact, while the causally available 15-minute price/OI/account features do not identify that separation with useful breadth. More model complexity would be a model rescue of a negative base family. A future revisit would require genuinely new contemporaneous information such as exact aggressive-flow/absorption data, not a threshold or hyperparameter change.

## Gate and final decision

The frozen 2022 gate passed point-return, PF, median and exact winner-removal conditions but failed useful breadth:

- minimum 100 completed model trades: **false**
- completed model trades: **32**
- 2023 opened: **false**
- official 2024-2026 opened: **false**

The exact family is retired as **sparse model-only edge, not Core**. It does not challenge the ranking and receives no risk/leverage research.

## Reproduction

```bash
python run.py --root <canonical_core_export> --output <output_dir> --end-year 2022
```

Two independent full runs produced byte-identical full `RESULT.json`, predictions and both trade ledgers, and semantically identical event/action frames. See `VALIDATION_ATTESTATION.json` for hashes.

No credentials, paper orders, testnet orders or live orders were used.
