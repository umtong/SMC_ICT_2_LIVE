from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

Side = Literal[1, -1]


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


def next_event_entry_index(touch_index: int, bar_count: int) -> int | None:
    candidate = touch_index + 1
    return candidate if 0 <= candidate < bar_count else None


def target_crossed(side: Side, bar: Bar, target: float, trade_through_bps: float) -> bool:
    offset = trade_through_bps / 10_000
    threshold = target * (1 + side * offset)
    tolerance = max(abs(target), 1.0) * 1e-12
    return bar.high > threshold + tolerance if side == 1 else bar.low < threshold - tolerance


def stop_crossed(side: Side, bar: Bar, stop: float) -> bool:
    return bar.low <= stop if side == 1 else bar.high >= stop


def conservative_exit(
    side: Side,
    bar: Bar,
    stop: float,
    target: float,
    trade_through_bps: float,
) -> Literal["stop", "target"] | None:
    if stop_crossed(side, bar, stop):
        return "stop"
    if target_crossed(side, bar, target, trade_through_bps):
        return "target"
    return None


def adverse_gap_stop_price(
    side: Side,
    bar_open: float,
    stop: float,
    stop_slippage_bps: float,
) -> float:
    slippage = stop_slippage_bps / 10_000
    normal = stop * (1 - side * slippage)
    if side == 1 and bar_open < stop:
        return min(normal, bar_open * (1 - slippage))
    if side == -1 and bar_open > stop:
        return max(normal, bar_open * (1 + slippage))
    return normal


def select_non_overlapping(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    chosen: list[tuple[int, int]] = []
    busy_until = -1
    for entry, exit_ in sorted(intervals):
        if entry <= busy_until:
            continue
        chosen.append((entry, exit_))
        if exit_ < 0:
            break
        busy_until = exit_
    return chosen
