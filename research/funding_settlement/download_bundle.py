from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/monthly"
KINDS = ("fundingRate", "klines", "premiumIndexKlines")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def get(url: str, path: Path, attempts: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "smc-ict-2-funding-settlement/1.0"})
            with urllib.request.urlopen(request, timeout=600) as response, path.open("wb") as output:
                shutil.copyfileobj(response, output, 1 << 20)
            return
        except (OSError, urllib.error.URLError) as exc:
            last = exc
            path.unlink(missing_ok=True)
            if attempt + 1 < attempts:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"download failed: {url}: {last!r}")


def expected_checksum(text: str, filename: str) -> str:
    tokens = [token.lower() for token in text.replace("*", " ").split() if len(token) == 64]
    if filename not in text or not tokens:
        raise ValueError(f"invalid CHECKSUM for {filename}")
    return tokens[0]


def archive_spec(symbol: str, kind: str, month: str) -> tuple[str, str]:
    if kind == "fundingRate":
        filename = f"{symbol}-fundingRate-{month}.zip"
        url = f"{BASE}/fundingRate/{symbol}/{filename}"
    else:
        filename = f"{symbol}-5m-{month}.zip"
        url = f"{BASE}/{kind}/{symbol}/5m/{filename}"
    return filename, url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--start", default="2021-01")
    parser.add_argument("--end", default="2025-12")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    args = parser.parse_args()

    months = [str(period) for period in pd.period_range(args.start, args.end, freq="M")]
    records: list[dict[str, object]] = []
    for symbol in [s.upper() for s in args.symbols]:
        for month in months:
            for kind in KINDS:
                filename, url = archive_spec(symbol, kind, month)
                archive = args.root / "raw" / symbol / kind / filename
                checksum_path = archive.with_suffix(".zip.CHECKSUM")
                if not checksum_path.exists():
                    get(url + ".CHECKSUM", checksum_path)
                expected = expected_checksum(checksum_path.read_text(encoding="utf-8-sig"), filename)
                if not archive.exists() or sha256(archive) != expected:
                    archive.unlink(missing_ok=True)
                    get(url, archive)
                observed = sha256(archive)
                if observed != expected:
                    raise RuntimeError(f"checksum mismatch: {filename}: {observed} != {expected}")
                records.append({
                    "symbol": symbol,
                    "month": month,
                    "kind": kind,
                    "filename": filename,
                    "url": url,
                    "sha256": observed,
                    "bytes": archive.stat().st_size,
                })
                print(symbol, month, kind, archive.stat().st_size, observed, flush=True)

    records.sort(key=lambda row: (str(row["symbol"]), str(row["month"]), str(row["kind"])))
    manifest = args.root / "manifest.json"
    manifest.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "archives": len(records),
        "manifest": str(manifest),
        "manifest_sha256": sha256(manifest),
        "orders_submitted": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
