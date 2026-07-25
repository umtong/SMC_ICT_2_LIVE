# Option-surface shape state research — preregistration

## Claim

`CLM-20260726-0107-OPTION-SURFACE-001`

## Objective

Test whether completed BTC/ETH option-surface **shape**, rather than ATM/DVOL level, can route a single Binance USD-M perpetual position with materially larger realistic after-cost geometric growth and lower profit concentration.

## Non-overlap

This claim excludes the merged DVOL-XSEC study's 30-day IV level, common/relative DVOL and IV-minus-realized-volatility premium. It also excludes active spot-perp, COIN-M/cross-margin, cross-exchange price discovery, flow-size/impact, positioning and L2-maker scopes.

The new information set is limited to:

- 25-delta risk reversal: `RR25 = IV(call,+0.25 delta) - IV(put,-0.25 delta)`;
- 25-delta butterfly: `BF25 = 0.5*(IV(call25)+IV(put25)) - IV(ATM)`;
- front/back ATM term slope;
- front/back RR25 term slope;
- prior-only changes, rolling ranks and z-scores of those quantities;
- option open-interest concentration only when present in the same completed snapshot.

Options are **state information only**. The strategy may submit at most one permitted BTCUSDT or ETHUSDT USD-M perpetual order/position.

## Data hierarchy

1. Public hourly full-chain data linked by Deribit Insights for 2024-01-13 through 2024-07-27, if the immutable file is retrievable.
2. UWA Deribit options dataset released under CC BY, used for an older independent pilot if timestamp and field semantics are adequate.
3. Tardis free first-day-of-month Deribit `options_chain` files, used for schema verification and sparse cross-regime falsification; never represented as continuous daily coverage.
4. Paid/modelled sources are not silently mixed with public observed data. Any model-derived surface must be separately tagged and excluded from the primary result.

## Point-in-time surface construction

- A snapshot becomes usable only after its exchange timestamp and local capture timestamp are both observed, plus a fixed 5-minute operational delay.
- Bid/ask IV midpoint is used only when both sides are finite, positive and non-crossed. Mark IV is not substituted silently.
- For each target tenor, use the nearest expiry inside the registered DTE window; no interpolation across future expiries.
- Front tenor: 5–14 calendar days. Middle tenor: 21–45 days. Back tenor: 60–120 days.
- Call/put 25-delta and ATM contracts are the nearest available deltas within 0.07 of the target. A surface row is invalid if any required leg is missing.
- Rolling standardisation uses only previously completed usable snapshots. The current observation is excluded from its own reference distribution.
- Sparse Tardis month-start samples use expanding prior samples only and are evaluated as a separate sparse experiment.

## Hypothesis families kept separate

1. **Downside-demand continuation**: RR25 becomes more negative, front RR is more negative than back RR, downside BF expands and completed perp structure is weak; trade short.
2. **Downside-demand exhaustion**: RR25 is extremely negative but stops worsening while price reclaims completed structure; trade long.
3. **Call-squeeze continuation**: RR25 turns positive, front ATM/BF rises and price confirms an upside break; trade long.
4. **BTC–ETH surface divergence**: one asset's RR/term surface leads while its perp underreacts relative to the other; trade only the causally selected USD-M leg.
5. **CASH**: no trade when the expected after-cost edge or surface completeness gate is not met.

No family may use the future option snapshot, final trade outcome, future MFE/MAE or later surface classification as an input.

## Small registered parameter set

- observation cadence: 1h and 4h;
- signal horizon / economic state life: 4h, 12h and 24h;
- rolling reference: 20 and 60 prior usable snapshots;
- absolute surface-state threshold: 1.0, 1.5 and 2.0 prior-only z;
- structure confirmation: none, completed 4h break/reclaim;
- risk/reward: 1.0R, 1.5R and 2.0R;
- stop: completed 1h/4h structure plus 0.25 ATR, or 1.0 ATR when structure is unavailable.

The state-life exit is the registered information half-life of the options snapshot, not an arbitrary account-management liquidation. State invalidation, stop or target may exit earlier.

## Execution contract

- decision after completed option snapshot plus 5-minute delay;
- entry at the next available Binance USD-M one-minute open after decision;
- one global pending/open slot across BTCUSDT and ETHUSDT;
- 0.5% planned NAV loss per trade; 3x notional cap; 0.1% prior quote-volume capacity cap;
- entry/stop fees and adverse stop slippage included in quantity;
- same-minute stop/target ambiguity resolves to stop;
- gap stop fills at adverse actual open;
- actual historical funding applied in `(entry, exit]` using contemporaneous mark/open fallback only when explicitly disclosed;
- identical base signals and paths replayed at 12, 18 and 24 bp round-trip modeled costs;
- no option orders, credentials, paper/testnet/live orders or bank integration.

## Staged evaluation

The exact calendar split depends on observed public coverage and is frozen in the data manifest before strategy PnL is computed. At minimum:

- data/schema pilot;
- chronological development;
- independent selection;
- one unopened validation interval;
- any later/forward interval remains sealed unless preceding gates pass.

A public six-month 2024 dataset can produce only a pilot/short OOS result and is not ranking-eligible by itself. Tardis first-day monthly samples remain a separate sparse falsification set.

## Initial economic gates

- positive geometric growth at 12 and 18 bp in each opened development segment;
- non-negative at 24 bp;
- PF >= 1.10 at 18 bp;
- at least 60 completed trades in development for an intraday candidate;
- positive return after removing top five winners and top 10% winners;
- top-five positive-PnL share <= 35%;
- maximum drawdown <= 15%;
- no forced liquidation or irrecoverable account path.

The 1% daily-growth target is unchanged. Passing these gates only opens the next stage; it does not grant rank, paper or live permission.
