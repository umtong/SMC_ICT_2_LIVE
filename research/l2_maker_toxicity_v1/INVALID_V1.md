# L2 maker toxicity V1 — hard invalidation

The first transport implementation is not valid evidence even if an Actions artifact exists.

The defects were identified before usable discovery or validation PnL was accepted:

1. a state containing all events in second `s` could be acted on at the start of `s` rather than the next boundary;
2. candidate arbitration could condition on eventual fill outcome;
3. an unfilled selected order did not occupy the global pending slot through TTL;
4. the passive price could be repriced at acknowledgement rather than fixed at decision;
5. official BBO freshness allowed an excessive gap;
6. rolling features could condition on the existence of depth updates rather than an exact-second clock;
7. mixed microsecond/millisecond timestamps were not normalized row-wise;
8. sequence continuity could compare updates across a new snapshot boundary;
9. visible queue state was not represented in the fill model; and
10. the same market window was replayed separately for every queue/TTL/horizon combination.

V2 fixes these defects, uses 15 passing regression tests, and reconstructs exact sources from SHA-256-locked gzip/base64 parts. Only V2 outputs may be considered.
