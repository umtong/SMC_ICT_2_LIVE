# Scale-invariance fatal screen for sponsored external-range acceptance Core

## Decision

`RETIRED_PRE2024_SCALE_INVARIANCE_FAILURE` for the exact pooled policy. The result is **positive weak Core evidence**, not a rank-eligible or official-period system: it is broad and winner-resistant, but it does not keep the same cost-after sign in every pre-2024 year and its typical trade remains negative.

## Logic tested

BTC and ETH were treated only as test markets. A completed hourly auction closing beyond a pre-existing 24/48/96/192-hour range with inherited exceptional participation was interpreted as possible new-price acceptance. One product-neutral policy entered after 500 ms, realized the full position at +1.5R, and exited earlier only on hard structural invalidation or a completed hourly close back inside the exact consumed boundary. No symbol-side or best-scale selection, ML, runner, elapsed-time exit, risk search, or official-period replay was allowed.

## Programization audit before outcome interpretation

- Canonical ZIP CRC, manifest SHA, member SHA, dataset identity, continuous 1h/1m clocks and availability clocks were verified.
- The state-loss execution minute no longer reuses its later high/low. Adverse stop gaps use the observed open; favorable target gaps are capped at the frozen target; otherwise state loss exits at the open.
- Linear-contract quantity uses structural stop distance, entry/stop fee reserve and a 2 bp funding reserve. Realized entry/exit fees and actual signed funding are charged exactly once.
- Seven focused synthetic tests passed. Two fresh full executions produced 15 byte-identical outputs.

## Candidate surface

- Parent events: **638** (2021 188, 2022 211, 2023 239).
- Scale counts: 24h 102, 48h 85, 96h 114, 192h 337.
- BTC/ETH and long/short were all eligible under one rule; simultaneous candidates competed for one global slot.

## Continuous account results

| Cost | Multiple | Daily geometric growth | Trades | PF | Median trade | MDD | Winner-deleted multiple |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 12 bp | 1.293650x | 0.023516% | 353 | 1.3584 | -0.159716% | 3.777301% | 1.233594x |
| 18 bp | 1.221881x | 0.018302% | 353 | 1.2747 | -0.169676% | 4.512644% | 1.152533x |
| 24 bp | 1.158984x | 0.013475% | 353 | 1.1995 | -0.177187% | 5.284800% | 1.114188x |

### Principal 24 bp path

- Ending NAV: **11589.84 USDT** from 10,000; total multiple **1.158984x**.
- 353 completed/marked trades, 145 positive; median hold 6.00 h; slot occupancy 28.402334%.
- Top-five positive-PnL share **4.309686%**; top-10%-positive share **12.551272%**. This is not a few-jackpot path.
- Exact top-10%-positive parent deletion followed by full rerouting retained **1.114188x** and PF **1.1408**.

### Year stability at 24 bp

| Year | Return | Trades | PF | Median |
|---:|---:|---:|---:|---:|
| 2021 | 8.674465% | 120 | 1.3821 | -0.163727% |
| 2022 | 7.276392% | 106 | 1.3207 | -0.158661% |
| 2023 | -0.586427% | 127 | 0.9788 | -0.202621% |

2021 and 2022 were positive, but unchanged 2023 was **-0.586427%** with PF below one. The failure is therefore not trade scarcity or jackpot concentration; the same accepted-delivery interpretation did not retain its sign across regimes.

### Scale decomposition at 24 bp

| Largest consumed scale | Trades | PnL | PF | Median |
|---:|---:|---:|---:|---:|
| 24 h | 65 | 218.37 | 1.1510 | -0.179278% |
| 48 h | 51 | -90.83 | 0.9238 | -0.206682% |
| 96 h | 63 | 33.97 | 1.0242 | -0.175349% |
| 192 h | 174 | 1428.33 | 1.3638 | -0.159521% |

The positive effect was not confined to the inherited 96-hour scale: pooled sub-96h and >=96h families were both positive. However, every scale had a negative median and the 48-hour scale was negative. This supports a weak participation/acceptance tendency, not a completed scale-invariant Core.

## Noncausal information-family upper bound

A future-knowing exact interval-scheduling oracle selected enter/flat on the same 638 parents at 24 bp and 0.5% risk. It chose 173 non-overlapping positive actions, reached **2.811489x**, and only **0.094448% per day**—9.44% of the 1% target. This is not a strategy; it shows that classifier improvement alone cannot make this event family the complete target system.

## Why the exact policy is retired

- It is winner-resistant and positive overall, so the market tendency is not an alpha illusion caused by a few trades.
- It fails sign stability in 2023 at the principal 24 bp cost and has a negative typical trade.
- The 48-hour scale is negative, while 192-hour events supply most of the surplus; the mechanism is not yet invariant across nested scales.
- Even perfect future selection at discovery risk remains structurally far from the project objective.
- No scale, side, threshold, target, stop, ML, risk or leverage rescue is authorized from this exposed result.

## Research implication

The retained high-volume boundary family contains a small, broad cost-after effect, but exceptional completed business plus an outside close does not fully identify **who is sponsoring the new price** or whether that sponsorship will persist. The next useful information must observe a materially different causal payer—such as executable inventory replenishment/withdrawal, finalized forced inventory removal, or external spot/inventory demand—not another range lookback or candle confirmation.

## Reproduction fingerprints

- Implementation SHA-256: `eb4c28599fc072dd4a3f4410a128e17bf606089eb96ed2a7fd6a9b6209e01623`
- RESULT SHA-256: `3705126df6e68bb367b2f9ed5097808e96df98dd2aa370bce0fd055f4abd9bed`
- Candidate tape SHA-256: `4f32f36f056a33dbb39cd0d465488aefda8d541ef30667458ffa0392cf95ad96`
- Validation checks: **5751**, status `PASS`.
- Two-run file parity: **15 / 15** files identical.

No credentials, paper/testnet orders, live orders, official 2024-2026 replay, risk/leverage search or ranking change occurred.
