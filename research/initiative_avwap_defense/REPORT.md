# Initiative-displacement AVWAP inventory-defense result

- status: `RETIRED_2022_DETERMINISTIC_ECONOMIC_FAILURE`
- pooled calendar-2021 q75 turnover-z threshold: `0.628394710479388`
- candidate counts: `{'DEFEND_CONTINUE': 17, 'FAIL_UNWIND': 127}`

## Untouched calendar-2022 principal 24bp

- `FULL_MAP`: 59 trades, `0.879845174x`, PF `0.107031`, median `-0.204939%`, halves `{'2022H1': -0.06982269701742061, '2022H2': -0.054110252585368945}`, median hold `10.00m`, top-five positive share `73.86%`, winner-deleted/rerouted `0.870433160x`.
- `DEFEND_ONLY`: 6 trades, `0.970428754x`, PF `0.000000`, median `-0.500000%`, halves `{'2022H1': -0.014874518366318923, '2022H2': -0.014918635294385973}`, median hold `43.00m`, top-five positive share `0.00%`, winner-deleted/rerouted `0.970428754x`.
- `FAIL_ONLY`: 53 trades, `0.906656126x`, PF `0.134804`, median `-0.184118%`, halves `{'2022H1': -0.055777847264674274, '2022H2': -0.039785157546549654}`, median hold `10.00m`, top-five positive share `73.56%`, winner-deleted/rerouted `0.896957305x`.

## Zero-cost diagnosis

Even before fees, `FULL_MAP` ended at `0.948610009x` and `FAIL_ONLY` at `0.976342589x`; all six selected `DEFEND_ONLY` trades lost. The failure is not an execution-cost-only effect.

## Programization audit

- one-hour pivots become usable only after two completed right-side bars;
- the displacement interval begins after pool availability and uses a prior-only 672-bar turnover state;
- event AVWAP is exact `sum(turnover)/sum(volume)` over all fifteen observed one-minute rows and matches the completed 15-minute aggregate;
- OI/account sponsorship is available at exact completed five-minute timestamps, with no stale carry-forward;
- the first AVWAP interaction resolves the event; no second-touch retry is permitted;
- a completed five-minute close through the displacement open is origin-state loss before interaction;
- entry occurs strictly after decision +500ms and intervening completed-minute premise/target/stop consumption cancels the action;
- same-minute barrier ambiguity is stop-first, actual funding is applied, BTC/ETH share one slot, and no elapsed-time close is used;
- unresolved stage exposure is marked rather than strategy-closed.

Two fresh processes produced byte-identical result, report, candidate and validation files.

## Decision

The event family is retired before calendar 2023. Event AVWAP is a coherent observable cost-basis proxy, but completed OI/account sponsorship and the first AVWAP interaction do not distinguish defended initiative inventory from unwind with executable cost headroom. No ML, risk/leverage, AVWAP band, turnover threshold, pivot width, target, stop, session, FVG/OB or adjacent confirmation rescue is authorized.
