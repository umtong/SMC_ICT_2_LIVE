# RUN-20260725-ATTENTION-LIQUIDITY-001

## Decision

`RES-20260725-001-ATTENTION-LIQUIDITY` is **TESTED_BELOW_GATE**. It does not change the revision-7 strategy ranking and grants no paper/live authority.

## Scope and claim

- Claim: `CLAIM-20260725-001-ATTENTION-LIQUIDITY`
- Original base revision: 3
- Reconciled project revision: 7
- Worker: `gpt-5.6-pro-chat-20260725-1506`
- Result: `RES-20260725-001-ATTENTION-LIQUIDITY`

## Completed mechanisms

| Mechanism | Configurations | Development gate passes |
|---|---:|---:|
| Four-asset attention breakout / trap / absorption-reacceptance | 576 | 0 |
| Attention breadth switch | 96 | 0 |
| State-first hazard and direction separation | 288 | 0 |
| Cross-asset SMT divergence / catch-up | 192 | 0 |
| Native BBO/aggTrade vacuum / absorption / catch-up | 384 | 0 |
| **Total** | **1,536** | **0** |

Validation and sealed confirmation were not opened.

## Causal and execution corrections

1. Funding uses the mark **open** observable at the settlement timestamp. Same-timestamp contract open is the only fallback.
2. Structural target prices are cost-invariant. The first 576-cell run that moved targets with cost is hard-invalid.
3. Completed-bar decisions enter no earlier than the next open; native BBO decisions enter after the completed information interval.
4. Same-bar ambiguity is stop-first, gap stops use the adverse open, and the global position count is at most one.

## Diagnostic finding

- Hazard AUC: `0.759331–0.807847`
- Direction AUC conditional on hazard: `0.544957–0.645932`
- Non-tradable perfect-direction oracle, best weaker-development daily geometric growth at 1% risk: `0.501923%`

Movement opportunity is partly identifiable, but direction and execution economics remain binding. The oracle is not a strategy result.

## Ranking comparison

Current first place remains `FIRST-20260725-HIGH-RESISTANCE-SWEEP-C232AE43`. This result has no development-passing strategy candidate and therefore is not ranked.

## Reuse boundary

The original grid-generation scripts were not retained. The committed preregistrations, amendments, compact evidence, hashes, diagnostics and validator support reuse of the negative result and prevent repeated threshold search, but do not support independent regeneration of every grid row.

## Next exact action

Do not repeat completed-bar attention thresholds. Build event-time liquidation/depth/flow panels and keep continuation and exhaustion as separate causal arms using impact efficiency, depth recovery and opposite-flow reacceptance.
