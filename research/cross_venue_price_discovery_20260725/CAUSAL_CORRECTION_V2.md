# Causal correction V2

The first source-probe and pilot implementations are **hard-invalid before any economic result may be used**.

## Defects found by adversarial review

1. Tardis normalized files are delivered in local-arrival order. Exchange timestamps describe source-event time, but a live strategy cannot use an event until `local_timestamp`. V1 bucketed by exchange timestamp.
2. A 100 ms bucket aggregates all events inside that bucket. V1 treated the bucket start as decision time rather than the bucket end, allowing up to 100 ms of unavailable information.
3. V1 sorted events globally by score before time. That could let a later high-score event consume the global slot before an earlier event and is not a causal portfolio path.

## V2 contract

- All event sequencing and feature buckets use `local_timestamp`.
- Exchange timestamp is retained only for latency and staleness diagnostics.
- A bucket `[t, t+100ms)` becomes available at `t+100ms`.
- Entry occurs at the first actual Binance quote with local arrival time at or after decision availability plus registered latency.
- Events are processed chronologically; score is used only to break ties at the same decision time.
- No V1 source-probe or PnL output is admissible in Result Registry, ranking or strategy selection.
- Parameters, economic families, systematic sample days, fees and gates are unchanged.
