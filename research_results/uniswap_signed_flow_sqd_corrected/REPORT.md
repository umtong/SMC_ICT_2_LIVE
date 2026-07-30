# Signed Uniswap WETH–stablecoin flow — final corrected decision

- Claim: `CLM-20260730-UNISWAP-SIGNED-FLOW-SQD-TAKEOVER-001`
- Result: `RES-20260730-UNISWAP-SIGNED-FLOW-SQD-CORRECTED-001`
- Status: `RETIRED_PRE2024_CONFIRMATION_GATE_FAILURE_AFTER_PROGRAMIZATION_CORRECTION`

## Economic question

Does a large, directionally imbalanced, causally available five-minute signed WETH inventory transfer across the four canonical Uniswap V3 WETH–USDC/USDT 500/3000 pools predict a cost-surviving ETHUSDT action toward the nearest still-unconsumed causal 15-minute structural pool?

## Source authority

The source gate passed before market outcomes were opened. Finalized full history decoded 2,099,482 swaps in 2021-05-05 through year-end, 4,184,012 in 2022 and 3,650,145 in 2023, with zero duplicate identities and zero decode errors.

The fit-only notional event boundary was 24,313,142.23 stablecoin units. It yielded 26 source buckets and 21 structurally eligible actions: 16 fit, one calibration, four untouched 2023H1 confirmation and no development rows.

## Programization audit

Before interpreting economics, the final v6 corrected transaction-level concentration, pivot activation order, target consumption during latency, future executable-price leakage, actual-entry risk geometry, funding-time position value, pre-market/missing-price funding handling, finite-source terminal marking, the undeclared minimum-fit gate, development gates and deterministic artifact identity.

Nineteen focused tests passed. Two fresh complete executions produced byte-identical final outputs.

## Untouched 2023H1 confirmation

Prediction:

- model AUC: 0.50
- structural-distance baseline AUC: 1.00
- Brier skill: -0.5054

At 18 bp:

- NAV: 10,000 → 9,933.07
- trades: 4
- PF: 0.556
- median trade: -0.5005%
- winner-deleted/full-rerouted NAV: 9,850.13

At 24 bp:

- NAV: 10,000 → 9,930.20
- trades: 4
- PF: 0.537
- median trade: -0.5004%
- winner-deleted/full-rerouted NAV: 9,850.19

## Decision

The actual signed-inventory source is valid and economically distinct, but this exact standalone trigger/payoff is sparse, baseline-inferior and negative after realistic cost. It is retired before 2023H2 development and before official 2024–2026.

This does not prove signed flow has no information. It proves that `large five-minute signed flow → nearest causal 15-minute first passage` is not a repeatable Core. Signed flow may only be useful as one state sensor inside a materially different liquidity-consumption / acceptance-rejection policy. The retired threshold, pool set, bucket, feature set, model, label, cost, risk and leverage may not be retuned after this outcome.

No ranking or live-permission change. No credentials or orders.
