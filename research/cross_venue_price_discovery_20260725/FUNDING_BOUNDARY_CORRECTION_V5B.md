# Funding-boundary correction V5B

Status: frozen before any V5B price or PnL screen.

Claim: `CLM-20260725-1850-XVENUE-001`.

V5 corrected local-arrival causality but omitted the inherited rule that prevents a position from crossing an eight-hour funding settlement when the historical funding cashflow is not modeled. V5 output therefore cannot promote a candidate.

V5B changes only this validity boundary:

- Compute the latest possible causal exit from the first executable entry time, maximum configured hold, configured exit latency and the bounded completed-bucket rounding allowance.
- Reject an entry before sizing whenever that interval can include an eight-hour UTC funding settlement.
- Apply the same rule in the fixed-notional fatal pilot and account-level development.
- Do not infer the realized early exit and then decide retrospectively whether funding would have been paid.
- Keep all signals, parameters, symbols, dates, fees, capacity, impact, risk, leverage and promotion gates unchanged.
- Keep 2024 selection, 2025 confirmation and 2026 sealed.

Only V5B or a later explicitly corrected engine may challenge the strategy ranking.
