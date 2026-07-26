from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = REPO_ROOT / "research" / "ml_stablecoin_issuance_economic_20260726"
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

# The direct causal engine was recorded before source/model/market outcomes. It
# fixes entry-bar lookahead, marks unresolved positions instead of clock-closing
# them, opens calendar-2023 after model fit, and applies amendment-004 risk gates.
import run_causal as engine  # noqa: E402

engine.CLAIM_ID = engine.base.CLAIM_ID
engine.json_safe = engine.base.json_safe

CORRECTION_ID = "CORRECTION-20260726-ML-STABLECOIN-ENTRY-BAR-CAUSALITY-001"
DIRECT_ENGINE_CORRECTION_ID = (
    "CORRECTION-20260726-ML-STABLECOIN-CAUSAL-FEATURE-BOUNDARY-MARK-006"
)
SHIFTED_FEATURES = (
    "prior_15m_return",
    "prior_60m_realized_volatility",
    "prior_60m_path_efficiency",
)
_ORIGINAL_RETURNS_FEATURES = engine.base._returns_features


def causal_returns_features(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Diagnostic equivalent of information available before the entry open."""
    observed = _ORIGINAL_RETURNS_FEATURES(frame)
    corrected: dict[str, np.ndarray] = {}
    for key, values in observed.items():
        array = np.asarray(values, dtype=float)
        if key in {"ret15", "vol60", "eff60"}:
            shifted = np.full(array.shape, np.nan, dtype=float)
            if len(array) > 1:
                shifted[1:] = array[:-1]
            corrected[key] = shifted
        else:
            corrected[key] = array.copy()
    return corrected


def _walk_source_boundary(value: Any, paths: list[str], prefix: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("exit_reason") == "SOURCE_BOUNDARY":
            event_id = str(value.get("event_id", "UNKNOWN"))
            symbol = str(value.get("symbol", "UNKNOWN"))
            paths.append(f"{prefix}:{event_id}:{symbol}")
        for key, child in value.items():
            _walk_source_boundary(child, paths, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_source_boundary(child, paths, f"{prefix}[{index}]")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            engine.base.json_safe(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _refresh_hashes(output: Path) -> None:
    files = [
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output / "SHA256SUMS.txt").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in sorted(files)
        ),
        encoding="utf-8",
    )


def audit_result(output: Path) -> dict[str, Any]:
    """Bind direct causal execution and make any legacy synthetic stop fatal."""
    result_path = output / "RESULT.json"
    full_path = output / "FULL_RESULT.json"
    if not result_path.is_file() or not full_path.is_file():
        raise FileNotFoundError("economic result files missing")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    full = json.loads(full_path.read_text(encoding="utf-8"))
    unresolved_paths: list[str] = []
    _walk_source_boundary(full, unresolved_paths)
    unresolved_paths = sorted(set(unresolved_paths))

    guard = {
        "correction_id": CORRECTION_ID,
        "direct_engine_correction_id": DIRECT_ENGINE_CORRECTION_ID,
        "direct_engine": engine.ENGINE,
        "entry_bar_close_excluded": True,
        "shifted_completed_close_features": list(SHIFTED_FEATURES),
        "prior_liquidity_arrays_changed": False,
        "unresolved_selected_path_count": len(unresolved_paths),
        "unresolved_selected_paths": unresolved_paths,
        "stage_boundary_positions_marked_not_closed": True,
        "elapsed_time_liquidation_accepted": False,
        "confirmation_robustness_is_advancement_veto": False,
    }
    result["causal_guard"] = guard
    full["causal_guard"] = guard

    if unresolved_paths:
        result["status"] = "PRE2024_INVALID_UNRESOLVED_SELECTED_PATH"
        full["status"] = result["status"]
        for payload in (result, full):
            payload.setdefault("confirmation_gate", {})[
                "zero_unresolved_selected_paths"
            ] = False
            payload["confirmation_gate"]["all"] = False
            payload.setdefault("development_gate", {})[
                "zero_unresolved_selected_paths"
            ] = False
            payload["development_gate"]["all"] = False
            payload["official_2024h1_opened"] = False
            payload["official_2024_2026_opened"] = False
    else:
        for payload in (result, full):
            payload.setdefault("confirmation_gate", {})[
                "zero_unresolved_selected_paths"
            ] = True
            if payload.get("development_opened"):
                payload.setdefault("development_gate", {})[
                    "zero_unresolved_selected_paths"
                ] = True
                # The direct engine already computed objective-first "all".
                payload["development_gate"]["all"] = all(
                    bool(value)
                    for key, value in payload["development_gate"].items()
                    if key not in {"all"}
                )

    _write_json(result_path, result)
    _write_json(full_path, full)
    _refresh_hashes(output)
    return guard


def self_test() -> None:
    engine.self_test()

    times = np.arange(
        pd.Timestamp("2021-01-01", tz="UTC").value // 1_000_000,
        pd.Timestamp("2021-01-01 03:00", tz="UTC").value // 1_000_000,
        60_000,
        dtype=np.int64,
    )
    close = 100.0 + np.linspace(0.0, 2.0, len(times))
    frame = pd.DataFrame(
        {
            "open_time_ms": times,
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "quote_volume": np.full(len(times), 1_000_000.0),
        }
    )
    mutated = frame.copy()
    entry_index = 100
    mutated.loc[entry_index, "close"] = frame.loc[entry_index, "close"] * 1.25
    mutated.loc[entry_index, "high"] = mutated.loc[entry_index, "close"]
    before = causal_returns_features(frame)
    after = causal_returns_features(mutated)
    for key in ("ret15", "vol60", "eff60", "prior_high", "prior_low"):
        if not np.isclose(
            before[key][entry_index],
            after[key][entry_index],
            equal_nan=True,
        ):
            raise AssertionError(f"entry-bar future information leaked through {key}")
    if np.isclose(
        before["ret15"][entry_index + 1],
        after["ret15"][entry_index + 1],
        equal_nan=True,
    ):
        raise AssertionError("completed entry bar did not become available later")

    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        output = Path(raw)
        compact = {
            "claim_id": engine.CLAIM_ID,
            "status": "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1",
            "confirmation_gate": {"all": True},
            "development_gate": {"all": True},
            "development_opened": True,
            "official_2024h1_opened": False,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        full = {
            **compact,
            "development": {
                "costs": {
                    "24": {
                        "trade_ledger": [
                            {
                                "event_id": "e",
                                "symbol": "BTCUSDT",
                                "exit_reason": "SOURCE_BOUNDARY",
                            }
                        ]
                    }
                }
            },
        }
        _write_json(output / "RESULT.json", compact)
        _write_json(output / "FULL_RESULT.json", full)
        observed = audit_result(output)
        corrected = json.loads((output / "RESULT.json").read_text())
        if observed["unresolved_selected_path_count"] != 1:
            raise AssertionError(observed)
        if corrected["status"] != "PRE2024_INVALID_UNRESOLVED_SELECTED_PATH":
            raise AssertionError(corrected)
        if corrected["development_gate"]["all"] is not False:
            raise AssertionError("legacy unresolved path did not close development")

    print("stablecoin direct-causal guard self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--events", type=Path, required=True)
    run_parser.add_argument("--market-cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    rc = engine.run(args)
    guard = audit_result(args.output)
    print(json.dumps({"causal_guard": guard}, indent=2, sort_keys=True))
    if guard["unresolved_selected_path_count"]:
        return 2
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
