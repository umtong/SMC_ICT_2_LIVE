# Stop-floor and sample-day correction V5C

Status: frozen before any authoritative V5C price or PnL screen.

Claim: `CLM-20260725-1850-XVENUE-001`.

V5B repaired exact local-arrival ordering, funding-boundary exclusion and the frozen symbol-concentration gate. Two remaining defects can still overstate performance, so V5B outputs cannot promote a candidate.

## Defect 1: favorable rebound after a protective-stop breach

The V5B trigger was detected from the adverse executable extremum of a completed 100-ms bucket, but the recorded exit price came only from the first quote after the bucket boundary plus configured latency. A rebound between the breach and that delayed quote could turn an already-triggered stop into an unrealistically favorable exit.

V5C preserves the configured exit latency but prices a protective-stop exit at the adverse of:

1. the executable, capacity-adjusted price at the stop-trigger bucket extremum; and
2. the executable, capacity-adjusted first actual quote after the configured exit-latency boundary.

For a long position this is the lower price; for a short position it is the higher price. Exit-capacity overrun is the logical union of both observations. Drawdown is recomputed with the adverse stop fill. This is conservative and prevents a stopped trade from benefiting from a later rebound.

## Defect 2: omitted zero-trade pilot days

The fixed-notional fatal pilot computed `positive_day_fraction` and median trades per day only from dates containing accepted trades. V5C reindexes both statistics to all four preregistered pilot dates. A date with no accepted trade contributes a zero day and zero trades. All other pilot metrics and fatal thresholds remain unchanged.

## Boundary invariants

The compressed first-quote execution index is exact only because every decision, entry-latency boundary, maximum hold and exit-latency boundary is aligned to the frozen 100-ms grid. V5C fails closed if a decision, configured latency or configured hold is not an integer multiple of 100 ms.

## Unchanged dependencies

Signals, symbols, dates, family definitions, parameter values, fees, impact, top-quote capacity, risk fraction, leverage cap, funding exclusion, source-clock evidence, development gates and sealed 2024/2025/2026 samples are unchanged.

Only V5C or a later explicitly corrected engine may challenge the strategy ranking.
