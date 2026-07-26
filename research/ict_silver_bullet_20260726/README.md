# ICT Silver Bullet exact-window causal screen

Claim: `CLM-20260726-1620-SILVER-BULLET-001`  
Branch: `agent/r11-silver-bullet-window-001`

## Explanation for an SMC/ICT trader

This is the three-window ICT Silver Bullet model, translated without hindsight.

The only valid setup clocks are **03:00–04:00, 10:00–11:00 and 14:00–15:00 America/New_York**. Historical daylight-saving time is applied from the IANA timezone database; a fixed UTC offset is forbidden.

For a bullish trade:

1. Before the window opens, freeze the immediately preceding 60- or 120-minute buy-side and sell-side liquidity range.
2. Inside the active hour, price must raid the frozen sell-side liquidity.
3. The raid must reclaim that level on the sweep bar or within three completed bars.
4. A later completed bullish displacement candle must close through the last five-minute internal high and create a classic bullish three-candle FVG inside the same Silver Bullet hour.
5. The first later completed interaction with that FVG is decisive. It must either close back through the near edge or reclaim consequent encroachment. An unaccepted or failed first touch invalidates the setup permanently.
6. Entry is the next contiguous one-minute open. Stop is beyond the raid extreme. Target is the frozen opposing pre-window liquidity, and the target must provide the candidate's minimum structural reward/risk.
7. After entry, only opposing liquidity, protective stop, completed FVG invalidation or a source failure can end the position. There is no window-end or elapsed-time liquidation.

The bearish model is the exact mirror.

This can be explained on a chart with the ordinary ICT vocabulary—time window, external liquidity, raid, MSS, displacement, FVG, CE, first retracement and opposing draw on liquidity—while every noun has an information-availability timestamp.

## Historical concept source

The Inner Circle Trader's May 2023 Silver Bullet lesson describes the three New-York-local windows as 03:00–04:00, 10:00–11:00 and 14:00–15:00 and frames the model around an FVG delivering toward an opposing liquidity pool. The source supplies vocabulary and a falsifiable clock; no displayed performance claim is accepted.

## Distinction from nearby project work

- The expired broad session-range claim used Asian/London/New-York range acceptance and sweep/reclaim outside a single exact entry clock. It produced no branch, PR or result.
- Unicorn required a failed order block converted into a breaker and exact breaker/FVG overlap. Silver Bullet requires neither.
- OTE uses a 62–79% retracement of an impulse, not a fixed one-hour FVG clock.
- FVG-SMT and SMT-sweep compare two instruments; this model is single-symbol time-price delivery.
- Quarter-hour order flow uses the first ten seconds of every quarter-hour and fixed holding diagnostics; this model uses three one-hour New-York-local windows and structural exits.

## Frozen research contract

- Venue and execution proxy: native Bybit USDT-linear one-minute public archives.
- Universe: BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT.
- Fit: calendar 2022.
- Development: calendar 2023, downloaded only for frozen fit survivors.
- 2024–2026: prohibited by code.
- Candidate grid: 384 cells covering window participation, pre-window liquidity horizon, reclaim delay, displacement, FVG size, first-touch acceptance and structural minimum RR.
- One global pending/open slot.
- Planned stop risk 0.5% of NAV, 3x notional cap and 0.1% of prior 60-minute quote-turnover capacity.
- Identical opportunity paths replayed at 12, 18 and 24 bp.
- Conservative one-basis-point reserve per crossed UTC eight-hour funding boundary in this fatal screen.
- Adverse gap stops and stop-first same-bar ambiguity.
- Missing minutes are never forward-filled or compressed. A post-entry source gap is terminal rather than deleted.
- No credentials, paper, testnet or live orders.

## Promotion boundary

A fit survivor must have at least 80 trades, positive return at 12/18/24 bp, at least 0.025% daily growth at 18 bp, positive median, both half-years positive, PF >= 1.10, acceptable drawdown and concentration, and positive full-account rerun after removing the largest 10% of winning trades. Development raises the trade, growth, PF, drawdown and concentration requirements.

Even a development survivor is not rank eligible. It must first receive a separate preregistration for exact historical Bybit BBO/depth, actual funding and sequential 2024 evaluation.
