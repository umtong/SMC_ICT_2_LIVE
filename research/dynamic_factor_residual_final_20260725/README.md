# Dynamic common-factor residual — revision 7 reconciliation

This directory records the decision-ready reconciliation for `RES-20260725-DYNAMIC-FACTOR-001` without duplicating the full scientific implementation.

## Scientific source of truth

- Original code and preregistration: PR #25, branch `agent/r4-dynamic-factor-residual-001`
- Verified immutable-bundle workflow: run `30160153690`
- Scientific workflow head: `4a36ca54115517e77955d2d6ce1e4cb58c1fe691`
- Repaired bundle archive SHA-256: `0681abe577ef7fa13fee19d2fd78d807c6c2c65fed7d3fd900c31d85135c659e`
- Actual-funding audit code commit: `cc3294b1c1f6826a9c5a3682da934a9e8d8e8062`
- Actual-funding evidence bundle SHA-256: `e2b83969c61daea1bd1fe74b0dcd4382ad1da097f468c57b4d648289bf4d21b6`

## Candidate

- Candidate: `021fbab613517a31ad98`
- Family: rank transition with flow-decay exit
- Stage: exploratory 2023 development
- One global BTC/ETH/SOL/XRP slot
- Next exact five-minute-open entry
- 0.5% planned loss, 3x notional cap, 0.1% prior quote-volume cap
- 12/18/24bp same-path cost replay
- Actual funding at calc_time using contemporaneous mark open

At 12bp with actual funding the candidate generated 194 trades, +23.2585%, 0.0573077% geometric daily growth, PF 1.504 and MDD 4.617%. It is proposed as provisional first place by target proximity, but remains below the strict economic gate because top-10%-removed return is -21.8583%, the median trade is negative and all four frozen 2024 family portfolios lost. It is not validated or deployable; 2025 and 2026 remain sealed and order permission remains none.
