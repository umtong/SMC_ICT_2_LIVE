# Repeated 500ms absorption-cluster rotation Core

**Result:** `RES-20260730-BYBIT-REPEATED-ABSORPTION-ROTATION-001`  
**Decision:** `RETIRED_REPEATED_ABSORPTION_ROTATION_SPARSE_FAILURE`

## Question

The single-breach 500ms replenishment route failed because its executable target was smaller than realistic cost. This study asked a different inventory question: if the same frozen two-hour outer boundary is attacked three times by abnormal aggressive flow, each attack closes back inside, and the market completes an inside one-minute rearm between attempts, does the third failure reveal durable passive replenishment and a rotation toward the frozen midpoint?

## Frozen contract

The first attempt froze the prior completed two-hour observed-trade high/low and midpoint. A valid attempt required breach-direction five-second turnover z>=2 and a completed five-second close back inside the same boundary. Three distinct attempts had to finish within 30 minutes. After the third attempt, the action faded the boundary after fixed 500ms at the first later observed 500ms bucket. The stop was one tick beyond the maximum causal cluster excursion and the target the frozen midpoint. A completed one-minute close beyond the cluster extreme was strategy state loss. There was no elapsed-time exit.

## Programization audit

Synthetic tests established four required invariants:

1. three high-side attacks with completed-minute rearms create exactly one short event;
2. the low-side path is symmetric;
3. no completed-minute rearm creates no event;
4. a third attack outside the 30-minute cluster window cannot complete the old state.

The real event funnel independently counted every first, second and third attempt, expiry and not-rearmed block.

| Stage | First attempts | Second attempts | Third attempts | Expired after one | Expired after two | Not rearmed |
|---|---:|---:|---:|---:|---:|---:|
| Jan-Feb fit | 115 | 4 | 1 | 112 | 2 | 226 |
| Mar-Apr development | 213 | 10 | 0 | 203 | 10 | 338 |
| May-Jun confirmation | 253 | 14 | 1 | 240 | 12 | 594 |

The two completed clusters were high-side events lasting 630 seconds in fit and 405 seconds in confirmation. The absence of development events is therefore genuine scarcity, not a hidden generator bug.

## Economic result

Development contained zero actions. Unchanged confirmation contained one short action. It stopped after 1.25 minutes for the planned 0.5% NAV loss. The cost grid did not alter the account result because the structural sizing denominator absorbed each fixed cost path and the trade reached its hard stop.

One event cannot establish a repeatable expectation. It also cannot support ML, winner-deletion inference, risk optimization or an official-period opening.

## Decision

The exact repeated-absorption cluster is retired as structurally too sparse. Do not rescue it by reducing the required attempt count, lengthening the cluster window, changing the boundary scale, target, stop, flow threshold, model, risk or leverage after observing the funnel.

The research lesson is specific: durable repeated replenishment may be economically meaningful, but the frozen three-attempt/30-minute state does not occur often enough to serve as the missing day-trading Core. The next route must change the information source rather than loosen this event into a different hypothesis.

No credentials, paper orders, testnet orders or live orders were used.
