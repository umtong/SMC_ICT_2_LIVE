# Institutional order-flow continuation

This directory records `RES-20260730-ML-IOF-CONTINUATION-001` for existing Work Claim #398.

Reconstruct the deterministic evaluator and semantic tests:

```bash
python research/iof_continuation/materialize.py
pytest -q research/iof_continuation/materialized/test_semantics.py
```

Then run against the retained canonical Bybit core-table export:

```bash
python research/iof_continuation/materialized/run.py \
  --data-root /path/to/core_tables \
  --output /tmp/iof_continuation_result
```

The full source hard-cuts data before 2024. The deterministic action family failed at 12/18/24bp in every pre-2024 year, so ML, risk/leverage search and official 2024–2026 remain sealed. No credentials or orders were used.
