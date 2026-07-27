                    stop=stop,
                    target=target,
                )
                candidate_id = f"{setup_id}:{entry_mode}"
                candidates.append(
                    Candidate(
                        candidate_id=candidate_id,
                        setup_id=setup_id,
                        symbol=str(row["symbol"]),
                        direction=direction,
                        signal_available_ms=int(row["available_at_ms"]),
                        activation_ms=activation_ms,
                        entry_mode=entry_mode,
                        planned_entry=entry,
                        stop_price=stop,
                        target_price=target,
                        liquidity_source=str(state["source"]),
                        target_source=target_source,
                        feature_values=feature_values,
                    )
                )
            sweep_state[direction] = None
    deduplicated: dict[str, Candidate] = {candidate.candidate_id: candidate for candidate in candidates}
    return sorted(deduplicated.values(), key=lambda c: (c.activation_ms, c.symbol, c.candidate_id))


def _observed_mask(frame: pd.DataFrame) -> np.ndarray:
    if "observed" in frame.columns:
        return frame["observed"].fillna(False).astype(bool).to_numpy()
    if "is_complete" in frame.columns:
        return frame["is_complete"].fillna(False).astype(bool).to_numpy()
    return frame[["open", "high", "low", "close"]].notna().all(axis=1).to_numpy()


def _adverse_price(price: float, direction: int, bps: float, *, is_entry: bool) -> float:
    rate = bps / 10_000.0
    if is_entry:
        return price * (1.0 + direction * rate)
    return price * (1.0 - direction * rate)


def _funding_arrays(data: SymbolData) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if data.funding.empty or "timestamp_ms" not in data.funding or "funding_rate" not in data.funding:
        return np.array([], dtype=np.int64), np.array([], dtype=float), np.array([], dtype=float)
    funding = data.funding.dropna(subset=["timestamp_ms", "funding_rate"]).sort_values("timestamp_ms")
    times = funding["timestamp_ms"].astype("int64").to_numpy()
    rates = funding["funding_rate"].astype(float).to_numpy()
    minute = data.mark_minute if not data.mark_minute.empty else data.minute
    minute_times = minute["start_time_ms"].astype("int64").to_numpy()
    minute_closes = minute["close"].astype(float).to_numpy()
    positions = np.searchsorted(minute_times, times, side="right") - 1
    marks = np.where(positions >= 0, minute_closes[np.maximum(positions, 0)], np.nan)
    return times, rates, marks


def _funding_cash_between(
    funding_times: np.ndarray,
    funding_rates: np.ndarray,
    funding_marks: np.ndarray,
    *,
    start_ms: int,
    end_ms: int,
    direction: int,
) -> float:
    left = int(np.searchsorted(funding_times, start_ms, side="left"))
    right = int(np.searchsorted(funding_times, end_ms, side="right"))
    if right <= left:
        return 0.0
    rates = funding_rates[left:right]
    marks = funding_marks[left:right]
    valid = np.isfinite(rates) & np.isfinite(marks)
    # Positive funding transfers from longs to shorts.
    return float(np.sum(-direction * rates[valid] * marks[valid]))


def simulate_candidate_plan(
    candidate: Candidate,
    data: SymbolData,
    execution: FeeExecutionConfig,
    *,
    end_exclusive_ms: int,
) -> TradePlan:
    minute = data.minute.sort_values("start_time_ms").reset_index(drop=True)
    times = minute["start_time_ms"].astype("int64").to_numpy()
    opens = minute["open"].astype(float).to_numpy()
    highs = minute["high"].astype(float).to_numpy()
    lows = minute["low"].astype(float).to_numpy()
    closes = minute["close"].astype(float).to_numpy()
    observed = _observed_mask(minute)
    funding_times, funding_rates, funding_marks = _funding_arrays(data)

    active_minute_ms = ceil_to_minute_ms(candidate.activation_ms)
    index = int(np.searchsorted(times, active_minute_ms, side="left"))
    while index < len(times) and (times[index] >= end_exclusive_ms or not observed[index]):
        if times[index] >= end_exclusive_ms:
            break
        index += 1
    if index >= len(times) or times[index] >= end_exclusive_ms:
        return TradePlan(candidate, end_exclusive_ms, "unresolved_no_observable_price", None, None, None, None, None, None, None, None, None, False, 0.0, None, None, None)

    direction = candidate.direction
    entry_index: int | None = None
    entry_price: float | None = None
    entry_fee_rate: float | None = None
    if candidate.entry_mode == "confirmation_market":
        entry_index = index
        entry_price = _adverse_price(float(opens[index]), direction, execution.market_slippage_bps, is_entry=True)
        entry_fee_rate = execution.taker_fee_rate
    else:
        penetration = max(execution.maker_penetration_bps, 0.0) / 10_000.0
        cursor = index
        while cursor < len(times) and times[cursor] < end_exclusive_ms:
            if not observed[cursor]:
                cursor += 1
                continue
            stop_hit = lows[cursor] <= candidate.stop_price if direction == 1 else highs[cursor] >= candidate.stop_price
            target_hit = highs[cursor] >= candidate.target_price if direction == 1 else lows[cursor] <= candidate.target_price
            if stop_hit:
                return TradePlan(candidate, int(times[cursor]), "canceled_structure_invalidated", None, None, None, None, None, None, None, None, None, True, 0.0, None, None, None)
            if target_hit:
                return TradePlan(candidate, int(times[cursor]), "canceled_objective_delivered", None, None, None, None, None, None, None, None, None, True, 0.0, None, None, None)
            if direction == 1:
                penetrated = lows[cursor] <= candidate.planned_entry * (1.0 - penetration)
            else:
                penetrated = highs[cursor] >= candidate.planned_entry * (1.0 + penetration)
            if penetrated:
                entry_index = cursor
                entry_price = candidate.planned_entry
                entry_fee_rate = execution.maker_fee_rate
                break
            cursor += 1
        if entry_index is None:
            return TradePlan(candidate, end_exclusive_ms, "pending_unresolved", None, None, None, None, None, None, None, None, None, False, 0.0, None, None, None)

    assert entry_price is not None and entry_index is not None and entry_fee_rate is not None
    exit_index: int | None = None
    exit_price: float | None = None
    exit_fee_rate: float | None = None
    exit_reason: str | None = None
    cursor = entry_index
    while cursor < len(times) and times[cursor] < end_exclusive_ms:
        if not observed[cursor]:
            cursor += 1
            continue
        if direction == 1:
            stop_hit = lows[cursor] <= candidate.stop_price
            target_hit = highs[cursor] >= candidate.target_price
        else:
            stop_hit = highs[cursor] >= candidate.stop_price
            target_hit = lows[cursor] <= candidate.target_price
        # Same-minute ambiguity is intentionally resolved against the strategy.
        if stop_hit:
            raw_stop = candidate.stop_price
            if direction == 1 and opens[cursor] < raw_stop:
                raw_stop = float(opens[cursor])
            elif direction == -1 and opens[cursor] > raw_stop:
                raw_stop = float(opens[cursor])
            exit_price = _adverse_price(raw_stop, direction, execution.stop_slippage_bps, is_entry=False)
            exit_fee_rate = execution.taker_fee_rate
            exit_index = cursor
            exit_reason = "stop"
            break
        if target_hit:
            exit_price = candidate.target_price
            exit_fee_rate = execution.maker_fee_rate
            exit_index = cursor
            exit_reason = "target"
            break
        cursor += 1

    stop_exit = _adverse_price(candidate.stop_price, direction, execution.stop_slippage_bps, is_entry=False)
    loss_budget_per_unit = -(
        direction * (stop_exit - entry_price)
        - entry_fee_rate * abs(entry_price)
        - execution.taker_fee_rate * abs(stop_exit)
    )
    loss_budget_per_unit = max(float(loss_budget_per_unit), 1e-12)
    if exit_index is None or exit_price is None or exit_fee_rate is None:
        return TradePlan(
            candidate,
            end_exclusive_ms,
            "open_unresolved",
            int(times[entry_index]),
            entry_index,
            entry_price,
            entry_fee_rate,
            None,
            None,
            None,
            None,
            None,
            False,
            _funding_cash_between(
                funding_times, funding_rates, funding_marks,
                start_ms=int(times[entry_index]), end_ms=end_exclusive_ms - 1, direction=direction,
            ),
            None,
            loss_budget_per_unit,
            None,
        )
    entry_time = int(times[entry_index])
    exit_time = int(times[exit_index])
    funding_cash = _funding_cash_between(
        funding_times,
        funding_rates,
        funding_marks,
        start_ms=entry_time,
        end_ms=exit_time,
        direction=direction,
    )
    net_cash = (
        direction * (exit_price - entry_price)
        - entry_fee_rate * abs(entry_price)
        - exit_fee_rate * abs(exit_price)
        + funding_cash
    )
    return TradePlan(
        candidate,
        exit_time,
        "filled_resolved",
