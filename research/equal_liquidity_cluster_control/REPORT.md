# Equal-liquidity cluster control-transfer result

- Result ID: `RES-20260730-EQUAL-LIQUIDITY-CLUSTER-CONTROL-001`
- Status: `RETIRED_2022_DETERMINISTIC_ECONOMIC_FAILURE`
- Ranking role: none
- Official 2024-2026: unopened
- Credentials/orders: none

## Question

Does repeated causal defense at nearly equal one-hour swing highs/lows create a materially stronger stop-liquidity pool than an arbitrary single swing, so that the first exceptional-turnover raid supports either outside acceptance continuation or inside rejection rotation as a frequent day-trading Core?

## Frozen state

Two same-side confirmed one-hour pivots had to be separated by at least four hours and no more than five days, with dispersion no larger than `0.10 × prior-only ATR20`. The first pivot's close-side defense had to remain unconsumed until the second pivot became available. Calendar 2021 fixed one pooled prior-only 168h log-turnover-z q75, `0.6293676360`.

The first later close through the cluster by at least `0.05 ATR` on exceptional participation started the event. The immediately next completed hour selected ACCEPT outside or REJECT inside. Entries activated after 500ms at the first later observed minute; targets, stops and state loss followed the same control-transfer premise. One global BTC/ETH slot, actual funding, fixed 0.5% NAV risk, 3x cap and 12/18/24bp were used. There was no elapsed-time exit.

## Programization correction

The preliminary output was quarantined because the initial generator could pair a second equal pivot with a first pivot whose close defense had already been consumed. The corrected authority requires the first pivot to remain close-unconsumed through the bar preceding the second pivot's causal availability.

After correction:

- equal-pool inventory: BTC `512`, ETH `453`;
- executable candidate inventory: 2021 `201`, untouched 2022 `283`;
- candidate states: ACCEPT `394`, REJECT `90` across 2021-2022;
- two fresh processes produced byte-identical `RESULT.json`, `REPORT.md` and candidate CSV hashes;
- entry chronology, stop/entry/target geometry and global-slot non-overlap assertions passed.

## Untouched calendar-2022 result

### Principal 24bp

| Policy | Trades | NAV | PF | Median | Half-years | Winner deleted/rerouted | Median hold |
|---|---:|---:|---:|---:|---|---:|---:|
| Full ACCEPT/REJECT map | 193 | 0.972170x | 0.9301 | -0.1920% | +1.14%, -3.88% | 0.894380x | 4.00h |
| ACCEPT only | 153 | 0.976948x | 0.9241 | -0.1616% | +1.72%, -3.96% | 0.903126x | 3.53h |
| REJECT only | 61 | 1.004080x | 1.0316 | -0.2083% | -1.64%, +2.08% | 0.942669x | 4.00h |

The only ordinary positive path was REJECT, but it failed every Core interpretation that matters: negative median, negative first half, `61.01%` top-five positive-PnL concentration and loss after exact winner deletion with full slot rerouting.

### Gross and cost decomposition

At zero transaction cost:

- full map `1.10758x`;
- ACCEPT `1.07773x`;
- REJECT `1.06271x`.

Yet every median trade remained negative, ACCEPT and REJECT both fell below one after winner deletion, and at 12bp all winner-deleted paths were below one. At 18bp the full map was only `1.000406x` with a negative second half and negative median. The information unit therefore has a weak gross relation but no stable executable Core headroom.

## Interpretation

Repeated equal highs/lows are more meaningful than arbitrary pivots, but price geometry alone still does not reveal how much outstanding inventory is actually defended there. The ordinary ACCEPT/REJECT map admits many small losing events. REJECT captures a few successful rotations after raids, but the sign is half-year unstable and dependent on a small positive tail.

The result narrows the SMC/ICT conclusion:

> A visible liquidity shape can identify where stops may exist, but a tradable Core also needs causal evidence that the pool contains enough vulnerable inventory and that raid flow is actually exhausted or newly sponsored.

Therefore the project should not continue refining equal-level tolerance, pivot width, killzone, FVG, OB or confirmation count. Those changes would search historical subgroups inside an information source that has already shown inadequate cost headroom.

## Decision

`RETIRE_EQUAL_LIQUIDITY_CLUSTER_CONTROL_PRE2024`.

Calendar 2023 and official 2024-2026 remain sealed. ML, risk and leverage research remain closed. Ranking and live authority are unchanged.
