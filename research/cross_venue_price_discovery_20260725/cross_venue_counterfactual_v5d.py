from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import requests

import cross_venue_development_v2 as d2
import cross_venue_development_v5 as development
import cross_venue_execution_v5d as v5d
import cross_venue_pilot as v1
import cross_venue_pilot_v2 as v2

BASE_FEE = 5.0
DEVELOPMENT_DAYS = development.DEVELOPMENT_DAYS
EventKey = tuple[str, str, str, int, int]


def event_key(item) -> EventKey:
    return (
        str(item.day),
        str(item.symbol),
        str(item.family),
        int(item.decision_ms),
        int(item.side),
    )


def winner_keys(ledger: pd.DataFrame, fraction: float = 0.10) -> set[EventKey]:
    if ledger.empty:
        return set()
    count = max(1, int(math.ceil(len(ledger) * fraction)))
    selected = ledger.nlargest(count, "account_return")
    return {
        (
            str(row.day),
            str(row.symbol),
            str(row.family),
            int(row.decision_ms),
            int(row.side),
        )
        for row in selected.itertuples(index=False)
    }


def replay_without_events(
    config: v1.Config,
    removed: set[EventKey],
    cache: Path,
) -> float:
    v5d.patch_v5()
    state = v5d.initial_account_state()
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-v5d-counterfactual/1.0"
        for day in DEVELOPMENT_DAYS:
            frames: dict[tuple[str, str], pd.DataFrame] = {}
            for symbol in v1.SYMBOLS:
                frame, _records = v1.load_day(cache, session, day, symbol)
                frames[(day, symbol)] = frame
            events: list[v1.Event] = []
            for (event_day, symbol), frame in frames.items():
                events.extend(v2.signal_events_v2(frame, config, event_day, symbol))
            filtered = [item for item in events if event_key(item) not in removed]
            _trades, state = v5d.simulate_account_day_v5(
                frames,
                filtered,
                config,
                BASE_FEE,
                state,
            )
            if float(state.get("nav", 0.0)) <= 0:
                return -1.0
    return max(0.0, float(state["nav"])) / d2.INITIAL_NAV - 1.0
