# Absorption-flow benchmark — revision 7 final checkpoint

This package records one decision-ready strategy result and one completed negative follow-up.

- 216 completed-five-minute absorption/continuation/reversal policies: zero preregistered development survivors.
- 324 prior-volume dollar-clock policies: zero development survivors and no OOS opening.
- exploratory aligned-continuation `33034b092ffd271a`: 0.0227977% geometric daily growth at approximately 15bp round trip and 0.0118956% at approximately 30bp, 184/183 trades, but no sequential OOS opening and a failed yearly robustness gate.
- proposed provisional strategy rank: 1 among currently verified hard-valid results, with incomplete-normalization confidence `MEDIUM_LOW`. PR #25 remains a closer but unverified candidate.

Run `python reconstruct.py`, then compile `reconstructed/src/*.py` and run the reconstructed tests. The economic datasets are registered separately and are not bundled into Git. No order was submitted.
