#!/usr/bin/env python3
"""Add a fixed-500ms, same-size severe execution stress profile."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "research/yt_trinity_ml/run_public_trade_tape_validation.py"
text = TARGET.read_text(encoding="utf-8")

anchor = '''def extract_contract(summary: Mapping[str, Any]) -> tuple[float, float, TapeConfig]:'''
helper = '''def strict_execution_profile(base: TapeConfig) -> TapeConfig:\n    return dataclasses.replace(\n        base,\n        # The project latency remains exactly 500 ms. Only execution uncertainty is stressed.\n        activation_latency_ms=500,\n        minimum_spread_bps=max(base.minimum_spread_bps * 4.0, 2.0),\n        market_slippage_bps=max(base.market_slippage_bps * 2.5, 5.0),\n        stop_slippage_bps=max(base.stop_slippage_bps * 2.5, 10.0),\n        passive_entry_queue_multiple=max(base.passive_entry_queue_multiple * 2.5, 5.0),\n        passive_target_queue_multiple=max(base.passive_target_queue_multiple * 2.5, 4.0),\n        base_impact_bps=max(base.base_impact_bps * 3.0, 2.0),\n        impact_bps_per_sqrt_participation=max(\n            base.impact_bps_per_sqrt_participation * 2.5, 6.0\n        ),\n        maximum_impact_bps=max(base.maximum_impact_bps * 2.4, 60.0),\n    )\n\n\n'''
if "def strict_execution_profile(" not in text:
    if anchor not in text:
        raise SystemExit("extract contract anchor missing")
    text = text.replace(anchor, helper + anchor, 1)

old_config = '''    risk_fraction, maximum_leverage, config = extract_contract(summary)\n    args.output.mkdir(parents=True, exist_ok=True)'''
new_config = '''    risk_fraction, maximum_leverage, baseline_config = extract_contract(summary)\n    sizing_config = baseline_config\n    config = (\n        strict_execution_profile(baseline_config)\n        if args.execution_profile == "strict"\n        else baseline_config\n    )\n    args.output.mkdir(parents=True, exist_ok=True)'''
if new_config not in text:
    if old_config not in text:
        raise SystemExit("run config anchor missing")
    text = text.replace(old_config, new_config, 1)

old_quantity = '''        quantity = quantity_for_signal(selected, cash, risk_fraction, maximum_leverage, config)'''
new_quantity = '''        quantity = quantity_for_signal(\n            selected, cash, risk_fraction, maximum_leverage, sizing_config\n        )'''
if new_quantity not in text:
    if old_quantity not in text:
        raise SystemExit("quantity config anchor missing")
    text = text.replace(old_quantity, new_quantity, 1)

old_decision = '''    if source_error:\n        decision = "EVENT_TAPE_DATA_INCOMPLETE_INVALID"\n    elif invalid:\n        decision = "EVENT_TAPE_LIQUIDATION_OR_ACCOUNT_INVALID"\n    elif float(metrics["geometric_daily_growth"]) >= 0.01:\n        decision = "TARGET_EXCEEDED_PUBLIC_TRADE_TAPE_PENDING_QUOTE_STRESS"\n    elif float(metrics["geometric_daily_growth"]) > 0:\n        decision = "POSITIVE_PUBLIC_TRADE_TAPE_BELOW_TARGET"\n    else:\n        decision = "PUBLIC_TRADE_TAPE_ECONOMIC_FAIL"'''
new_decision = '''    prefix = "STRICT_" if args.execution_profile == "strict" else ""\n    if source_error:\n        decision = f"{prefix}EVENT_TAPE_DATA_INCOMPLETE_INVALID"\n    elif invalid:\n        decision = f"{prefix}EVENT_TAPE_LIQUIDATION_OR_ACCOUNT_INVALID"\n    elif float(metrics["geometric_daily_growth"]) >= 0.01:\n        decision = (\n            "TARGET_EXCEEDED_STRICT_PUBLIC_TRADE_TAPE"\n            if args.execution_profile == "strict"\n            else "TARGET_EXCEEDED_PUBLIC_TRADE_TAPE_PENDING_STRICT_STRESS"\n        )\n    elif float(metrics["geometric_daily_growth"]) > 0:\n        decision = f"{prefix}POSITIVE_PUBLIC_TRADE_TAPE_BELOW_TARGET"\n    else:\n        decision = f"{prefix}PUBLIC_TRADE_TAPE_ECONOMIC_FAIL"'''
if new_decision not in text:
    if old_decision not in text:
        raise SystemExit("decision anchor missing")
    text = text.replace(old_decision, new_decision, 1)

old_result = '''        "frozen_risk_fraction": risk_fraction,\n        "frozen_maximum_leverage": maximum_leverage,\n        "tape_config": dataclasses.asdict(config),'''
new_result = '''        "frozen_risk_fraction": risk_fraction,\n        "frozen_maximum_leverage": maximum_leverage,\n        "execution_profile": args.execution_profile,\n        "sizing_config": dataclasses.asdict(sizing_config),\n        "tape_config": dataclasses.asdict(config),\n        "strict_profile_uses_same_frozen_position_size": args.execution_profile == "strict",'''
if new_result not in text:
    if old_result not in text:
        raise SystemExit("result config anchor missing")
    text = text.replace(old_result, new_result, 1)

old_blockers = '''        "rankability_blockers": [\n            "historical best-bid/ask and displayed depth are not yet bound; trades infer aggressor-compatible execution conservatively",\n            "complete three-channel content corpus and audited ontology binding remains required",\n        ],'''
new_blockers = '''        "rankability_blockers": (\n            [\n                "historical best-bid/ask and displayed depth are not directly observed; strict trade-tape stress must remain above target",\n                "complete three-channel content corpus and audited ontology binding remains required",\n            ]\n            if args.execution_profile == "baseline"\n            else [\n                "strict public-trade execution stress still requires corpus-bound authority before ranking"\n            ]\n        ),'''
if new_blockers not in text:
    if old_blockers not in text:
        raise SystemExit("rankability blocker anchor missing")
    text = text.replace(old_blockers, new_blockers, 1)

old_parser = '''    parser.add_argument("--output", type=Path, required=True)\n    args = parser.parse_args()'''
new_parser = '''    parser.add_argument("--output", type=Path, required=True)\n    parser.add_argument(\n        "--execution-profile", choices=("baseline", "strict"), default="baseline"\n    )\n    args = parser.parse_args()'''
if new_parser not in text:
    if old_parser not in text:
        raise SystemExit("parser anchor missing")
    text = text.replace(old_parser, new_parser, 1)

TARGET.write_text(text, encoding="utf-8")

TEST = ROOT / "research/yt_trinity_ml/tests/test_public_trade_tape.py"
test_text = TEST.read_text(encoding="utf-8")
if "def test_strict_profile_preserves_500ms_and_increases_costs" not in test_text:
    test_text += '''\n\ndef test_strict_profile_preserves_500ms_and_increases_costs() -> None:\n    base = tape.TapeConfig(\n        activation_latency_ms=500, maker_fee_rate=0.0002, taker_fee_rate=0.00055,\n        minimum_spread_bps=0.5, market_slippage_bps=2.0, stop_slippage_bps=4.0,\n    )\n    strict = tape.strict_execution_profile(base)\n    assert strict.activation_latency_ms == 500\n    assert strict.minimum_spread_bps > base.minimum_spread_bps\n    assert strict.market_slippage_bps > base.market_slippage_bps\n    assert strict.stop_slippage_bps > base.stop_slippage_bps\n    assert strict.passive_entry_queue_multiple > base.passive_entry_queue_multiple\n    assert strict.maximum_impact_bps > base.maximum_impact_bps\n'''
    TEST.write_text(test_text, encoding="utf-8")
print("strict same-size trade-tape profile applied")
