# ML Intraday Liquidity Auction R23

This route implements the user's scope correction: **no tick-by-tick, subsecond, micro-price, queue-position or latency alpha**.

The system operates on completed 1-minute, 5-minute, 15-minute and 1-hour bars. The fixed 500 ms project latency remains only as a causal order-activation assumption. With minute OHLCV, a decision made at a completed 15-minute close enters no earlier than the next minute open.

## Performance objective

The objective is to **maximize sustainable realistic after-cost geometric growth on the continuous account NAV path**. The project requirement of 1% per UTC calendar day is a minimum completion threshold, not an optimization target, cap or reason to reduce leverage, risk, position size, trade frequency or realized growth.

A path above 1% per day remains at full strength. A 2%, 3% or higher hard-valid sustainable path ranks ahead of a near-1% path when liquidation, irreversible account damage, loss-tail concentration, costs, execution and reproducibility remain acceptable. Conversely, a merely positive pre-2024 result only justifies opening the official 2024H1 evaluation; it is not success and will not be protected from replacement by a structurally stronger alpha.

The primary cost basis is the actual Bybit order-type fee plus causally observed spread, estimated size-dependent slippage/market impact and actual funding. Fixed values such as 24 bp may be used as adverse sensitivity points, but no universal 24 bp number is the primary selector.

## SMC/ICT interpretation

A previously available external-liquidity level is swept. The model chooses among:

- `reject`: failed acceptance and rotation toward internal/opposing liquidity;
- `continue`: acceptance beyond the level and measured range expansion;
- `flat`: no positive expected structural utility after realistic costs.

The liquidity map uses confirmed hourly swings, prior UTC-day high/low, prior-only rolling 24-hour high/low and completed eight-hour session ranges. Pivots are unavailable until the complete right-side confirmation span has elapsed.

## Current implementation

`run.py` provides:

- strict minute-bar validation and explicit rejection of tick/queue columns;
- causal 5m/15m/1h aggregation;
- delayed confirmed swing construction;
- prior-day, rolling-24h and completed-session liquidity levels;
- 15-minute sweep/acceptance event rows and completed 5-minute displacement/FVG features;
- structural rejection and continuation plans;
- next-minute entry under the fixed 500 ms latency;
- adverse-first same-minute stop/target handling;
- no maximum holding time and boundary NAV marking;
- paired HistGradientBoosting payoff models with isotonic calibration.

Input files are standardized one-minute `SYMBOL.parquet`, `SYMBOL.csv.gz` or `SYMBOL.csv` files with `timestamp, open, high, low, close, volume`. Timestamp is the UTC minute-open time.

```bash
python reconstruct.py
python run.py self-test
python run.py run --data-root /path/to/minute-bars --output /path/to/output --symbols BTCUSDT ETHUSDT
pytest -q test_run.py
```

## Next executable step

Bind the existing immutable pre-2024 Bybit minute partitions to the standardized input contract. The exact causal training, calibration and update procedure remains a design variable and must be selected for objective impact and frozen before opening official 2024H1. There is no mandatory `2021-2022 fit -> 2023H1 calibration -> untouched 2023H2` sequence. Once the complete method is fixed, all data permitted by that method through 2023-12-31 may be used for the deployable 2024H1 model.

When pre-2024 evidence shows credible realistic after-cost possibility without a fatal validity error, freeze the full system and open official 2024H1 immediately. Fixed 24 bp profitability and a separate untouched 2023H2 gate are not required. After base alpha is confirmed, risk and leverage maximize the realistic-cost continuous account path and are never scaled down merely because performance exceeds 1%.

No credentials or orders are authorized.
