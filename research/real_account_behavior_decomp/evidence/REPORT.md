# Pre-2024 real-account decision-behavior decomposition

## Decision

`IDEA_EVIDENCE_ONLY_NO_BYBIT_PREREGISTRATION`. This study is **hypothesis-generation evidence only**. It is not a strategy, backtest, ranking result, or live authorization.

## Source boundary

- Repository: `bwjoke/BTC-Trading-Since-2020`
- Pinned commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- Manifest generated: `2026-07-19T12:35:13Z`
- Economic cutoff: `2023-12-31T23:59:59.999000+00:00`
- Execution rows retained: 146,423 of 173,434
- Order rows retained: 38,158 of 43,251
- Wallet rows retained: 4,777 of 17,484

Every required file matched the manifest SHA-256. Later rows were transport-only and were discarded before episode reconstruction.

## Reconstruction

- BTC-related position-effect rows: 77,125
- Episodes: 653
- Closed episodes: 651
- Open at cutoff: 2
- Symbols: XBTM21, XBTUSD, XBT_USDT
- Execution/order-ID match ratio: 0.9998444084278768

## Instrument / side summary

| symbol   | settlement_currency   | side   |   episodes |   wins |   losses |   win_rate |   gross_realised_pnl_native |   realised_minus_comm_proxy_native |   positive_pnl_native |   negative_pnl_native |   median_pnl_native |   median_duration_min |   mean_duration_min |   median_fills |   median_adds |   median_reductions |   maker_share | top1_positive_share   | top5_positive_share   | top10_positive_share   | top10pct_positive_share   |
|:---------|:----------------------|:-------|-----------:|-------:|---------:|-----------:|----------------------------:|-----------------------------------:|----------------------:|----------------------:|--------------------:|----------------------:|--------------------:|---------------:|--------------:|--------------------:|--------------:|:----------------------|:----------------------|:-----------------------|:--------------------------|
| XBTM21   | XBt                   | SHORT  |          1 |      0 |        0 |          0 |                           0 |                       -1.39856e+06 |                     0 |                     0 |                   0 |               0.57465 |             0.57465 |             19 |            11 |                   7 |      0        |                       |                       |                        |                           |
| XBTUSD   | XBt                   | LONG   |        409 |      0 |        0 |          0 |                           0 |                       -9.848e+08   |                     0 |                     0 |                   0 |             663.161   |          2245.58    |             31 |            14 |                  14 |      0.306757 |                       |                       |                        |                           |
| XBTUSD   | XBt                   | SHORT  |        241 |      0 |        0 |          0 |                           0 |                       -3.67461e+08 |                     0 |                     0 |                   0 |             703.689   |          2578.29    |             36 |            18 |                  18 |      0.323164 |                       |                       |                        |                           |

## Repeated behavior summary

| behavior              |   episodes |   episode_share |   win_rate |   median_pnl_native |   sum_pnl_native |   median_duration_min |   median_max_position |   maker_share |
|:----------------------|-----------:|----------------:|-----------:|--------------------:|-----------------:|----------------------:|----------------------:|--------------:|
| ANY_WINNING_ADD       |        383 |        0.588326 |          0 |                   0 |                0 |             1073.24   |                290100 |      0.304351 |
| ANY_LOSING_ADD        |        471 |        0.723502 |          0 |                   0 |                0 |              929.545  |                231110 |      0.318414 |
| WINNING_ADDS_ONLY     |         68 |        0.104455 |          0 |                   0 |                0 |              687.694  |                139200 |      0.229172 |
| LOSING_ADDS_ONLY      |        156 |        0.239631 |          0 |                   0 |                0 |              532.159  |                 82105 |      0.412435 |
| ANY_FAVORABLE_REDUCE  |        478 |        0.734255 |          0 |                   0 |                0 |              734.98   |                150200 |      0.32874  |
| ANY_ADVERSE_REDUCE    |        332 |        0.509985 |          0 |                   0 |                0 |             1074.69   |                258832 |      0.313366 |
| DIRECT_REVERSAL_ENTRY |        103 |        0.158218 |          0 |                   0 |                0 |              607.173  |                196747 |      0.328381 |
| REENTRY_WITHIN_60M    |        334 |        0.513057 |          0 |                   0 |                0 |              452.159  |                196148 |      0.311074 |
| NO_SCALE_IN           |         51 |        0.078341 |          0 |                   0 |                0 |               99.3237 |                 15555 |      0.346667 |
| SCALED_IN             |        600 |        0.921659 |          0 |                   0 |                0 |              726.402  |                165000 |      0.312263 |
| MAKER_MAJORITY        |        143 |        0.219662 |          0 |                   0 |                0 |              958.062  |                120000 |      0.607999 |
| TAKER_MAJORITY        |        473 |        0.726575 |          0 |                   0 |                0 |              611.134  |                160000 |      0.261253 |
| AFTER_PREVIOUS_WIN    |          0 |        0        |        nan |                 nan |                0 |              nan      |                   nan |    nan        |
| AFTER_PREVIOUS_LOSS   |          0 |        0        |        nan |                 nan |                0 |              nan      |                   nan |    nan        |

## Holding-time decomposition

| settlement_currency   | duration_bucket   |   episodes |   wins |   losses |   win_rate |   gross_realised_pnl_native |   realised_minus_comm_proxy_native |   positive_pnl_native |   negative_pnl_native |   median_pnl_native |   median_duration_min |   mean_duration_min |   median_fills |   median_adds |   median_reductions |   maker_share | top1_positive_share   | top5_positive_share   | top10_positive_share   | top10pct_positive_share   |
|:----------------------|:------------------|-----------:|-------:|---------:|-----------:|----------------------------:|-----------------------------------:|----------------------:|----------------------:|--------------------:|----------------------:|--------------------:|---------------:|--------------:|--------------------:|--------------:|:----------------------|:----------------------|:-----------------------|:--------------------------|
| XBt                   | <1h               |         85 |      0 |        0 |          0 |                           0 |                       -7.41899e+07 |                     0 |                     0 |                   0 |               14.6881 |             20.7875 |             15 |             6 |                 7   |      0.207802 |                       |                       |                        |                           |
| XBt                   | 1-6h              |        155 |      0 |        0 |          0 |                           0 |                       -2.6294e+08  |                     0 |                     0 |                   0 |              176.327  |            186.874  |             16 |             6 |                 9   |      0.182311 |                       |                       |                        |                           |
| XBt                   | 6-24h             |        201 |      0 |        0 |          0 |                           0 |                       -2.59982e+08 |                     0 |                     0 |                   0 |              717.762  |            774.516  |             32 |            15 |                15   |      0.287086 |                       |                       |                        |                           |
| XBt                   | 1-3d              |        125 |      0 |        0 |          0 |                           0 |                       -3.80469e+08 |                     0 |                     0 |                   0 |             2421.53   |           2536.84   |             57 |            30 |                21   |      0.285026 |                       |                       |                        |                           |
| XBt                   | 3-7d              |         59 |      0 |        0 |          0 |                           0 |                       -1.81629e+08 |                     0 |                     0 |                   0 |             6173.78   |           6325.97   |             96 |            46 |                58   |      0.386139 |                       |                       |                        |                           |
| XBt                   | >7d               |         26 |      0 |        0 |          0 |                           0 |                       -1.9445e+08  |                     0 |                     0 |                   0 |            15743.6    |          25502.5    |            223 |           117 |                98.5 |      0.394121 |                       |                       |                        |                           |

## Size after prior outcome

| settlement_currency   | previous_outcome   |   episodes |   median_start_qty |   median_start_home_notional |   median_start_foreign_notional |   median_max_position |   median_add_count |   next_episode_win_rate |
|:----------------------|:-------------------|-----------:|-------------------:|-----------------------------:|--------------------------------:|----------------------:|-------------------:|------------------------:|
| XBt                   | FLAT               |        649 |               8100 |                      0.38115 |                            8100 |                136288 |                 15 |                       0 |

## Core versus Expansion diagnosis

```json
{
  "broad_repetition": true,
  "concentration": [
    {
      "closed_episodes": 651,
      "episodes_gt3d": 85,
      "gross_realised_pnl_native": 0.0,
      "median_episode_pnl_native": 0.0,
      "pnl_from_gt3d_native": 0.0,
      "positive_episodes": 0,
      "settlement_currency": "XBt",
      "top10_positive_share": null,
      "top10pct_positive_share": null,
      "top1_positive_share": null,
      "top5_positive_share": null
    }
  ],
  "hypotheses_generated": 0,
  "positive_median_by_settlement": {
    "XBt": false
  }
}
```

## Falsifiable Bybit hypotheses

```json
[]
```

## Boundary

No external-account threshold, position size, side, holding time, or 2024-2026 behavior may be copied into a Bybit strategy. Any surviving hypothesis must be independently defined and frozen with canonical Bybit data through 2023-12-31, then evaluated under the project execution and one-slot account contract.
