# CME CF London-fix displacement Core — stage-1 decision

- Claim: `CLM-20260730-CME-CF-LONDON-FIX-CORE-001`
- Status: `RETIRED_PRE_ACCOUNT_SUBCOST_OR_NONINCREMENTAL`
- Selected action: `CONTINUATION`
- Official 2024–2026: unopened
- ML/risk grid: unopened
- Credentials/orders: none

The DST-aware Monday-Friday 15:00–16:00 London benchmark window was compared with identical 14:00–15:00 and 16:00–17:00 controls. Entry was the first observed Bybit minute after window completion plus fixed latency. The selected continuation action remained below cost.

| Period | Events | 24bp mean | Median | PF | Winner-removed mean |
|---|---:|---:|---:|---:|---:|
| 2022 | 260 | -13.80bp | -21.35bp | 0.702 | -23.95bp |
| 2023 | 260 | -17.08bp | -24.32bp | 0.555 | -25.69bp |

The primary window was incrementally better than the earlier control but not consistently better than the later control and remained absolutely negative after cost. All four half-years were negative. The benchmark clock is context without a tradable Core in this fixed action space.

No alternative London interval, weekday subset, displacement threshold, horizon, ML, risk/leverage or SMC gate is authorized.
