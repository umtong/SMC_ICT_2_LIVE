#!/usr/bin/env python3
"""Idempotently consolidate all causal research source invariants.

This exists to eliminate ordering risk between one-shot GitHub Actions that may
have started concurrently.  It applies only missing changes, verifies the final
text contracts, and removes the temporary materializers after the full test suite
has a single stable source surface.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, text: str) -> None:
    (ROOT / relative).write_text(text, encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> bool:
    text = read(relative)
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"anchor missing in {relative}: {old[:120]!r}")
    write(relative, text.replace(old, new, 1))
    return True


def ensure_cisd_datetime_and_stationarity() -> None:
    path = "research/yt_trinity_ml/run_cisd_bpr_ifvg_research.py"
    text = read(path)
    text = text.replace(
        'pd.to_datetime(frame[time_column], unit="ms", utc=True).as_unit("ns")',
        'pd.DatetimeIndex(pd.to_datetime(frame[time_column], unit="ms", utc=True)).as_unit("ns")',
    )
    if "ABSOLUTE_FEATURES = {" not in text:
        anchor = 'VARIANT_CODE = {"BPR": 1.0, "IFVG": 2.0, "CISD_FVG": 3.0}\n'
        block = '''VARIANT_CODE = {"BPR": 1.0, "IFVG": 2.0, "CISD_FVG": 3.0}\nABSOLUTE_FEATURES = {\n    "open", "high", "low", "close", "volume", "turnover", "mark_close", "body",\n    "ema_fast", "ema_slow", "ema_long", "vwap",\n    "confirmed_pivot_high", "confirmed_pivot_low", "last_swing_high", "last_swing_low",\n    "previous_day_high", "previous_day_low", "previous_week_high", "previous_week_low",\n    "bull_fvg_lower", "bull_fvg_upper", "bear_fvg_lower", "bear_fvg_upper",\n    "last_bull_fvg_lower", "last_bull_fvg_upper", "last_bear_fvg_lower", "last_bear_fvg_upper",\n    "decision_position", "ote_lower", "ote_upper",\n}\n'''
        if anchor not in text:
            raise RuntimeError("CISD variant anchor missing")
        text = text.replace(anchor, block, 1)
    old = '''        self.feature_names = [\n            name for name in ordered.columns\n            if name not in excluded and pd.api.types.is_numeric_dtype(ordered[name])\n        ]'''
    new = '''        self.feature_names = [\n            name for name in ordered.columns\n            if name not in excluded\n            and name not in ABSOLUTE_FEATURES\n            and pd.api.types.is_numeric_dtype(ordered[name])\n        ]'''
    if new not in text:
        if old not in text:
            raise RuntimeError("CISD model feature-selection anchor missing")
        text = text.replace(old, new, 1)
    write(path, text)


def ensure_frontend_fixes() -> None:
    probe = "research/yt_trinity_ml/probe_public_frontend_fleet.py"
    text = read(probe)
    if '"caption_syntax": caption_syntax' not in text:
        old = '''        meaningful = " ".join(text.split())\n        return {\n            "status": response.status_code,\n            "bytes": len(raw),\n            "characters": len(meaningful),\n            "content_type": response.headers.get("content-type"),\n            "sha256": hashlib.sha256(raw).hexdigest(),\n            "usable": response.status_code == 200 and len(meaningful) >= 80,\n        }'''
        new = '''        meaningful = " ".join(text.split())\n        lowered = text.lower()\n        caption_syntax = (\n            "webvtt" in lowered\n            or "-->" in text\n            or "<text" in lowered\n            or "<tt" in lowered\n            or '"events"' in lowered\n            or '"start_ms"' in lowered\n        )\n        return {\n            "status": response.status_code,\n            "bytes": len(raw),\n            "characters": len(meaningful),\n            "content_type": response.headers.get("content-type"),\n            "sha256": hashlib.sha256(raw).hexdigest(),\n            "caption_syntax": caption_syntax,\n            "usable": response.status_code == 200 and len(meaningful) >= 80 and caption_syntax,\n        }'''
        if old not in text:
            raise RuntimeError("frontend caption validation anchor missing")
        text = text.replace(old, new, 1)
        write(probe, text)

    workflow = ".github/workflows/yt-trinity-public-frontend-content.yml"
    text = read(workflow)
    if "os.environ['GITHUB_OUTPUT']" not in text:
        text = text.replace(
            "          import json\n          from pathlib import Path\n          candidates = []",
            "          import json\n          import os\n          from pathlib import Path\n          candidates = []",
            1,
        )
        text = text.replace(
            "          with open('${GITHUB_OUTPUT}', 'a', encoding='utf-8') as handle:",
            "          with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:",
            1,
        )
        write(workflow, text)


def route_tuples() -> list[tuple[str, str, str]]:
    return [
        ("cisd_bpr_ifvg", "YT_TRINITY_CISD_BPR_IFVG_ACTION_VALUE_V1", "CISD_BPR_IFVG_RUN_POINTER.json"),
        ("compression_bpr", "YT_TRINITY_COMPRESSION_BPR_CONTINUATION_ACTION_VALUE_V1", "COMPRESSION_BPR_RUN_POINTER.json"),
        ("smt_cisd", "YT_TRINITY_SMT_CISD_BPR_ACTION_VALUE_V1", "SMT_CISD_RUN_POINTER.json"),
        ("ifvg_failure", "YT_TRINITY_FAILED_DISPLACEMENT_IFVG_ACTION_VALUE_V1", "IFVG_FAILURE_RUN_POINTER.json"),
        ("htf_ote", "YT_TRINITY_HTF_OTE_FVG_ACTION_VALUE_V1", "HTF_OTE_RUN_POINTER.json"),
    ]


def ensure_selector_routes() -> None:
    path = "research/yt_trinity_ml/select_coarse_survivor.py"
    text = read(path)
    start = text.index("ROUTES = (")
    end = text.index("\n\n\ndef metrics_from", start)
    block = "ROUTES = (\n" + "".join(
        f'    ("{route}", "{strategy}", "{pointer}"),\n'
        for route, strategy, pointer in route_tuples()
    ) + ")"
    text = text[:start] + block + text[end:]
    text = text.replace("ALL_THREE_ECONOMIC_FAIL_SWITCH_ALPHA", "ALL_RESOLVED_ECONOMIC_FAIL_SWITCH_ALPHA")
    if "frozen pre-2024 sequential account" not in text:
        old = '''def positive_key(row: Mapping[str, Any]) -> tuple[float, float, float, float]:\n    metrics = row["official_metrics"]\n    return (\n        float(metrics.get("geometric_daily_growth") or 0.0),\n        float(metrics.get("account_multiple") or 0.0),\n        -float(metrics.get("maximum_drawdown") or 1.0),\n        float(metrics.get("completed_trades") or 0.0),\n    )'''
        new = '''def positive_key(row: Mapping[str, Any]) -> tuple[float, float, float, float]:\n    # H1 is only a survival gate. Magnitude selection remains owned by the\n    # frozen pre-2024 sequential account.\n    basic = row.get("selected_basic")\n    metrics = basic.get("metrics") if isinstance(basic, Mapping) else {}\n    if not isinstance(metrics, Mapping):\n        metrics = {}\n    return (\n        float(metrics.get("geometric_daily_growth") or 0.0),\n        float(metrics.get("account_multiple") or 0.0),\n        -float(metrics.get("maximum_drawdown") or 1.0),\n        float(metrics.get("completed_trades") or 0.0),\n    )'''
        if old not in text:
            raise RuntimeError("selector pre-2024 key anchor missing")
        text = text.replace(old, new, 1)
    write(path, text)


def ensure_full_routes() -> None:
    path = "research/yt_trinity_ml/run_full_sequential_survivor.py"
    text = read(path)
    imports = [
        "import run_compression_bpr_continuation as compression",
        "import run_htf_ote_continuation as htf_ote",
        "import run_ifvg_failure_research as ifvg_failure",
        "import run_smt_cisd_research as smt",
    ]
    import_anchor = "import run_cisd_bpr_ifvg_research as engine\n"
    for statement in imports:
        if statement not in text:
            text = text.replace(import_anchor, import_anchor + statement + "\n", 1)
    allowed_old_prefix = "if route_key not in {"
    allowed_start = text.index(allowed_old_prefix)
    allowed_end = text.index("}:\n", allowed_start) + 1
    allowed = 'if route_key not in {"cisd_bpr_ifvg", "compression_bpr", "smt_cisd", "ifvg_failure", "htf_ote"}'
    text = text[:allowed_start] + allowed + text[allowed_end:]
    generator_start = text.index("    if route_key == \"smt_cisd\":", text.index("def generate_route_candidates"))
    generator_end = text.index("    features: dict[str, pd.DataFrame] = {}", generator_start)
    generator = '''    if route_key == "smt_cisd":\n        features, candidates = smt.generate_joint_candidates(decision_frames)\n        return features, candidates\n    if route_key == "cisd_bpr_ifvg":\n        generator = engine.generate_candidates\n    elif route_key == "compression_bpr":\n        generator = compression.generate_candidates\n    elif route_key == "ifvg_failure":\n        generator = ifvg_failure.generate_candidates\n    else:\n        generator = htf_ote.generate_candidates\n'''
    text = text[:generator_start] + generator + text[generator_end:]
    text = text.replace(
        'boundaries = list(pd.date_range(OFFICIAL_START, OFFICIAL_END, freq="6MS", tz="UTC"))',
        'boundaries = list(pd.date_range(OFFICIAL_START, OFFICIAL_END, freq="6MS"))',
    )
    if 'SCORED_CANDIDATES.jsonl' not in text:
        anchor = "    realistic_config = engine.DEFAULT_EXECUTION\n"
        block = '''    scored_for_tape = engine.score_predictions(predictions, risk_fraction, model_spec.confidence_penalty)\n    scored_rows = []\n    for scored in scored_for_tape:\n        candidate = scored.candidate\n        scored_rows.append({\n            "timestamp": candidate.timestamp, "symbol": candidate.symbol,\n            "family": candidate.family.value, "side": candidate.side,\n            "decision_price": candidate.decision_price, "entry_reference": candidate.entry_reference,\n            "stop_reference": candidate.stop_reference, "target_reference": candidate.target_reference,\n            "structural_level": candidate.structural_level, "feature_row": dict(candidate.feature_row),\n            "win_probability": scored.win_probability, "expected_net_r": scored.expected_net_r,\n            "passive_fill_probability": scored.passive_fill_probability,\n            "expected_log_growth": scored.expected_log_growth,\n            "lower_confidence_score": scored.lower_confidence_score,\n            "chosen_action": scored.chosen_action.value,\n        })\n    scored_sha = write_jsonl(args.output / "SCORED_CANDIDATES.jsonl", scored_rows)\n\n'''
        if anchor not in text:
            raise RuntimeError("full scored-candidate anchor missing")
        text = text.replace(anchor, block + anchor, 1)
        text = text.replace(
            '            "fills_sha256": fill_sha,\n',
            '            "fills_sha256": fill_sha,\n            "scored_candidates_sha256": scored_sha,\n            "scored_candidate_rows": len(scored_rows),\n',
            1,
        )
    write(path, text)


def ensure_pooled_scored_candidates() -> None:
    path = "research/yt_trinity_ml/run_pooled_trinity_system.py"
    text = read(path)
    if 'SCORED_CANDIDATES.jsonl' in text:
        return
    anchor = "            realistic_config, zero_config, stressed_config = full_execution_triplet()\n"
    block = '''            scored_for_tape = engine.score_predictions(\n                official_predictions, float(selected_risk["risk_fraction"]), spec.confidence_penalty\n            )\n            scored_rows = []\n            for scored in scored_for_tape:\n                candidate = scored.candidate\n                scored_rows.append({\n                    "timestamp": candidate.timestamp, "symbol": candidate.symbol,\n                    "family": candidate.family.value, "side": candidate.side,\n                    "decision_price": candidate.decision_price, "entry_reference": candidate.entry_reference,\n                    "stop_reference": candidate.stop_reference, "target_reference": candidate.target_reference,\n                    "structural_level": candidate.structural_level, "feature_row": dict(candidate.feature_row),\n                    "win_probability": scored.win_probability, "expected_net_r": scored.expected_net_r,\n                    "passive_fill_probability": scored.passive_fill_probability,\n                    "expected_log_growth": scored.expected_log_growth,\n                    "lower_confidence_score": scored.lower_confidence_score,\n                    "chosen_action": scored.chosen_action.value,\n                })\n            scored_sha = full.write_jsonl(args.output / "SCORED_CANDIDATES.jsonl", scored_rows)\n'''
    if anchor not in text:
        raise RuntimeError("pooled scored-candidate anchor missing")
    text = text.replace(anchor, block + anchor, 1)
    text = text.replace(
        '                    "fills_sha256": fill_sha,\n',
        '                    "fills_sha256": fill_sha,\n                    "scored_candidates_sha256": scored_sha,\n                    "scored_candidate_rows": len(scored_rows),\n',
        1,
    )
    write(path, text)


def ensure_htf_stationarity() -> None:
    path = "research/yt_trinity_ml/run_htf_ote_continuation.py"
    text = read(path)
    if "HTF_ABSOLUTE_FEATURES = {" not in text:
        old = '''def numeric_row(row: pd.Series) -> dict[str, float]:\n    return {\n        str(key): float(value)\n        for key, value in row.items()\n        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)\n    }'''
        new = '''HTF_ABSOLUTE_FEATURES = {\n    "htf_atr", "htf_ema_fast", "htf_ema_slow", "htf_ema_long",\n    "htf_last_swing_high", "htf_last_swing_low",\n    "htf_previous_day_high", "htf_previous_day_low",\n    "htf_previous_week_high", "htf_previous_week_low",\n}\n\n\ndef numeric_row(row: pd.Series) -> dict[str, float]:\n    return {\n        str(key): float(value)\n        for key, value in row.items()\n        if key not in HTF_ABSOLUTE_FEATURES\n        and isinstance(value, (int, float, np.integer, np.floating))\n        and np.isfinite(value)\n    }'''
        if old not in text:
            raise RuntimeError("HTF stationarity anchor missing")
        text = text.replace(old, new, 1)
    text = text.replace('            "ote_lower": ote_lower,\n            "ote_upper": ote_upper,\n', '')
    write(path, text)


def ensure_trade_tape() -> None:
    path = "research/yt_trinity_ml/run_public_trade_tape_validation.py"
    text = read(path)
    if '"row_order": np.arange(len(frame), dtype=np.int64)' not in text:
        text = text.replace(
            '            "sequence": frame[sequence_column].astype(str) if sequence_column else np.arange(len(frame)).astype(str),\n',
            '            "sequence": frame[sequence_column].astype(str) if sequence_column else np.arange(len(frame)).astype(str),\n            "row_order": np.arange(len(frame), dtype=np.int64),\n',
            1,
        )
    text = text.replace(
        'result = result.sort_values(["timestamp", "sequence"], kind="stable").reset_index(drop=True)',
        'result = result.sort_values(["timestamp", "row_order"], kind="stable").reset_index(drop=True)',
    )
    if "def day_requires_trade_archive(" not in text:
        anchor = "def resolve_signal(\n"
        helper = '''def day_requires_trade_archive(\n    signal: FrozenSignal, day: pd.Timestamp, activation: pd.Timestamp,\n    mark_frame: pd.DataFrame, entry_filled: float, open_quantity: float,\n) -> bool:\n    if signal.chosen_action == "MARKETABLE" and entry_filled <= 0:\n        return day == activation.floor("D")\n    start = max(day, activation)\n    end = min(day + pd.Timedelta(days=1), OFFICIAL_END)\n    bars = mark_frame.loc[(mark_frame["bar_start"] >= start) & (mark_frame["bar_start"] < end)]\n    if bars.empty:\n        raise ArchiveGap(f"no one-minute interaction index for {signal.symbol} {day.date()}")\n    low = float(bars["low"].min()); high = float(bars["high"].max())\n    if open_quantity > 1e-12:\n        return low <= signal.stop_reference or high >= signal.target_reference\n    if signal.side > 0:\n        return low < signal.entry_reference or low <= signal.stop_reference or high >= signal.target_reference\n    return high > signal.entry_reference or high >= signal.stop_reference or low <= signal.target_reference\n\n\n'''
        if anchor not in text:
            raise RuntimeError("trade-tape resolve anchor missing")
        text = text.replace(anchor, helper + anchor, 1)
    old_loop = '''    while day < OFFICIAL_END.floor("D") + pd.Timedelta(days=1):\n        trades = archive.get(signal.symbol, day)\n'''
    if "if not day_requires_trade_archive(" not in text:
        new_loop = '''    while day < OFFICIAL_END.floor("D") + pd.Timedelta(days=1):\n        if not day_requires_trade_archive(signal, day, activation, mark_frame, entry_filled, open_quantity):\n            day += pd.Timedelta(days=1)\n            cursor = day\n            if day >= OFFICIAL_END:\n                break\n            continue\n        trades = archive.get(signal.symbol, day)\n'''
        if old_loop not in text:
            raise RuntimeError("trade-tape day loop anchor missing")
        text = text.replace(old_loop, new_loop, 1)
    write(path, text)


def ensure_workflow_triggers() -> None:
    selection = ".github/workflows/yt-trinity-coarse-survivor-selection.yml"
    text = read(selection)
    anchor = "      - research/yt_trinity_ml/select_coarse_survivor.py"
    for pointer in ("IFVG_FAILURE_RUN_POINTER.json", "HTF_OTE_RUN_POINTER.json"):
        line = f"      - research/yt_trinity_ml/{pointer}\n"
        if line not in text:
            text = text.replace(anchor, line + anchor, 1)
    write(selection, text)

    full_workflow = ".github/workflows/yt-trinity-full-sequential-survivor.yml"
    text = read(full_workflow)
    compile_anchor = "            research/yt_trinity_ml/run_full_sequential_survivor.py \\\n"
    for script in ("run_ifvg_failure_research.py", "run_htf_ote_continuation.py"):
        line = f"            research/yt_trinity_ml/{script} \\\n"
        if line not in text:
            text = text.replace(compile_anchor, line + compile_anchor, 1)
    write(full_workflow, text)


def remove_temporary_materializers() -> None:
    names = [
        "apply_cisd_runner_datetime_fix.py",
        "apply_cisd_stationarity_guard.py",
        "apply_frontend_content_output_fix.py",
        "apply_frontend_caption_validation_fix.py",
        "apply_full_survivor_calendar_fix.py",
        "apply_alpha_chain_selection_fix.py",
        "apply_ifvg_route_integration.py",
        "apply_htf_ote_stationarity_fix.py",
        "apply_htf_ote_route_integration.py",
        "apply_scored_candidate_evidence.py",
        "apply_trade_tape_efficiency_fix.py",
    ]
    for name in names:
        path = ROOT / "research/yt_trinity_ml" / name
        path.unlink(missing_ok=True)
    workflows = [
        "yt-trinity-cisd-runner-fix.yml",
        "yt-trinity-cisd-stationarity-fix.yml",
        "yt-trinity-frontend-content-fix.yml",
        "yt-trinity-frontend-caption-validation-fix.yml",
        "yt-trinity-full-survivor-calendar-fix.yml",
        "yt-trinity-alpha-chain-selection-fix.yml",
        "yt-trinity-ifvg-route-integration.yml",
        "yt-trinity-htf-ote-stationarity-fix.yml",
        "yt-trinity-htf-ote-route-integration.yml",
        "yt-trinity-scored-candidate-evidence.yml",
        "yt-trinity-trade-tape-efficiency-fix.yml",
    ]
    for name in workflows:
        (ROOT / ".github/workflows" / name).unlink(missing_ok=True)


def verify() -> None:
    selector = read("research/yt_trinity_ml/select_coarse_survivor.py")
    full = read("research/yt_trinity_ml/run_full_sequential_survivor.py")
    trade = read("research/yt_trinity_ml/run_public_trade_tape_validation.py")
    htf = read("research/yt_trinity_ml/run_htf_ote_continuation.py")
    cisd = read("research/yt_trinity_ml/run_cisd_bpr_ifvg_research.py")
    for route, _, pointer in route_tuples():
        assert route in selector and pointer in selector
    assert "ABSOLUTE_FEATURES" in cisd and "name not in ABSOLUTE_FEATURES" in cisd
    assert "SCORED_CANDIDATES.jsonl" in full
    assert "run_htf_ote_continuation as htf_ote" in full
    assert "run_ifvg_failure_research as ifvg_failure" in full
    assert "HTF_ABSOLUTE_FEATURES" in htf and '"ote_lower": ote_lower' not in htf
    assert "row_order" in trade and "day_requires_trade_archive" in trade
    assert "ALL_RESOLVED_ECONOMIC_FAIL_SWITCH_ALPHA" in selector


def main() -> int:
    ensure_cisd_datetime_and_stationarity()
    ensure_frontend_fixes()
    ensure_selector_routes()
    ensure_full_routes()
    ensure_pooled_scored_candidates()
    ensure_htf_stationarity()
    ensure_trade_tape()
    ensure_workflow_triggers()
    verify()
    remove_temporary_materializers()
    print("research source consolidation complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
