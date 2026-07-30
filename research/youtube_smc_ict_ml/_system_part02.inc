        merged = merged.drop(columns=[source_time])
    return merged.sort_values("start_time_ms").reset_index(drop=True)


def build_symbol_features(data: SymbolData, config: StructuralConfig) -> pd.DataFrame:
    frame = data.five_minute.copy()
    required = {"start_time_ms", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{data.symbol} 5m bars missing columns: {sorted(missing)}")
    complete_column = "is_complete" if "is_complete" in frame.columns else "observed"
    if complete_column in frame.columns:
        frame = frame.loc[frame[complete_column].fillna(False).astype(bool)].copy()
    frame = frame.sort_values("start_time_ms").reset_index(drop=True)
    if "available_at_ms" not in frame.columns:
        frame["available_at_ms"] = frame["start_time_ms"].astype("int64") + MS_5MIN
    for column in ("open", "high", "low", "close", "volume", "turnover"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.ewm(alpha=1.0 / config.atr_period, adjust=False, min_periods=config.atr_period).mean()
    frame["range"] = frame["high"] - frame["low"]
    frame["body"] = (frame["close"] - frame["open"]).abs()
    frame["body_signed"] = frame["close"] - frame["open"]
    frame["upper_wick"] = frame["high"] - frame[["open", "close"]].max(axis=1)
    frame["lower_wick"] = frame[["open", "close"]].min(axis=1) - frame["low"]
    frame["body_atr"] = safe_divide(frame["body"], frame["atr"])
    frame["range_atr"] = safe_divide(frame["range"], frame["atr"])
    frame["close_location"] = safe_divide(frame["close"] - frame["low"], frame["range"])
    frame["lower_wick_fraction"] = safe_divide(frame["lower_wick"], frame["range"])
    frame["upper_wick_fraction"] = safe_divide(frame["upper_wick"], frame["range"])

    log_volume = np.log1p(frame["volume"].clip(lower=0))
    volume_mean = log_volume.rolling(config.volume_z_window, min_periods=max(12, config.volume_z_window // 4)).mean()
    volume_std = log_volume.rolling(config.volume_z_window, min_periods=max(12, config.volume_z_window // 4)).std(ddof=0)
    frame["volume_z"] = safe_divide(log_volume - volume_mean, volume_std)
    turnover = frame.get("turnover", frame["volume"] * frame["close"])
    frame["turnover"] = turnover

    for lag in (1, 3, 6, 12, 48, 288):
        frame[f"return_{lag}"] = np.log(frame["close"] / frame["close"].shift(lag))
    frame["rv_12"] = frame["return_1"].rolling(12, min_periods=6).std(ddof=0)
    frame["rv_48"] = frame["return_1"].rolling(48, min_periods=12).std(ddof=0)
    frame["atr_pct"] = safe_divide(frame["atr"], frame["close"])

    highs = frame["high"].to_numpy(float)
    lows = frame["low"].to_numpy(float)
    atr = frame["atr"].to_numpy(float)
    last_high, last_low, equal_high, equal_low = _confirmed_pivots(
        highs,
        lows,
        atr,
        left=config.pivot_left,
        right=config.pivot_right,
        equal_tolerance_atr=config.equal_level_tolerance_atr,
    )
    frame["swing_high"] = last_high
    frame["swing_low"] = last_low
    frame["equal_high"] = equal_high
    frame["equal_low"] = equal_low

    timestamps = pd.to_datetime(frame["start_time_ms"], unit="ms", utc=True)
    frame["date"] = timestamps.dt.floor("D")
    day_agg = frame.groupby("date", sort=True).agg(day_high=("high", "max"), day_low=("low", "min"), day_open=("open", "first"), day_close=("close", "last"))
    day_agg[["prior_day_high", "prior_day_low", "prior_day_open", "prior_day_close"]] = day_agg[["day_high", "day_low", "day_open", "day_close"]].shift(1).to_numpy()
    frame = frame.merge(day_agg[["prior_day_high", "prior_day_low", "prior_day_open", "prior_day_close"]], left_on="date", right_index=True, how="left")

    rolling_high_4h = frame["high"].rolling(48, min_periods=24).max().shift(1)
    rolling_low_4h = frame["low"].rolling(48, min_periods=24).min().shift(1)
    rolling_high_24h = frame["high"].rolling(288, min_periods=96).max().shift(1)
    rolling_low_24h = frame["low"].rolling(288, min_periods=96).min().shift(1)
    frame["dealing_high_4h"] = rolling_high_4h
    frame["dealing_low_4h"] = rolling_low_4h
    frame["dealing_mid_4h"] = (rolling_high_4h + rolling_low_4h) / 2.0
    frame["premium_discount_4h"] = safe_divide(frame["close"] - frame["dealing_mid_4h"], rolling_high_4h - rolling_low_4h)
    frame["range_position_24h"] = safe_divide(frame["close"] - rolling_low_24h, rolling_high_24h - rolling_low_24h)
    frame["ema_fast"] = frame["close"].ewm(span=12, adjust=False, min_periods=12).mean()
    frame["ema_slow"] = frame["close"].ewm(span=48, adjust=False, min_periods=48).mean()
    frame["trend_ema_atr"] = safe_divide(frame["ema_fast"] - frame["ema_slow"], frame["atr"])

    frame["hour_sin"] = np.sin(2 * np.pi * timestamps.dt.hour / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * timestamps.dt.hour / 24.0)
    frame["weekday_sin"] = np.sin(2 * np.pi * timestamps.dt.dayofweek / 7.0)
    frame["weekday_cos"] = np.cos(2 * np.pi * timestamps.dt.dayofweek / 7.0)
    frame["session_asia"] = timestamps.dt.hour.between(0, 7).astype(float)
    frame["session_london"] = timestamps.dt.hour.between(7, 13).astype(float)
    frame["session_new_york"] = timestamps.dt.hour.between(13, 21).astype(float)

    frame = _asof_feature(frame, data.open_interest_5m, stream_time="timestamp_ms", columns=("open_interest",), prefix="oi_")
    frame = _asof_feature(frame, data.account_ratio_5m, stream_time="timestamp_ms", columns=("buy_ratio", "sell_ratio"), prefix="acct_")
    frame = _asof_feature(frame, data.mark_minute, stream_time="start_time_ms", columns=("close",), prefix="mark_")
    frame = _asof_feature(frame, data.index_minute, stream_time="start_time_ms", columns=("close",), prefix="index_")
    frame = _asof_feature(frame, data.premium_minute, stream_time="start_time_ms", columns=("close",), prefix="premium_")
    frame = _asof_feature(frame, data.funding, stream_time="timestamp_ms", columns=("funding_rate",), prefix="funding_")
    if "oi_open_interest" in frame:
        frame["oi_change_1"] = frame["oi_open_interest"].pct_change(fill_method=None)
        frame["oi_change_12"] = frame["oi_open_interest"].pct_change(12, fill_method=None)
    else:
        frame["oi_change_1"] = np.nan
        frame["oi_change_12"] = np.nan
    if "acct_buy_ratio" in frame and "acct_sell_ratio" in frame:
        frame["account_imbalance"] = frame["acct_buy_ratio"] - frame["acct_sell_ratio"]
    else:
        frame["account_imbalance"] = np.nan
    if "mark_close" in frame and "index_close" in frame:
        frame["basis_pct"] = safe_divide(frame["mark_close"] - frame["index_close"], frame["index_close"])
    else:
        frame["basis_pct"] = np.nan
    if "funding_funding_rate" not in frame:
        frame["funding_funding_rate"] = np.nan
    frame["symbol"] = data.symbol
    return frame.drop(columns=["date"], errors="ignore")


def add_cross_asset_features(feature_frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    symbols = sorted(feature_frames)
    for symbol in symbols:
        frame = feature_frames[symbol].copy()
        peers = [peer for peer in symbols if peer != symbol]
        if not peers:
            for column in ("peer_return_1", "peer_return_3", "peer_return_12", "peer_range_atr", "relative_return_3", "relative_return_12"):
                frame[column] = np.nan
            result[symbol] = frame
            continue
        peer = peers[0]
        peer_frame = feature_frames[peer][["available_at_ms", "return_1", "return_3", "return_12", "range_atr", "trend_ema_atr", "premium_discount_4h"]].rename(
            columns={
                "return_1": "peer_return_1",
                "return_3": "peer_return_3",
                "return_12": "peer_return_12",
                "range_atr": "peer_range_atr",
                "trend_ema_atr": "peer_trend_ema_atr",
                "premium_discount_4h": "peer_premium_discount_4h",
            }
        )
        frame = pd.merge_asof(
            frame.sort_values("available_at_ms"),
            peer_frame.sort_values("available_at_ms"),
            on="available_at_ms",
            direction="backward",
            tolerance=MS_5MIN,
        ).sort_values("start_time_ms").reset_index(drop=True)
        frame["relative_return_3"] = frame["return_3"] - frame["peer_return_3"]
        frame["relative_return_12"] = frame["return_12"] - frame["peer_return_12"]
        result[symbol] = frame
    return result


def _select_level(previous_close: float, levels: Mapping[str, float], direction: int) -> tuple[str, float] | None:
    valid: list[tuple[str, float]] = []
    for source, level in levels.items():
        if not np.isfinite(level):
            continue
        if direction == 1 and level < previous_close:
            valid.append((source, float(level)))
        elif direction == -1 and level > previous_close:
            valid.append((source, float(level)))
    if not valid:
        return None
    if direction == 1:
        return max(valid, key=lambda item: item[1])
    return min(valid, key=lambda item: item[1])


def _select_target(entry: float, levels: Mapping[str, float], direction: int) -> tuple[str, float] | None:
    valid: list[tuple[str, float]] = []
    for source, level in levels.items():
        if not np.isfinite(level):
            continue
        if direction == 1 and level > entry:
            valid.append((source, float(level)))
        elif direction == -1 and level < entry:
            valid.append((source, float(level)))
    if not valid:
        return None
    if direction == 1:
        return min(valid, key=lambda item: item[1])
    return max(valid, key=lambda item: item[1])


def _candidate_feature_values(
    row: pd.Series,
    *,
    direction: int,
    entry_mode: str,
    liquidity_source: str,
    target_source: str,
    sweep_depth_atr: float,
    reclaim_atr: float,
    sweep_wick_fraction: float,
    displacement_body_atr: float,
    displacement_range_atr: float,
    close_extreme: float,
    mss_break_atr: float,
    setup_age_bars: int,
    fvg_size_atr: float,
    entry: float,
    stop: float,
    target: float,
) -> dict[str, Any]:
    atr = float(row["atr"])
    stop_distance = direction * (entry - stop)
    target_distance = direction * (target - entry)
    rr = target_distance / stop_distance if stop_distance > 0 else math.nan
    values: dict[str, Any] = {
        "symbol": row["symbol"],
        "entry_mode": entry_mode,
        "liquidity_source": liquidity_source,
        "target_source": target_source,
        "direction": float(direction),
