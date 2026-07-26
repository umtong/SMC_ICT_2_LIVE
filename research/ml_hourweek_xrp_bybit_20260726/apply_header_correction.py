from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "run.py"
ORIGINAL_SHA256 = "6776def0ce1dc3f749507387eadc1834e2d19e26486b80c25308943db73edced"
CORRECTED_SHA256 = "c4aef87f1bb42fe8f196630a545a37d6a4ae3b7a1e4f8d3b4b7ada60f9826aaa"

INSERT_BEFORE = "def download_binance_hourly(cache: Path, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], list[dict]]:\n"
HELPER = '''def parse_binance_kline_csv(raw: bytes, columns: list[str]) -> pd.DataFrame:\n    \"\"\"Parse Binance Vision klines with or without the published header row.\"\"\"\n    frame = pd.read_csv(io.BytesIO(raw), header=None, names=columns)\n    frame[\"open_time_ms\"] = pd.to_numeric(frame[\"open_time_ms\"], errors=\"coerce\")\n    frame = frame.dropna(subset=[\"open_time_ms\"]).copy()\n    frame[\"open_time_ms\"] = frame[\"open_time_ms\"].astype(\"int64\")\n    numeric = [\"open\", \"high\", \"low\", \"close\", \"quote_volume\", \"taker_buy_quote\"]\n    for column in numeric:\n        frame[column] = pd.to_numeric(frame[column], errors=\"raise\")\n    return frame\n\n\n'''
OLD_READ = '            frame = pd.read_csv(io.BytesIO(raw), header=None, names=columns)\n            frames.append(frame)\n'
NEW_READ = '            frame = parse_binance_kline_csv(raw, columns)\n            frames.append(frame)\n'


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    raw = TARGET.read_bytes()
    current = digest(raw)
    if current == CORRECTED_SHA256:
        print(f"HEADER_CORRECTION_ALREADY_APPLIED sha256={current}")
        return 0
    if current != ORIGINAL_SHA256:
        raise RuntimeError(f"unexpected pre-correction source hash {current}")
    text = raw.decode("utf-8")
    if text.count(INSERT_BEFORE) != 1 or text.count(OLD_READ) != 1:
        raise RuntimeError("header correction anchors are not unique")
    text = text.replace(INSERT_BEFORE, HELPER + INSERT_BEFORE, 1)
    text = text.replace(OLD_READ, NEW_READ, 1)
    corrected = text.encode("utf-8")
    if digest(corrected) != CORRECTED_SHA256:
        raise RuntimeError(f"corrected source identity mismatch {digest(corrected)}")
    compile(corrected, str(TARGET), "exec")
    TARGET.write_bytes(corrected)
    print(f"HEADER_CORRECTION_APPLIED bytes={len(corrected)} sha256={digest(corrected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
