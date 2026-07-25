# Champion policy

## Definition

Champion is the current best hard-valid strategy or strategy-portfolio candidate available to the project. It is a moving rank pointer to an already registered result, not a statement that the final target has been met or that the strategy is ready for practical use.

## Selection rule

Select a Champion whenever at least one comparable candidate has passed hard validity checks for causality, calculation, data integrity, and execution assumptions. A candidate may be far below the 1% geometric daily-growth target, early in validation, concentrated, or cost-fragile and still be the current Champion if it is the best candidate available.

Use `NONE` only when:

- no comparable candidate has been produced; or
- every available candidate is hard-invalid because of future information, calculation or data error, impossible execution, or another basic validity failure.

Economic gate failure is not hard invalidity. A method-valid but economically weak result is retained as a tested-below-gate result and may remain the current research benchmark until a better candidate exists.

## Operational effect

Champion status has no effect on research priority, validation budget, protection level, or default next-step selection. Work is chosen by expected contribution to the project objective and information value. A completely different market, signal, data source, timeframe, execution method, or portfolio structure should be preferred whenever it offers a stronger path to the objective.

Champion is not a default improvement target. It does not need to be refined, defended, revalidated, copied, or separately backed up merely because it is Champion. Every material result is recorded through the ordinary Result Registry, code commit, data snapshot, and evaluation/cost/execution contract. When the ranking changes, update the Champion pointer; do not repeat preservation work already completed by normal versioning.

Only unrecorded artifacts at risk of being overwritten or deleted require ordinary state-loss protection. That rule applies to all reusable work, not specifically to the Champion.

## Required separation

Champion records separate:

- current relative rank;
- qualification stage;
- target status and target gap;
- data, cost, execution, and evaluation conditions;
- comparison confidence;
- known weaknesses;
- practical-use permission.

A Champion can therefore have `target_status = NOT_MET` and `qualification_stage = EXPLORATORY`.

## Comparison

Every material strategy result is compared with the current Champion as a ranking operation. Prefer normalized comparisons under the same data, cost, execution, and evaluation contract. When full normalization is not possible, retain a provisional Champion and explicitly lower comparison confidence rather than leaving the project without a benchmark.

Rank on account-level net growth together with drawdown, liquidation and tail risk, concentration, sample size, execution sensitivity, and capital efficiency. A single metric does not silently replace the project objective.

The comparison does not determine research priority. After ranking, choose the next work independently from Champion status using target contribution and information value.

## Component leaders

Execution routing, data, feature, or portfolio-construction components may have separate leaders. A positive component result does not become the overall Champion unless it is embedded in a complete strategy or portfolio candidate.

## Current selection at revision 6

Current research Champion:

- ID: `CHAMPION-20260725-HIGH-RESISTANCE-SWEEP-C232AE43`
- source result: `RES-20260725-ALPHA-HYP-001`
- PR: `#10`
- stage: `EXPLORATORY`
- target status: `NOT_MET`

Selection basis: it is the only completed causally valid strategy specification currently recorded with positive growth at its declared base-cost case. This is a rank pointer only and does not allocate research resources to the family.

Critical weaknesses:

- geometric daily growth `0.0024555%`, only `0.24555%` of the 1% target;
- negative return at 18 and 24 bps;
- 55 trades;
- top five positive trades account for 66.92% of positive PnL;
- no sequential selection or confirmation interval opened;
- comparison against other studies is not fully normalized.

Current execution component leader:

- `RES-20260725-1510-L1-EXEC-001`
- positive relative modeled routing improvement through development, validation, and confirmation;
- negative standalone expectancy, so it remains a component leader only.
