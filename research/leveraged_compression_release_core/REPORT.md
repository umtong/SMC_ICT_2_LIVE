# Leveraged compression-release acceptance/rejection Core

## Decision

`RES-20260730-LEVERAGED-COMPRESSION-RELEASE-CORE-001` is:

`RETIRED_PRE2024_SUBCOST_LEVERAGED_COMPRESSION_RELEASE`

The exact joint state is frequent and is not dependent on a few winners, but it does not contain enough gross price movement to pay realistic round-trip costs. Calendar 2023 is negative even before costs. ML, risk/leverage search and official 2024–2026 remained closed.

## Failure lesson and mechanism

The current provisional rank-one is a multi-day Expansion whose official growth is concentrated in long-held winners. This work therefore did not tune its channel, scale, side or risk. It tested a distinct intraday balance-sheet transition:

> OI notional accumulates while price remains trapped inside a compressed six-hour balance; the first release is either accepted price discovery or a rejected false release.

At each completed UTC hour, the prior 72 completed five-minute bars formed a frozen six-hour balance. Calendar 2021 alone froze, per symbol, the lower-quartile compression threshold and upper-quartile positive OI-notional accumulation threshold. An active state was never refreshed. The first five-minute close outside the range was the release; the immediately following completed five-minute response classified acceptance continuation or rejection rotation.

No FVG, OB, session, prior-day level, channel lookback, fixed holding duration or post-outcome direction choice was used.

## Frozen thresholds

| Symbol | 2021 fit rows | compression q25 | OI-notional accumulation q75 |
|---|---:|---:|---:|
| BTCUSDT | 8,110 | 0.718466803 | 1.060886570 |
| ETHUSDT | 6,357 | 0.732828556 | 1.100980300 |

The canonical export ZIP SHA-256 is `950ad2ee0f5d6df729c11a15b817e30e19ead754a35385e5535233d0af8e6c02`.

## Opportunity density

The corrected state machine generated 1,525 actionable classifications through 2023:

- 1,460 resolved actions;
- 58 entries already structurally invalidated by the first executable minute;
- 7 rejection targets already passed before activation.

Resolved deterministic actions:

| Year | accepted continuation | rejected rotation | total resolved |
|---|---:|---:|---:|
| 2021 | 268 | 102 | 370 |
| 2022 | 441 | 186 | 627 |
| 2023 | 281 | 182 | 463 |

The one-global-slot account completed 537 trades in 2022 and 421 in 2023, with activity in all 12 months of both years. Opportunity scarcity is therefore not the failure.

## Gross mechanism economics

| Year | Action | Mean gross | Median gross | Median hold |
|---|---|---:|---:|---:|
| 2022 | ACCEPT_CONTINUE | +9.51 bp | −3.22 bp | 11 min |
| 2022 | REJECT_ROTATE | +2.34 bp | −8.65 bp | 17 min |
| 2023 | ACCEPT_CONTINUE | +0.06 bp | −5.39 bp | 7 min |
| 2023 | REJECT_ROTATE | +2.46 bp | −4.51 bp | 10.5 min |

Every year/action aggregate has a negative median. The strongest mean, 2022 accepted continuation at +9.51 bp, is below even the 12 bp diagnostic cost. The unchanged 2023 gross account is negative. This is not a good alpha erased only by the conservative 24 bp path.

## One-slot account result

Fixed 0.5% current-NAV planned loss, 3x cap, actual signed funding and adverse ambiguity:

| Year | Cost | Final NAV | Return | Trades | PF | Median account return | MDD |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 0 bp | 14,433.74 | +44.34% | 537 | 1.313 | −0.1348% | 6.31% |
| 2022 | 12 bp | 5,262.18 | −47.38% | 537 | 0.563 | −0.3398% | 47.38% |
| 2022 | 18 bp | 4,030.31 | −59.70% | 537 | 0.403 | −0.3658% | 59.70% |
| 2022 | 24 bp | 3,354.86 | −66.45% | 537 | 0.301 | −0.3856% | 66.45% |
| 2023 | 0 bp | 9,309.30 | −6.91% | 421 | 0.916 | −0.1403% | 9.70% |
| 2023 | 12 bp | 3,760.87 | −62.39% | 421 | 0.264 | −0.4241% | 62.39% |
| 2023 | 18 bp | 3,084.24 | −69.16% | 421 | 0.170 | −0.4964% | 69.16% |
| 2023 | 24 bp | 2,745.91 | −72.54% | 421 | 0.116 | −0.4971% | 72.54% |

Exact top-five positive event-key deletion followed by complete slot rerouting made the already negative 24 bp routes worse:

- 2022: 3,354.86 → 3,294.82 USDT;
- 2023: 2,745.91 → 2,662.09 USDT.

The top-five positive-PnL shares were only 8.22% in 2022 and 21.68% in 2023. This route is not failing because a few large winners dominate. It is a frequent, broad loss-compounding process after costs.

## Programization audit

The first implementation was not accepted as economic evidence. Two material discrepancies from the frozen semantic contract were found:

1. **Calendar-window defect.** The initial normalization used the most recent 720 valid hourly rows. A source gap could therefore make “30 days” span more than 30 UTC calendar days.
2. **OI endpoint defect.** The initial six-hour OI change compared the first and last five-minute stamps inside the balance, measuring 5 hours 55 minutes rather than the two exact six-hour availability boundaries.

The final run was rebuilt from the canonical source with:

- prior rolling `30D`, current observation excluded;
- exact OI observations available at the start and end of the six-hour state;
- 2021-only thresholds;
- non-overlapping states with no active-state refresh;
- one later completed response bar;
- decision plus 500 ms and first strictly later one-minute open;
- stop-first same-minute ambiguity;
- actual signed funding;
- full global-slot rerouting;
- zero trades crossing a selection boundary;
- no elapsed-time or scheduled strategy exit.

Eight focused tests passed. Two independent fresh-process runs produced byte-identical `RESULT.json`, `EVENTS.csv` and `RESOLVED_ACTIONS.csv`.

The corrected result remains decisively negative. The verdict is therefore economic failure after programization repair, not an unresolved implementation failure.

## Why ML and risk research stayed closed

The deterministic population failed at the level where ML would need genuine information:

- 2022 mean gross headroom does not pay 12 bp;
- 2023 is negative at zero cost;
- every action/year median is negative;
- 24 bp ordinary and winner-rerouted paths are deeply negative.

A conditional model could only obtain a positive headline by selecting rare historical tails or almost always choosing flat. Increasing risk or leverage would amplify a negative base distribution. Neither step is authorized.

## Decision and next direction

Retire the exact six-hour q25-compression / q75-OI-accumulation / one-response-bar information unit. Do not change the compression horizon, quantiles, response count, midpoint, R target, side, session, cost, risk, leverage or add an SMC checklist after observing this result.

The failure narrows the search: **inventory accumulation inside a visible price balance is not enough; the missing information must identify actual aggressive order ownership or an external inventory transfer before the release, not infer it from OHLCV and aggregate OI/account state alone.**

No credentials, paper orders, testnet orders or live orders were used.
