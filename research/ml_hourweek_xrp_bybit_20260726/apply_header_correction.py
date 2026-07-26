from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "run.py"
ORIGINAL_SHA256 = "6776def0ce1dc3f749507387eadc1834e2d19e26486b80c25308943db73edced"
HEADER_CORRECTED_SHA256 = "c4aef87f1bb42fe8f196630a545a37d6a4ae3b7a1e4f8d3b4b7ada60f9826aaa"
FINAL_CORRECTED_SHA256 = "40e80b39783d2a85cb6b7f5dbee1553c4aaabd650687e0938a284f36535c1f00"

INSERT_BEFORE = "def download_binance_hourly(cache: Path, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], list[dict]]:\n"
HELPER = '''def parse_binance_kline_csv(raw: bytes, columns: list[str]) -> pd.DataFrame:\n    """Parse Binance Vision klines with or without the published header row."""\n    frame = pd.read_csv(io.BytesIO(raw), header=None, names=columns)\n    frame["open_time_ms"] = pd.to_numeric(frame["open_time_ms"], errors="coerce")\n    frame = frame.dropna(subset=["open_time_ms"]).copy()\n    frame["open_time_ms"] = frame["open_time_ms"].astype("int64")\n    numeric = ["open", "high", "low", "close", "quote_volume", "taker_buy_quote"]\n    for column in numeric:\n        frame[column] = pd.to_numeric(frame[column], errors="raise")\n    return frame\n\n\n'''
OLD_READ = '            frame = pd.read_csv(io.BytesIO(raw), header=None, names=columns)\n            frames.append(frame)\n'
NEW_READ = '            frame = parse_binance_kline_csv(raw, columns)\n            frames.append(frame)\n'

URL_REPLACEMENTS = {
    '    url = "https://api.bybit.com/v5/market/kline"\n': '''    urls = [\n        "https://api.bybit.com/v5/market/kline",\n        "https://api.bytick.com/v5/market/kline",\n        "https://api-demo.bybit.com/v5/market/kline",\n        "https://api.bybit.nl/v5/market/kline",\n    ]\n''',
    '    url = "https://api.bybit.com/v5/market/mark-price-kline"\n': '''    urls = [\n        "https://api.bybit.com/v5/market/mark-price-kline",\n        "https://api.bytick.com/v5/market/mark-price-kline",\n        "https://api-demo.bybit.com/v5/market/mark-price-kline",\n        "https://api.bybit.nl/v5/market/mark-price-kline",\n    ]\n''',
    '    url = "https://api.bybit.com/v5/market/funding/history"\n': '''    urls = [\n        "https://api.bybit.com/v5/market/funding/history",\n        "https://api.bytick.com/v5/market/funding/history",\n        "https://api-demo.bybit.com/v5/market/funding/history",\n        "https://api.bybit.nl/v5/market/funding/history",\n    ]\n''',
}
OLD_INLINE = '                response = session.get(url, params=params, timeout=(20, 90), headers={"User-Agent": "SMC-ICT-2-hourweek-xrp/1.0"})\n'
NEW_INLINE = '''                chosen_url = urls[attempt % len(urls)]\n                response = session.get(chosen_url, params=params, timeout=(20, 90), headers={"User-Agent": "SMC-ICT-2-hourweek-xrp/1.0"})\n'''
OLD_MULTILINE = '''                response = session.get(\n                    url,\n                    params=params,\n'''
NEW_MULTILINE = '''                chosen_url = urls[attempt % len(urls)]\n                response = session.get(\n                    chosen_url,\n                    params=params,\n'''
OLD_COMPACT_CALL = '        calls.append({"symbol": symbol, "end": cursor, "rows": len(data), "response_time": payload.get("time")})\n'
NEW_COMPACT_CALL = '        calls.append({"symbol": symbol, "end": cursor, "rows": len(data), "response_time": payload.get("time"), "endpoint": chosen_url})\n'
OLD_MARK_CALL = '''                "response_time": payload.get("time"),\n            }\n'''
NEW_MARK_CALL = '''                "response_time": payload.get("time"),\n                "endpoint": chosen_url,\n            }\n'''


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def apply_header(text: str) -> str:
    if text.count(INSERT_BEFORE) != 1 or text.count(OLD_READ) != 1:
        raise RuntimeError("header correction anchors are not unique")
    text = text.replace(INSERT_BEFORE, HELPER + INSERT_BEFORE, 1)
    return text.replace(OLD_READ, NEW_READ, 1)


def apply_domains(text: str) -> str:
    for old, new in URL_REPLACEMENTS.items():
        if text.count(old) != 1:
            raise RuntimeError(f"Bybit URL correction anchor count is {text.count(old)} for {old!r}")
        text = text.replace(old, new, 1)
    if text.count(OLD_INLINE) != 2:
        raise RuntimeError(f"inline Bybit request anchor count is {text.count(OLD_INLINE)}")
    text = text.replace(OLD_INLINE, NEW_INLINE)
    if text.count(OLD_MULTILINE) != 1:
        raise RuntimeError(f"multiline Bybit request anchor count is {text.count(OLD_MULTILINE)}")
    text = text.replace(OLD_MULTILINE, NEW_MULTILINE, 1)
    if text.count(OLD_COMPACT_CALL) != 2:
        raise RuntimeError("compact Bybit call-log anchor count is not two")
    text = text.replace(OLD_COMPACT_CALL, NEW_COMPACT_CALL)
    if text.count(OLD_MARK_CALL) != 1:
        raise RuntimeError("mark-price call-log anchor count is not one")
    return text.replace(OLD_MARK_CALL, NEW_MARK_CALL, 1)


def main() -> int:
    raw = TARGET.read_bytes()
    current = digest(raw)
    if current == FINAL_CORRECTED_SHA256:
        print(f"TRANSPORT_CORRECTIONS_ALREADY_APPLIED sha256={current}")
        return 0
    text = raw.decode("utf-8")
    if current == ORIGINAL_SHA256:
        text = apply_header(text)
        intermediate = text.encode("utf-8")
        if digest(intermediate) != HEADER_CORRECTED_SHA256:
            raise RuntimeError(f"header-corrected source identity mismatch {digest(intermediate)}")
    elif current != HEADER_CORRECTED_SHA256:
        raise RuntimeError(f"unexpected pre-correction source hash {current}")
    text = apply_domains(text)
    corrected = text.encode("utf-8")
    if digest(corrected) != FINAL_CORRECTED_SHA256:
        raise RuntimeError(f"final corrected source identity mismatch {digest(corrected)}")
    compile(corrected, str(TARGET), "exec")
    TARGET.write_bytes(corrected)
    print(f"TRANSPORT_CORRECTIONS_APPLIED bytes={len(corrected)} sha256={digest(corrected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
