# Absorption-flow benchmark — revision 8 reconciliation

Decision-ready evidence for `RES-20260725-ABS-FLOW-001`.

- 216 completed-five-minute policies: zero preregistered development survivors.
- 324 prior-volume dollar-clock policies: zero development survivors and no OOS opening.
- exploratory aligned-continuation `33034b092ffd271a`: 0.0227977% geometric daily growth at approximately 15bp round trip and 0.0118956% at approximately 30bp, 184/183 trades, but no sequential OOS opening and a failed yearly robustness gate.
- revision-8 provisional rank: second behind verified dynamic-factor state-exit `021fbab613517a31ad98`, which has a smaller target gap. Neither candidate passed its economic gate or permits deployment.

Run `python reconstruct.py`. The 16 checked chunks reconstruct the exact dollar-clock sources and five causal/executor tests. CI fetches the separately hash-registered baseline source from the original claim branch. Large registered market datasets and the full trade ledger remain outside Git. No order was submitted.
