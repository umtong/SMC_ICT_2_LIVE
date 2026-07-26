# ML scheduled-macro pre-positioned OCO

Claim: `CLM-20260727-0402-ML-MACRO-OCO-TAKEOVER-001`  
Result namespace: `RES-20260727-ML-MACRO-OCO-001`

## Economic hypothesis

A scheduled CPI, U.S. Employment Situation, or FOMC statement can turn a compressed pre-release dealing range into one-sided price discovery. The system does not predict the released number. It places a frozen two-sided stop-entry OCO so that both orders become active at the official release timestamp, then uses an ML take/skip probability computed only from completed pre-release Bybit trade state to avoid low-quality ranges that are more likely to whipsaw than expand.

The route is distinct from post-release five-minute prediction. No actual release value, consensus surprise, completed post-release bar, cross-venue quote, liquidation label, or later outcome enters the decision.

## Frozen causal contract

- Instruments: Bybit USDT linear perpetual `BTCUSDT` and `ETHUSDT`.
- Global slot: at most one selected pending OCO or one open position across both instruments.
- Release timestamps: official BLS annual schedules and Federal Reserve FOMC meeting calendars, converted from `America/New_York` with historical daylight-saving rules.
- Feature cutoff: strictly before `release_time - 1.000s`.
- Submission: `release_time - 0.500s`; fixed order/venue activation latency `500ms`; orders become active at the scheduled release time.
- Candidate set: three preregistered dealing-range templates (`tight15`, `standard30`, `wide60`) on both symbols. The model may accept one candidate or stay flat; it does not alter geometry.
- Model: pooled HistGradientBoosting classifier trained on 2022; one-dimensional logistic probability calibration on 2023H1; threshold, risk, and leverage route selected on 2023H2 only.
- Costs: identical 12/18/24bp round-trip stress. Trigger and exit gaps come from the first observed Bybit trade beyond each price condition.
- OCO cancellation race: the opposite stop remains live for 500ms after the first fill; an opposite trigger inside that interval is flattened adversely and charged two round trips.
- Pending-order invalidation: no breakout plus a completed five-minute state wholly inside both triggers and closing in the middle half of the prerelease range.
- Position exits: expansion target, failed acceptance back into the range, opposing OCO transition, or NAV mark at a data/stage boundary. There is no elapsed-time forced liquidation.
- Position size: whole-account NAV risk budget divided by expected stop loss plus cost; notional is capped by the frozen leverage route. Risk grid is 0.25%–60%; leverage/notional caps are 1x–100x.
- Pre-2024 gate: positive 24bp 2023H2 geometric growth at 1% risk/3x baseline, at least six completed trades, no unresolved selected exposure/account destruction, and positive exact winner-removal growth. Only then is the broad risk/leverage route selected and the 2024H1 market archive opened.
- Negative gate: close this exact route without adjacent feature, threshold, stop, target, asset, risk, or leverage rescue.

## Data and provenance

- Bybit public daily trade archives: `https://public.bybit.com/trading/`
- BLS 2022 release calendar: `https://www.bls.gov/schedule/2022/home.htm`
- BLS 2023 release calendar: `https://www.bls.gov/schedule/2023/home.htm`
- BLS 2024 release calendar: `https://www.bls.gov/schedule/2024/home.htm`
- Federal Reserve FOMC calendar: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`

`events.csv` is the frozen timestamp snapshot. Every downloaded archive is recorded with URL, compressed SHA-256, byte count, row count, and observed timestamp bounds. The workflow opens 2024 archives only after the pre-2024 gate passes.

## Reproduction

```bash
python -m pip install -r research/ml_macro_oco_20260727/requirements.txt
python -m pytest -q tests/test_ml_macro_oco_20260727.py
python research/ml_macro_oco_20260727/run.py \
  --output artifacts/ml_macro_oco_20260727 \
  --cache .cache/ml_macro_oco_20260727
```

Fast plumbing check:

```bash
python research/ml_macro_oco_20260727/run.py \
  --smoke \
  --output artifacts/ml_macro_oco_20260727-smoke
```

The action artifact contains the decision, source manifest, scored candidates, route diagnostics, any official ledger, environment fingerprint, and run log. It never uses exchange credentials or sends an order.
