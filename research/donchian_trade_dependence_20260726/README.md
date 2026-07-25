# Donchian theoretical-trade dependence screen

## Decision

`RES-20260726-DONCHIAN-DEPENDENCE-001` is **TESTED_BELOW_GATE**. A causal 2023-only Binance USD-M proxy screen found positive raw trend-following paths, and one matched specification improved materially when the short-channel breakout was allowed only after a losing theoretical breakout. However, no policy passed the preregistered concentration, sample, both-half-year, matched-improvement and 24-bps gates. The work therefore did not open 2024, 2025 or 2026, did not change the project first place, and did not authorize any order path.

## Mechanism

The original Turtle System 1 rule is a state machine, not merely another Donchian threshold. Every theoretical short-channel breakout in a symbol is followed to its 2-ATR stop or opposite-channel exit even when the account does not take it. The outcome updates the symbol state. A subsequent short-channel breakout is eligible after a theoretical loser; after a theoretical winner it is skipped unless a longer failsafe channel is crossed.

The 2026 YouTube/runs-test material was used only to discover that this old rule should be tested as conditional trade dependence. It did not supply any rule used for the official 2024 causal structure.

## Frozen development contract

- Physical data opened by the final run: 2023 only.
- Symbols: BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT.
- Aggregation: contiguous 5-minute bars to completed 30-minute or 60-minute bars.
- Entry channel: 12, 24, 48 or 96 aggregated bars; exit channel: one-quarter or one-half of the entry lookback.
- Failsafe: 2.5 times the entry lookback.
- Stop: fixed 2-ATR from the next-bar entry.
- Modes: all breakouts, after theoretical loser, after theoretical winner, and Turtle-style loser gate plus failsafe.
- Account: one global slot; 0.5% planned NAV risk including entry/stop fees; 5x notional cap; 10,000 USDT initial NAV.
- Cost replay: identical signals at 12, 18 and 24 bps round trip.
- No forced time exit. Opposite-channel exits fill at the next bar open; stops are executable intrabar, with adverse gap handling.

The primary screen contains 16 channel specifications and 64 matched policies. A targeted concentration follow-up contains 56 fixed payoff variants across the four strongest one-hour specifications.

## Key results

### Highest raw path, not a dependence improvement

Specification `a70626d9e484285f2cb4`: 60-minute, 96-bar entry, 48-bar exit, 240-bar failsafe, after-loser mode.

- 12 bps: 89 trades, +35.37% total, 0.0829996% geometric daily growth, PF 1.8083, MDD 11.02%.
- 24 bps: +25.93% total, 0.0631845% geometric daily growth, PF 1.6226, MDD 11.03%.
- Median trade: -50 bps; win rate: 17.98%; top-five positive-PnL share at 24 bps: 67.35%.
- Removing the largest 10% positive trades changes 24-bps return to -26.31%.
- The matched all-breakout comparator was stronger: 0.0900854% daily at 12 bps and 0.0700189% at 24 bps. This candidate therefore does not demonstrate incremental value from the dependence rule.

### Strongest matched dependence improvement

Specification `b5afb33dc35cb6c46093`: 60-minute, 48-bar entry, 24-bar exit, 120-bar failsafe.

- Matched all-breakout comparator: 160 trades, 0.0093688% daily at 12 bps and -0.0058577% at 24 bps.
- After-loser mode: 135 trades, 0.0737779% daily at 12 bps and 0.0497549% at 24 bps; 24-bps PF 1.3548 and MDD 14.25%.
- Both half-years were positive in the gated path, but the median trade remained -50 bps and the top-10%-removed return was -32.49%.
- Runs-test z was positive in all four symbols, but conditional next-trade means did not favor the after-loser state consistently across symbols. The mechanism is therefore unstable rather than a reusable four-asset law.

### Payoff-concentration follow-up

Fifty-six variants tested full or half exits at 1R/2R, break-even ratchets and the original channel exit. Zero passed. The most frequent small-win variant improved the median trade to +29.94 bps and made 246 trades, but reduced 24-bps growth to 0.002419% per day and still lost 9.51% after removing the top 10% winners. The original wide channel remained the highest raw path and the most concentrated.

## Why the work stopped

The target requires repeatable positive expectancy across many substantially independent trades, not a few long trends. Every positive path here depends on a small set of large winners; payout reshaping did not remove that dependence. Opening Bybit replay, historical funding, risk/leverage optimization or 2024 OOS would spend validation budget on a family that failed the fatal development gate.

## Reproduction

```bash
python -m pip install numpy pandas pytest
export DONCHIAN_SNAPSHOT=/path/to/2023_snapshot
export DONCHIAN_OUTPUT=/path/to/development_output
python research/donchian_trade_dependence_20260726/donchian_dependence_screen.py

export DONCHIAN_PAYOFF_OUTPUT=/path/to/payoff_output
python research/donchian_trade_dependence_20260726/payoff_concentration_screen.py
pytest -q research/donchian_trade_dependence_20260726/tests
```
