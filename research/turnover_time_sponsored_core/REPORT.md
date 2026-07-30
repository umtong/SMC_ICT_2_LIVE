# Turnover-time sponsored external-range acceptance Core — fatal screen

## Decision

`RES-20260730-TURNOVER-TIME-SPONSORED-CORE-001` is `RETIRED_2022_TURNOVER_TIME_SPONSORED_CORE_FAILURE`.

BTCUSDT and ETHUSDT are testbeds for one market-invariant question: does unusually fast completion of a normal-hour quantity of business, ending beyond a pre-existing external range, identify accepted new price strongly enough to produce a repeatable +1.5R day-trading Core?

## Logic and fixed implementation

- Each UTC day freezes one packet-turnover target from the median turnover of the preceding 168 complete clock hours.
- Completed one-minute bars form non-overlapping packets. Packets never cross a UTC day, minutes are never reused, overshoot is not carried and incomplete day-end packets are discarded.
- Sponsorship uses the inherited `intensity_z >= 2.2706072565238586`; no threshold is refit.
- A completed sponsored packet closing outside the prior 96 completed turnover packets creates the only action.
- Entry is the first later observable one-minute open after decision +500 ms.
- Stop is 2 prior-only packet ATR; full target is +1.5R; opposite prior-48-packet close is state loss.
- Actual signed funding, adverse ambiguity, 0.5% current-NAV structural loss, 3x cap and one global BTC/ETH slot are fixed.
- There is no elapsed-time, session, UTC-day, year or research-stage strategy close.

## Programization validation

A year-boundary audit found a potential semantic defect: a natural strategy outcome after the requested calendar boundary could have been imported into that year’s completed-trade account. The final authority instead marks the open exposure at the last observable price, leaves it incomplete and retains the slot. Re-running the complete tape after this repair did not change any of the 21 scientific files, so no selected 2021/2022 account path had depended on the defect.

Seven semantic tests pass, including strict packet construction, shifted state, +500ms entry, signed funding, global-slot rerouting and year-boundary marking. Two fresh complete processes generated all 21 scientific outputs byte-identically. The plain-text source imports and compiles without local datasets, and GitHub Actions workflow run `30552721014` passed. Calendar 2023 was neither loaded nor packetized because the 2022 gate failed.

## Event breadth

- packets: BTC 2021 `10799`, ETH 2021 `8739`, BTC 2022 `11959`, ETH 2022 `11701`;
- sponsored external-range events: 2021 BTC `145`, ETH `104`; 2022 BTC `111`, ETH `116`.

## 2022 fixed fatal screen

| Cost | Trades | NAV multiple | PF | Median trade | H1 | H2 |
|---:|---:|---:|---:|---:|---:|---:|
| 0bp | 135 | 1.061414x | 1.1539 | -0.4898% | 1.067334x | 0.994454x |
| 12bp | 135 | 1.009985x | 1.0256 | -0.4908% | 1.041253x | 0.969971x |
| 18bp | 135 | 0.987969x | 0.9688 | -0.4912% | 1.029628x | 0.959540x |
| 24bp | 135 | 0.967932x | 0.9159 | -0.4916% | 1.018811x | 0.950060x |

At 24bp the account ended at `9679.32` USDT, geometric daily growth was `-0.008929%`, and daily MDD was `7.93%`.

Deleting the five largest positive parent events before complete slot rerouting left `131` trades, `0.943050x`, PF `0.8481` and geometric daily growth `-0.016063%`.

## Interpretation

The event was neither sparse nor jackpot-dominated. A weak gross relation existed, but it was only near break-even at 12bp, failed at 18/24bp, had a negative median and reversed from positive H1 to negative H2. Post-outcome symbol/side exceptions are prohibited.

The result therefore rejects this exact turnover-time translation as the missing Core. It does not reject the broader observation that high-participation external-price acceptance can contain information; it shows that the inherited sponsorship threshold and +1.5R action do not become robust merely by replacing clock time with turnover time.

Do not rescue with another packet target, z threshold, range scale, target, stop, channel, symbol side, lower cost, ML, risk or leverage. Calendar 2023 and official 2024–2026 remain sealed. No credentials or orders were used.
