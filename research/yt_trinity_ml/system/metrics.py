from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp, log
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .execution import AccountState, ClosedTrade


@dataclass(frozen=True)
class AccountMetrics:
    start_nav: float
    end_nav: float
    account_multiple: float
    total_return: float
    calendar_days: int
    geometric_daily_growth: float
    maximum_drawdown: float
    completed_trades: int
    win_rate: float | None
    profit_factor: float | None
    median_trade_return: float | None
    top_five_positive_pnl_share: float | None
    winner_removal_return: float | None
    liquidated_or_invalid: bool

    def as_dict(self) -> dict[str, float | int | bool | None]:
        return asdict(self)


def _max_drawdown(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(values)
    drawdowns = 1 - values / peaks
    return float(np.nanmax(drawdowns))


def _trade_statistics(trades: Sequence[ClosedTrade], start_nav: float) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    if not trades:
        return None, None, None, None, None
    pnl = np.array([trade.net_pnl for trade in trades], dtype=float)
    returns = np.array([trade.net_return_on_entry_equity for trade in trades], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    win_rate = float(np.mean(pnl > 0))
    profit_factor = float(wins.sum() / -losses.sum()) if losses.size and -losses.sum() > 0 else (float("inf") if wins.size else None)
    median = float(np.median(returns))
    if wins.size:
        top_five_share = float(np.sort(wins)[-5:].sum() / wins.sum())
        largest_winner = float(wins.max())
        winner_removal_return = float((pnl.sum() - largest_winner) / start_nav)
    else:
        top_five_share = None
        winner_removal_return = float(pnl.sum() / start_nav)
    return win_rate, profit_factor, median, top_five_share, winner_removal_return


def summarize_account(
    account: AccountState,
    evaluation_start: pd.Timestamp,
    evaluation_end_exclusive: pd.Timestamp,
    final_mark_price: float,
) -> AccountMetrics:
    if evaluation_start.tz is None or evaluation_end_exclusive.tz is None:
        raise ValueError("evaluation boundaries must be timezone aware")
    if evaluation_end_exclusive <= evaluation_start:
        raise ValueError("evaluation end must follow start")
    calendar_days = int((evaluation_end_exclusive - evaluation_start) / pd.Timedelta(days=1))
    if calendar_days <= 0:
        raise ValueError("evaluation must include at least one calendar day")

    final_unrealized = 0.0
    if account.position is not None:
        position = account.position
        final_unrealized = position.side * position.open_quantity * (final_mark_price - position.average_entry_price)
    end_nav = float(account.cash) + final_unrealized
    if end_nav <= 0:
        geometric = -1.0
    else:
        geometric = exp(log(end_nav / account.initial_nav) / calendar_days) - 1

    daily = [record for record in account.daily_nav if evaluation_start < record.day_end_utc <= evaluation_end_exclusive]
    nav_values = [account.initial_nav, *[record.nav for record in daily], end_nav]
    win_rate, pf, median, top_share, removal = _trade_statistics(account.closed_trades, account.initial_nav)
    return AccountMetrics(
        start_nav=account.initial_nav,
        end_nav=end_nav,
        account_multiple=end_nav / account.initial_nav,
        total_return=end_nav / account.initial_nav - 1,
        calendar_days=calendar_days,
        geometric_daily_growth=geometric,
        maximum_drawdown=_max_drawdown(np.asarray(nav_values, dtype=float)),
        completed_trades=len(account.closed_trades),
        win_rate=win_rate,
        profit_factor=pf,
        median_trade_return=median,
        top_five_positive_pnl_share=top_share,
        winner_removal_return=removal,
        liquidated_or_invalid=account.invalid,
    )


def select_pre2024_configuration(results: Iterable[tuple[str, AccountMetrics]]) -> tuple[str, AccountMetrics]:
    valid = [
        (identifier, metrics)
        for identifier, metrics in results
        if not metrics.liquidated_or_invalid and metrics.end_nav > 0
    ]
    if not valid:
        raise ValueError("no nonliquidated configuration")
    # Growth is never clipped at the 1% project target. Concentration and drawdown
    # break near-ties but cannot rescue weak growth.
    return max(
        valid,
        key=lambda item: (
            item[1].geometric_daily_growth,
            item[1].account_multiple,
            item[1].winner_removal_return if item[1].winner_removal_return is not None else float("-inf"),
            -item[1].maximum_drawdown,
            item[1].completed_trades,
        ),
    )
