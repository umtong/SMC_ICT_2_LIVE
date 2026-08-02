# VISTA-D

VISTA-D is the current contract-faithful implementation of the inventory-transfer, value-acceptance, price-sponsorship and defended-price scenario.

## Frozen implementation

- Freeze ID: `VISTA-D-IMPLEMENTATION-FREEZE-20260802-001`
- Source aggregate SHA-256: `9c7decf3f74a5987cc22f20b691406bd41561ba6e79cb1ac5b337beacd9a0f8c`
- Frozen source files: 23
- Frozen contract tests: 73/73 passed

## 2024H1 authority

The authoritative frozen-source result is `RES-20260802-VISTA-D-2024H1-FROZEN-BASELINE-001`.

It is an audited deterministic baseline, **not** the completed VISTA-D policy result. The baseline enters every executable contract-faithful candidate whenever the global slot is free; it does not yet implement the skilled trader's `WAIT / ABANDON / WORK_LIMIT` action-value decision.

The earlier 2024H1 artifact ending at 5,751.80 USDT is superseded because its January order prefix does not reproduce from the frozen source fingerprint. The reproducible frozen-source H1 result ends at 4,521.59 USDT.

See the result directory for the audited metrics, diagnostics, provenance finding and next implementation boundary. Large trade, NAV and evidence artifacts remain in the Drive Run Report / immutable evaluation bundle rather than Git.
