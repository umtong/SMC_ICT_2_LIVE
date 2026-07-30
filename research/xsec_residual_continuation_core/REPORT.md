# Four-asset idiosyncratic residual acceptance-continuation fatal screen

## Decision

`RES-20260730-XSEC-RESIDUAL-CONTINUATION-CORE-001` is **RETIRED_PRE2024_RESIDUAL_CONTINUATION_FAILURE_WITH_PARTIAL_PARENT_PARITY**.

The already-frozen six-hour idiosyncratic residual event was tested as accepted price discovery rather than reversion. Threshold, horizon, rearm, universe, latency, stop, costs, risk, leverage and one-slot routing were unchanged.

## Event/action counts

- 2022 raw / continuation outcomes: **725 / 725**
- 2023 raw / continuation outcomes: **696 / 696**

## Primary 24-bp results

- 2022: **0.802037x**, 494 completed trades, PF **0.6411**, median **-0.0519%**, H1/H2 **-10.49% / -10.39%**, exact top-five-deleted full reroute **0.748000x**.
- 2023 unchanged: **0.784044x**, 489 completed trades, PF **0.6401**, median **-0.0797%**, H1/H2 **-17.53% / -4.93%**, exact top-five-deleted full reroute **0.655091x**.

Both years were already negative at 12 bp. This is not a sample-size or a few-jackpot failure: the continuation action was broad, negative-median and below one after exact winner deletion. ML, risk/leverage search and official 2024-2026 were not opened.

## Parent-event programization parity

The #570 overshoot-fade implementation was registered by a local source hash but was not transported as reusable code. Independent reconstruction achieved exact 2023 event/trade counts and close ordinary economics: 484 trades, 0.827194x and PF 0.6659 versus the reference 484 trades, 0.8294x and PF 0.667. The 2022 reconstruction produced 26 additional raw events.

To keep the economic judgment separate from that implementation drift, the first 26 reconstructed 2022 candidates were removed and the entire slot path rerouted. Continuation still ended at **0.800212x**, and exact top-five deletion ended at **0.748455x**. The unchanged 2023 path remained **0.784044x / 0.655091x rerouted**.

Therefore the continuation failure is robust, but this branch does not claim byte-exact reproduction of the parent 2022 event tape. The programization limitation is preserved rather than hidden.

## Consequence

The exact six-hour idiosyncratic residual family is closed in both economic directions: the previously tested fade and this accepted-continuation action. Do not rescue it with another residual horizon, z threshold, rearm, target fraction, hard stop, symbol subset, session, cost, risk, leverage or ML model.

No credentials, paper orders, testnet orders or live orders were used.
