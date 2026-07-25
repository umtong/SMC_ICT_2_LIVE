from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE = "https://data.binance.vision/data/futures/um/monthly"
KINDS = ("fundingRate", "klines")


@dataclass(frozen=True)
class Job:
    symbol: str
    month: str
    kind: str
    filename: str
    url: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def months(start: str, end: str) -> list[str]:
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out: list[str] = []
    year, month = sy, sm
    while (year, month) <= (ey, em):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return out


def archive_spec(symbol: str, kind: str, month: str) -> tuple[str, str]:
    if kind == "fundingRate":
        filename = f"{symbol}-fundingRate-{month}.zip"
        return filename, f"{BASE}/fundingRate/{symbol}/{filename}"
    filename = f"{symbol}-1h-{month}.zip"
    return filename, f"{BASE}/klines/{symbol}/1h/{filename}"


def request_bytes(url: str, attempts: int = 7) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "smc-ict-2-xsec-funding/1.0"},
            )
            with urllib.request.urlopen(request, timeout=600) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            last = exc
        except (OSError, urllib.error.URLError) as exc:
            last = exc
        if attempt + 1 < attempts:
            time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"download failed: {url}: {last!r}")


def expected_checksum(text: str, filename: str) -> str:
    tokens = [token.lower() for token in text.replace("*", " ").split() if len(token) == 64]
    if filename not in text or not tokens:
        raise ValueError(f"invalid CHECKSUM for {filename}")
    return tokens[0]


def run_job(root: Path, job: Job) -> dict[str, object]:
    archive = root / "raw" / job.symbol / job.kind / job.filename
    checksum_path = archive.with_suffix(".zip.CHECKSUM")
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not checksum_path.exists():
            checksum_path.write_bytes(request_bytes(job.url + ".CHECKSUM"))
        expected = expected_checksum(checksum_path.read_text(encoding="utf-8-sig"), job.filename)
        if not archive.exists() or sha256_file(archive) != expected:
            archive.unlink(missing_ok=True)
            archive.write_bytes(request_bytes(job.url))
        observed = sha256_file(archive)
        if observed != expected:
            raise RuntimeError(f"checksum mismatch: {job.filename}: {observed} != {expected}")
        return {
            "status": "OK",
            "symbol": job.symbol,
            "month": job.month,
            "kind": job.kind,
            "filename": job.filename,
            "url": job.url,
            "sha256": observed,
            "bytes": archive.stat().st_size,
        }
    except FileNotFoundError:
        checksum_path.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)
        return {
            "status": "MISSING",
            "symbol": job.symbol,
            "month": job.month,
            "kind": job.kind,
            "filename": job.filename,
            "url": job.url,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    jobs: list[Job] = []
    for symbol in config["symbols"]:
        for month in months(config["archive_start"], config["archive_end"]):
            for kind in KINDS:
                filename, url = archive_spec(symbol, kind, month)
                jobs.append(Job(symbol, month, kind, filename, url))

    records: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {pool.submit(run_job, args.root, job): job for job in jobs}
        for future in concurrent.futures.as_completed(future_map):
            record = future.result()
            records.append(record)
            print(json.dumps(record, sort_keys=True), flush=True)

    records.sort(key=lambda row: (str(row["symbol"]), str(row["month"]), str(row["kind"])))
    manifest = args.root / "manifest.json"
    manifest.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ok = sum(row["status"] == "OK" for row in records)
    missing = sum(row["status"] == "MISSING" for row in records)
    summary = {
        "requested_archives": len(records),
        "verified_archives": ok,
        "missing_archives": missing,
        "manifest": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "orders_submitted": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if ok == 0:
        raise RuntimeError("no archives downloaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
