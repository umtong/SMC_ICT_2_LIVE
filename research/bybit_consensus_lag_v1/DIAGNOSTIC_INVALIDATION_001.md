# Diagnostic invalidation: same-message quote groups

The first CI run produced `RES-20260726-BYBIT-CONSENSUS-LAG-UPPERBOUND-001`, zero fit survivors and only ten executable outcome rows. That output is retained as diagnostic evidence but cannot decide the intended family.

The engine already selected the last quote row strictly before each completed bucket boundary, then discarded that state whenever the immediately preceding row shared its `local_timestamp`. This conflicts with the provider contract for reconstructed quotes: CSV row order preserves capture order, and all rows belonging to one received message must be processed before reading the consistent state. At a later bucket boundary the complete group is available, so its final reconstructed BBO row is causal.

V1B removes only this over-exclusion. Exact equal-timestamp entry and exit groups remain adverse. Dates, symbols, venues, 324 candidates, costs, latency, capacity model, stage gates, global slot and sealed official periods do not change. Because candidate PnL was already visible, the amendment records that fact explicitly and prohibits parameter or gate retuning.
