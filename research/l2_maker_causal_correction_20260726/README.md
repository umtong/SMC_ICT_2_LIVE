# L2 maker V4 causal correction

This directory continues the expired `CLM-20260725-1958-L2-MAKER-001` scope. It is a corrective replay, not a new alpha family or parameter search.

## Why the reported V4 output cannot be registered as hard-valid

The successful V4 workflow artifact is economically negative, but independent inspection found four implementation defects:

1. `route_mask()` used `valid_order`, which is known only after the 100 ms acknowledgement. This screened signals and global-slot competition with future quote persistence.
2. ACK-rejected post-only submissions were treated like live orders through the full TTL rather than releasing the slot at acknowledgement.
3. A finite fill with an unavailable sampled exit quote could disappear from the ledger because a trade was recorded only when both fill and gross return were finite.
4. maximum drawdown was stored as the negative minimum of a signed drawdown series rather than a positive loss magnitude.

The immutable artifact contains 276,352 stored decision rows, the exact V4 source and SHA-256 manifests, so no market data need be reopened.

## Frozen correction contract

- Reuse GitHub Actions artifact `8621485991`, SHA-256 `ebd885b469c0391a5d164c8a6e540f5958ac34b39ee03a1e5a54748a7e6a1b46`.
- Preserve every date, symbol, feature, model, queue multiplier, TTL, horizon, route, score quantile, cost and stage gate.
- Form route eligibility from decision-time BBO/depth freshness and spread only.
- Treat `valid_order` solely as the later ACK outcome.
- Release an ACK-rejected order at ACK time; retain the original TTL for accepted but unfilled orders.
- Keep a filled order busy through its exit horizon. If its exit cannot be valued, mark the candidate execution path invalid and prohibit stage advancement.
- Report MDD as a positive magnitude.
- Open no additional date or order path.

`run_correction.py` verifies the entire original artifact manifest, runs adversarial self-tests, replays all 648 frozen candidates, writes the corrected candidate table and emits a decision-ready JSON result with a new SHA-256 manifest.
