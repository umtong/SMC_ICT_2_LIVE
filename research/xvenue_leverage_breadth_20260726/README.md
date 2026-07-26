# Binance–Bybit cross-venue leverage breadth

Claim: `CLM-20260726-1047-XVENUE-LEVERAGE-BREADTH-001`  
Result target: `RES-20260726-XVENUE-LEVERAGE-BREADTH-001`

## Economic hypothesis

A price shock alone does not reveal whether leverage is being created, transferred or closed. This study aligns same-symbol Binance Futures and Bybit open-interest updates with venue-specific aggressive trade flow on the comparable local-arrival clock.

It tests five distinct states:

1. balanced OI expansion plus aligned flow — common opening continuation;
2. Binance OI expansion before Bybit OI and price response — OI-led Bybit catch-up;
3. Bybit-specific OI expansion with weak or unconfirmed price response — trapped-opening reversal;
4. balanced OI contraction plus efficient displacement — common closing cascade;
5. balanced OI contraction plus weak Bybit close efficiency — closing exhaustion reversal.

Only Bybit BTCUSDT or ETHUSDT is traded. Cross-venue OI breadth or divergence is mandatory; ordinary price lead-lag cannot trigger a trade.

## Causal and execution contract

- Tardis `local_timestamp` orders every source message.
- Signals use only completed 1s, 2s or 5s windows.
- OI and activity scales are within-venue, shifted and prior-only.
- Bybit entry occurs at the causally current BBO after 100ms or 500ms; a quote older than one second is unavailable.
- Observed BBO spread, actual Bybit funding, 5% top-quote participation, 0.5% NAV risk and 3x notional cap are applied.
- Protective stop rebound is adverse.
- Exit is only by structural stop or 1R/2R target. No elapsed-time liquidation is introduced.
- One global BTC/ETH pending/open slot and no same-timestamp re-entry.
- Identical additional 12/18/24bp cost replay.

## Staging

The fatal screen opens six pre-2024 first-day public samples and 1,920 frozen policies. It is not rank eligible.

A survivor must pass fit and development sample, 18/24bp, median, profit-factor, concentration, unresolved-path and date-breadth gates, then expand under the exact frozen rule to every remaining pre-2024 public first-day sample before 2024 can open. Zero survivors retire this exact dependency.

## Reproduction

```bash
python -m pytest -q research/xvenue_leverage_breadth_20260726/test_run_screen.py
python research/xvenue_leverage_breadth_20260726/run_screen.py \
  --output research_runs/xvenue_leverage_breadth/output \
  --cache /tmp/xvenue-leverage-cache
```
