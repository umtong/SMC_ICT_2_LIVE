# ML protected-order-flow terminal failure V1

`RES-20260729-ML-PROTECTED-FLOW-FAILURE-001` is a pre-2024 retired result for Work Claim #421. It is distinct from active continuation issue #398: this route acts only after a scale-matched external objective is consumed and the protected internal order-flow origin fails.

The complete source, tests, contract, evidence summaries and full result are stored in the split deterministic payload. Run `python materialize.py`, then `python -m unittest -v test_protected_flow_failure.py`. The reproduced pipeline is `run_all.sh <canonical_core_root> <output_dir>`.

At 24 bp, the 2022-selected route made +2.94%, but exact top-10%-winner deletion with global-slot rerouting made -9.33%, and the unchanged 2023 route made -6.05%. The 2021 chronological ML diagnostic was worse than a constant baseline. The family therefore did not open the official 2024 interval and does not change the ranking.
