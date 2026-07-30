# Cross-venue sponsorship Core/Expansion action-value policy

**Result:** `RES-20260730-XVENUE-SPONSORSHIP-CORE-EXPANSION-001`  
**Decision:** `RETIRED_2023_XVENUE_SENSOR_BASELINE_INFERIOR_EXPANSION_ONLY`  

## Question

The exact high-volume 96-hour Bybit external-boundary event was held fixed. The only new information was completed Binance USD-M directional taker flow and price progress at the original breakout-hour decision. One fixed Ridge chose the unchanged `CORE`, unchanged protected-boundary `EXPANSION`, or flat action.

## Programization and dependency parity

- All-channel candidate counts reproduced `{2021: 538, 2022: 511, 2023: 369, 2024: 578, 2025: 598, 2026: 261}`.
- Selected high-volume event counts reproduced `{2021: 79, 2022: 101, 2023: 146, 2024: 110, 2025: 113, 2026: 50}`.
- The protected-boundary 24-bp fixed-risk path reproduced 2022 `1.219035x` and unchanged 2023 `1.313189x`.
- The original `+1.5R` Core reproduced 2022 `1.087189x`.
- The two-second external-source allowance plus fixed 500 ms never permits execution in the decision minute.
- No official-period sensor result was opened.

## Sensor breadth

The deterministic sign state was almost constant: global acceptance occurred in `99/101` 2022 events and `145/146` 2023 events. It therefore did not separate local stop-runs from market-wide acceptance.

## Untouched 2023 account comparison at 24 bp

| Policy | Multiple | Trades | PF | Median | MDD | Winner-deleted |
|---|---:|---:|---:|---:|---:|---:|
| Always Core | 1.042954x | 106 | 1.164 | 0.3813% | 4.72% | 0.982342x |
| Always Expansion | 1.313189x | 50 | 2.670 | -0.4300% | 4.79% | 1.102822x |
| Bybit-only Ridge | 1.207232x | 48 | 2.408 | -0.2531% | 4.92% | 1.086752x |
| Cross-venue Ridge | 1.192357x | 47 | 2.336 | -0.2769% | 4.81% | 1.224247x |

The cross-venue Ridge remained positive, but it underperformed the constant Expansion path and the Bybit-only Ridge. Its median trade was negative and the top five winners supplied `83.59%` of positive PnL. The exact winner-deletion/rerouting path remained positive because removed trades freed the slot for different candidates; that does not repair the ordinary-policy baseline inferiority.

## Model diagnosis

- Cross-venue MAE/MSE/Spearman: `0.00878481` / `0.00041150` / `0.1105`.
- Bybit-only MAE/MSE/Spearman: `0.00859866` / `0.00041343` / `0.1003`.
- Action-constant MAE/MSE: `0.00899419` / `0.00040210`.

Binance taker flow mostly described the same completed displacement already visible in the Bybit event. It did not reveal the local absorption, replenishment or future protected-delivery persistence needed to route Core versus Expansion.

## Decision

Retire this exact cross-venue sponsorship sensor. Do not tune flow horizons, thresholds, model, action map, target, channel, risk, leverage, cost or official-period filters. Preserve the protected-boundary route as Expansion only. A new Core must come from a materially different observable economic state.

No credentials, paper orders, testnet orders or live orders were used.
