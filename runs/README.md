# Run reports

Each peer worker produces an append-only report named:

`RUN__<worker_id>__<claim_id>__<timestamp>.md`

A Run Report records the base revision, objective/scope/dependency fingerprints, reused sources/data/results/validation, work completed, changed-surface validation, metrics, failures, artifacts, branch/commit/PR, claim disposition, and next exact action.

A worker may apply the report's state patch after re-reading the latest revision and reconciling concurrent changes. Otherwise the complete patch remains available for any later worker to integrate. No coordinator is required.