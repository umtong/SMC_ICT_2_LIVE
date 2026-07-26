# Minimal ML option-surface shape first-passage

This directory implements `CLM-20260726-1914-ML-OPTION-SURFACE-001`.

## Economic idea

Completed option-surface shape is treated as institutional sponsorship state, not as a direct trade trigger:

- more negative front RR25 and expanding front BF25 represent urgent downside convexity demand;
- positive or improving RR25 represents call-side demand or downside exhaustion;
- front/middle/back term differences separate short-lived hedging pressure from persistent repricing;
- price remains the execution map: the prior completed 60-minute high and low are frozen as buy-side and sell-side external liquidity.

One regularized logistic model estimates which frozen pool is reached first. One cost-adjusted expected-value equation chooses long, short or cash. There is no adjacent strategy family or threshold grid.

## Source discipline

`SOURCE_GATE.json` records the successful outcome-sealed source inspection. The public 2024 parquet contains 4,498,832 BTC option snapshot rows from 2024-01-13 through 2024-07-27, but it is never used for outcomes, labels, model fitting, actions or PnL.

The primary fatal screen uses only fixed pre-2024 Tardis Deribit month-start prefixes:

- 2020-2021 training;
- 2022H1 calibration;
- 2022H2 untouched confirmation;
- 2023 development, opened only if confirmation beats the structural-distance heuristic on both AUC and Brier score.

Each date reads exactly the first 150,000 rows. Increasing the cap after observing any outcome is prohibited.

## Implementation files

- `PREREGISTRATION.md`: frozen scientific and execution contract.
- `WORK_CLAIM.json`: live scope and non-overlap evidence.
- `SOURCE_GATE.json`: immutable public-parquet findings and decision.
- `run_py.gz.b64.part00`: deterministic gzip/base64 representation of `run_pre2024_option_surface.py`.
- `reconstruct.py`: recreates the executable source and verifies its SHA-256.
- `test_run_pre2024_option_surface.py`: network-free unit tests for surface construction, causal price context and cost-adjusted action choice.

The compressed source is used only because the connector write path has a practical large-text limit. The workflow reconstructs ordinary Python before compilation, tests and execution; the reconstructed source is uploaded in the evidence artifact.

## Output contract

The workflow emits:

- `SOURCE_MANIFEST.json` with consumed-prefix hashes and per-date surface counts;
- `PRICE_MANIFEST.json` for immutable Binance USD-M one-minute execution proxies;
- `CAUSAL_ROWS.json` with every causally available feature and first-passage label;
- `RESULT.json` with model diagnostics and, only after the confirmation gate, 12/18/24 bp account replays;
- `SHA256SUMS.txt` and the reconstructed source.

This is an early pre-2024 proxy screen, never a rank-eligible Bybit result. A passing result may only open an unchanged exact-Bybit reconstruction. No credentials or orders are permitted.
