        "sweep_depth_atr": sweep_depth_atr,
        "reclaim_atr": reclaim_atr,
        "sweep_wick_fraction": sweep_wick_fraction,
        "displacement_body_atr": displacement_body_atr,
        "displacement_range_atr": displacement_range_atr,
        "displacement_close_extreme": close_extreme,
        "mss_break_atr": mss_break_atr,
        "setup_age_bars": float(setup_age_bars),
        "fvg_size_atr": fvg_size_atr,
        "stop_distance_atr": stop_distance / atr if atr > 0 else math.nan,
        "target_distance_atr": target_distance / atr if atr > 0 else math.nan,
        "rr": rr,
        "entry_vs_close_atr": direction * (float(row["close"]) - entry) / atr if atr > 0 else math.nan,
    }
    signed_columns = (
        "premium_discount_4h",
        "trend_ema_atr",
        "return_1",
        "return_3",
        "return_6",
        "return_12",
        "return_48",
        "return_288",
        "relative_return_3",
        "relative_return_12",
        "basis_pct",
        "account_imbalance",
        "oi_change_1",
        "oi_change_12",
        "funding_funding_rate",
        "peer_return_1",
        "peer_return_3",
        "peer_return_12",
        "peer_trend_ema_atr",
        "peer_premium_discount_4h",
    )
    unsigned_columns = (
        "atr_pct",
        "rv_12",
        "rv_48",
        "range_atr",
        "body_atr",
        "volume_z",
        "range_position_24h",
        "peer_range_atr",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
        "session_asia",
        "session_london",
        "session_new_york",
    )
    for column in signed_columns:
        values[f"signed_{column}"] = direction * float(row.get(column, math.nan))
    for column in unsigned_columns:
        values[column] = float(row.get(column, math.nan))
    return values


def generate_candidates(frame: pd.DataFrame, config: StructuralConfig) -> list[Candidate]:
    """Create candidates from the strict sweep→displacement→MSS sequence."""
    if frame.empty:
        return []
    required = {"start_time_ms", "available_at_ms", "open", "high", "low", "close", "atr", "symbol"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"candidate feature frame missing {sorted(missing)}")
    records = frame.reset_index(drop=True)
    candidates: list[Candidate] = []
    sweep_state: dict[int, dict[str, Any] | None] = {1: None, -1: None}
    for i in range(max(config.internal_structure_lookback + 1, 2), len(records)):
        row = records.iloc[i]
        previous = records.iloc[i - 1]
        atr = float(row["atr"])
        if not np.isfinite(atr) or atr <= 0:
            continue

        for direction in (1, -1):
            state = sweep_state[direction]
            if state is not None and i - int(state["sweep_index"]) > config.sweep_max_age_bars:
                sweep_state[direction] = None

        low_levels = {
            "confirmed_swing": float(row.get("swing_low", math.nan)),
            "equal_liquidity": float(row.get("equal_low", math.nan)),
            "prior_day": float(row.get("prior_day_low", math.nan)),
            "dealing_range_4h": float(row.get("dealing_low_4h", math.nan)),
        }
        high_levels = {
            "confirmed_swing": float(row.get("swing_high", math.nan)),
            "equal_liquidity": float(row.get("equal_high", math.nan)),
            "prior_day": float(row.get("prior_day_high", math.nan)),
            "dealing_range_4h": float(row.get("dealing_high_4h", math.nan)),
        }
        previous_close = float(previous["close"])
        selected_low = _select_level(previous_close, low_levels, 1)
        selected_high = _select_level(previous_close, high_levels, -1)

        if selected_low is not None:
            source, level = selected_low
            depth = level - float(row["low"])
            if depth >= config.sweep_min_depth_atr * atr and float(row["close"]) > level:
                internal = records.iloc[max(0, i - config.internal_structure_lookback):i]["high"].max()
                sweep_state[1] = {
                    "sweep_index": i,
                    "level": level,
                    "source": source,
                    "extreme": float(row["low"]),
                    "internal_break": float(internal),
                    "depth_atr": depth / atr,
                    "reclaim_atr": (float(row["close"]) - level) / atr,
                    "wick_fraction": float(row.get("lower_wick_fraction", math.nan)),
                }
        if selected_high is not None:
            source, level = selected_high
            depth = float(row["high"]) - level
            if depth >= config.sweep_min_depth_atr * atr and float(row["close"]) < level:
                internal = records.iloc[max(0, i - config.internal_structure_lookback):i]["low"].min()
                sweep_state[-1] = {
                    "sweep_index": i,
                    "level": level,
                    "source": source,
                    "extreme": float(row["high"]),
                    "internal_break": float(internal),
                    "depth_atr": depth / atr,
                    "reclaim_atr": (level - float(row["close"])) / atr,
                    "wick_fraction": float(row.get("upper_wick_fraction", math.nan)),
                }

        for direction in (1, -1):
            state = sweep_state[direction]
            if state is None:
                continue
            age = i - int(state["sweep_index"])
            if age < 0 or age > config.sweep_max_age_bars:
                continue
            body_signed = direction * float(row["body_signed"])
            body_atr = body_signed / atr
            range_atr = float(row["range_atr"])
            close_location = float(row["close_location"])
            directional_close_location = close_location if direction == 1 else 1.0 - close_location
            break_distance = direction * (float(row["close"]) - float(state["internal_break"]))
            if not (
                body_atr >= config.displacement_body_atr
                and range_atr >= config.displacement_range_atr
                and directional_close_location >= config.displacement_close_location
                and break_distance > 0
            ):
                continue

            if direction == 1:
                stop = float(state["extreme"]) - config.stop_buffer_atr * atr
                target_levels = high_levels
            else:
                stop = float(state["extreme"]) + config.stop_buffer_atr * atr
                target_levels = low_levels

            target_pick = _select_target(float(row["close"]), target_levels, direction)
            if target_pick is None or direction * (target_pick[1] - float(row["close"])) < config.min_target_distance_atr * atr:
                target_source = "atr_fallback"
                target = float(row["close"]) + direction * config.fallback_target_atr * atr
            else:
                target_source, target = target_pick

            gap_size = 0.0
            limit_entry = math.nan
            if i >= 2:
                two_back = records.iloc[i - 2]
                if direction == 1 and float(row["low"]) > float(two_back["high"]):
                    gap_low, gap_high = float(two_back["high"]), float(row["low"])
                    gap_size = gap_high - gap_low
                    limit_entry = (gap_low + gap_high) / 2.0
                elif direction == -1 and float(row["high"]) < float(two_back["low"]):
                    gap_low, gap_high = float(row["high"]), float(two_back["low"])
                    gap_size = gap_high - gap_low
                    limit_entry = (gap_low + gap_high) / 2.0
            if not np.isfinite(limit_entry):
                start = max(int(state["sweep_index"]), i - 4)
                sequence = records.iloc[start:i]
                opposite = sequence[sequence["body_signed"] * direction < 0]
                if not opposite.empty:
                    ob = opposite.iloc[-1]
                    limit_entry = (float(ob["open"]) + float(ob["close"])) / 2.0

            setup_id = f"{row['symbol']}:{int(row['available_at_ms'])}:{'L' if direction == 1 else 'S'}:{state['source']}"
            activation_ms = int(row["available_at_ms"]) + 500
            entries: list[tuple[str, float]] = []
            if config.make_market_candidates:
                entries.append(("confirmation_market", float(row["close"])))
            if config.make_limit_candidates and np.isfinite(limit_entry):
                if direction == 1 and stop < limit_entry < float(row["close"]):
                    entries.append(("fvg_ob_limit", float(limit_entry)))
                elif direction == -1 and float(row["close"]) < limit_entry < stop:
                    entries.append(("fvg_ob_limit", float(limit_entry)))

            for entry_mode, entry in entries:
                stop_distance = direction * (entry - stop)
                target_distance = direction * (target - entry)
                if stop_distance <= 0 or target_distance <= 0:
                    continue
                rr = target_distance / stop_distance
                if rr < config.min_rr or rr > config.max_rr:
                    continue
                feature_values = _candidate_feature_values(
                    row,
                    direction=direction,
                    entry_mode=entry_mode,
                    liquidity_source=str(state["source"]),
                    target_source=target_source,
                    sweep_depth_atr=float(state["depth_atr"]),
                    reclaim_atr=float(state["reclaim_atr"]),
                    sweep_wick_fraction=float(state["wick_fraction"]),
                    displacement_body_atr=body_atr,
                    displacement_range_atr=range_atr,
                    close_extreme=directional_close_location,
                    mss_break_atr=break_distance / atr,
                    setup_age_bars=age,
                    fvg_size_atr=gap_size / atr,
                    entry=entry,
