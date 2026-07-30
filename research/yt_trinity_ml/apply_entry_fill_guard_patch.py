from __future__ import annotations

import hashlib
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "system" / "coarse.py"
SOURCE_SHA256 = "425f291c73a971e4f7172879b89e416786c41ada5b77812f3f82cce2b77bc2a9"
TARGET_SHA256 = "ae9545d0a4177868e3c4fd6415cbd45932c51c6699607bd594e091f14791df28"

REPLACEMENTS = (
    (
        """def _market_fill(open_price: float, side: int, row: pd.Series, slippage_bps: float, config: CoarseExecutionConfig) -> float:
    cost = _spread_fraction(row, config) / 2 + slippage_bps / 10000
    return open_price * (1 + side * cost)


class _RangeExtremaIndex:
""",
        """def _market_fill(open_price: float, side: int, row: pd.Series, slippage_bps: float, config: CoarseExecutionConfig) -> float:
    cost = _spread_fraction(row, config) / 2 + slippage_bps / 10000
    return open_price * (1 + side * cost)


def _entry_geometry_valid(candidate: EventCandidate, entry_price: float) -> bool:
    \"\"\"A marketable IOC order is cancelled if latency moves beyond stop or target.\"\"\"
    protective_distance = candidate.side * (entry_price - candidate.stop_reference)
    remaining_reward = candidate.side * (candidate.target_reference - entry_price)
    return protective_distance > 0 and remaining_reward > 0


class _RangeExtremaIndex:
""",
    ),
    (
        """        entry_time = self.available_times[entry_position] if passive else self.times[entry_position]
        stop_distance = abs(entry_price - candidate.stop_reference)
""",
        """        entry_time = self.available_times[entry_position] if passive else self.times[entry_position]
        if not _entry_geometry_valid(candidate, entry_price):
            return CoarseLabel(
                candidate.timestamp,
                None,
                entry_time,
                None,
                None,
                0,
                \"CANCELLED_INVALID_ENTRY_GEOMETRY\",
            )
        stop_distance = abs(entry_price - candidate.stop_reference)
""",
    ),
    (
        """    entry_time = labeler.available_times[entry_position] if passive else labeler.times[entry_position]
    if side > 0:
""",
        """    entry_time = labeler.available_times[entry_position] if passive else labeler.times[entry_position]
    if not _entry_geometry_valid(candidate, entry_price):
        return CoarseOutcome(
            candidate.timestamp,
            None,
            entry_time,
            \"CANCELLED_INVALID_ENTRY_GEOMETRY\",
            None,
            None,
            0.0,
            None,
            None,
            None,
        )
    if side > 0:
""",
    ),
    (
        """            symbol_risk = replace(risk, quantity_step=float(step), minimum_quantity=float(minimum))
            quantity = size_position_from_nav(
                cash,
                candidate,
                symbol_risk,
                outcome.entry_fee_rate,
                self.config.taker_fee_rate,
                self.config.market_slippage_bps / 10000 if not passive else 0.0,
                self.config.stop_slippage_bps / 10000,
            )
""",
        """            symbol_risk = replace(risk, quantity_step=float(step), minimum_quantity=float(minimum))
            sizing_candidate = replace(candidate, entry_reference=float(outcome.entry_price))
            quantity = size_position_from_nav(
                cash,
                sizing_candidate,
                symbol_risk,
                outcome.entry_fee_rate,
                self.config.taker_fee_rate,
                0.0,
                self.config.stop_slippage_bps / 10000,
            )
""",
    ),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    data = TARGET.read_bytes()
    current = digest(data)
    if current == TARGET_SHA256:
        print(f"entry-fill guard already at {TARGET_SHA256}")
        return
    if current != SOURCE_SHA256:
        raise SystemExit(f"unexpected coarse.py source sha256: {current}")
    text = data.decode("utf-8")
    for before, after in REPLACEMENTS:
        count = text.count(before)
        if count != 1:
            raise SystemExit(f"expected exactly one patch location, found {count}")
        text = text.replace(before, after, 1)
    output = text.encode("utf-8")
    final = digest(output)
    if final != TARGET_SHA256:
        raise SystemExit(f"patched coarse.py digest mismatch: {final}")
    TARGET.write_bytes(output)
    print(f"wrote {TARGET} sha256={final}")


if __name__ == "__main__":
    main()
