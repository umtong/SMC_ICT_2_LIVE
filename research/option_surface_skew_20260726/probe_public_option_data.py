from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests

TWEET_ID = "1817888742650085616"
TWEET_URL = f"https://x.com/cryptarbitrage/status/{TWEET_ID}"
USER_AGENT = "SMC-ICT-2-LIVE-research/1.0 (+public-data-probe)"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def js_base36(number: float) -> str:
    """Close enough to JS Number.toString(36) for the syndication token.

    The exact known token for this preregistered tweet is retained below as a
    deterministic fallback. The endpoint is only used to discover the public
    file link; it is never an alpha input.
    """
    integer = int(number)
    fraction = number - integer
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    chars: list[str] = []
    if integer == 0:
        chars.append("0")
    while integer:
        integer, rem = divmod(integer, 36)
        chars.append(alphabet[rem])
    whole = "".join(reversed(chars))
    digits: list[str] = []
    for _ in range(12):
        fraction *= 36
        digit = int(fraction)
        digits.append(alphabet[digit])
        fraction -= digit
    return whole + "." + "".join(digits)


def extract_urls(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            out.extend(extract_urls(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(extract_urls(item))
    elif isinstance(value, str):
        out.extend(re.findall(r"https?://[^\s\"'<>]+", value))
    return out


def safe_request(session: requests.Session, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = session.request(method, url, timeout=45, allow_redirects=True, **kwargs)
        return {
            "ok": response.ok,
            "status": response.status_code,
            "url": url,
            "final_url": response.url,
            "headers": {k.lower(): v for k, v in response.headers.items()},
            "content": response.content,
            "text": response.text,
        }
    except Exception as exc:  # pragma: no cover - network diagnostics
        return {"ok": False, "status": None, "url": url, "error": repr(exc), "content": b"", "text": ""}


def probe_tweet(session: requests.Session) -> dict[str, Any]:
    token = "4en.2dfij0pb"
    syndication = (
        "https://cdn.syndication.twimg.com/tweet-result?"
        f"id={TWEET_ID}&lang=en&token={token}"
    )
    oembed = "https://publish.twitter.com/oembed?omit_script=true&url=" + quote(TWEET_URL, safe="")
    results: dict[str, Any] = {"tweet_id": TWEET_ID, "tweet_url": TWEET_URL, "requests": []}
    discovered: list[str] = []
    for label, url in (("syndication", syndication), ("oembed", oembed)):
        response = safe_request(session, "GET", url)
        entry = {
            "label": label,
            "status": response.get("status"),
            "final_url": response.get("final_url"),
            "content_type": response.get("headers", {}).get("content-type"),
            "bytes": len(response.get("content", b"")),
            "sha256": sha256_bytes(response.get("content", b"")),
        }
        text = response.get("text", "")
        try:
            parsed = json.loads(text)
            entry["json"] = parsed
            discovered.extend(extract_urls(parsed))
        except Exception:
            entry["text_prefix"] = text[:2000]
            discovered.extend(extract_urls(text))
        results["requests"].append(entry)
    redirect_results = []
    for url in sorted(set(discovered)):
        if "x.com" in url or "twitter.com" in url or "twimg.com" in url:
            continue
        response = safe_request(session, "GET", url, headers={"Range": "bytes=0-0"})
        redirect_results.append(
            {
                "url": url,
                "status": response.get("status"),
                "final_url": response.get("final_url"),
                "content_type": response.get("headers", {}).get("content-type"),
                "content_length": response.get("headers", {}).get("content-length"),
            }
        )
    results["discovered_urls"] = sorted(set(discovered))
    results["redirects"] = redirect_results
    return results


def probe_uwa(session: requests.Session, output: Path) -> dict[str, Any]:
    files = {
        "Deribit_w_IV.csv": "https://research-repository.uwa.edu.au/files/78305486/Deribit_w_IV.csv",
        "instrument_name.csv": "https://research-repository.uwa.edu.au/files/78305487/instrument_name.csv",
        "Price_5m.csv": "https://research-repository.uwa.edu.au/files/78305488/Price_5m.csv",
        "Deribit_BTC_option_all.rds": "https://research-repository.uwa.edu.au/files/78320956/Deribit_BTC_option_all.rds",
    }
    report: dict[str, Any] = {"doi": "10.26182/5eabbcb4fbf28", "files": []}
    for name, url in files.items():
        response = safe_request(session, "GET", url, headers={"Range": "bytes=0-65535"})
        content = response.get("content", b"")
        row = {
            "name": name,
            "url": url,
            "status": response.get("status"),
            "final_url": response.get("final_url"),
            "content_type": response.get("headers", {}).get("content-type"),
            "content_length": response.get("headers", {}).get("content-length"),
            "content_range": response.get("headers", {}).get("content-range"),
            "received_bytes": len(content),
            "received_sha256": sha256_bytes(content),
            "prefix_hex": content[:32].hex(),
        }
        if name.endswith(".csv") and content:
            try:
                decoded = content.decode("utf-8-sig", errors="replace")
                row["text_prefix"] = decoded[:2000]
                row["header"] = next(csv.reader(io.StringIO(decoded)))
            except Exception as exc:
                row["parse_error"] = repr(exc)
        report["files"].append(row)
    return report


def probe_tardis_file(
    session: requests.Session,
    url: str,
    sample_path: Path,
    max_rows: int = 100_000,
) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url, "max_rows": max_rows}
    try:
        response = session.get(url, stream=True, timeout=120)
        result["status"] = response.status_code
        result["final_url"] = response.url
        result["headers"] = {k.lower(): v for k, v in response.headers.items()}
        response.raise_for_status()
        response.raw.decode_content = False
        with gzip.GzipFile(fileobj=response.raw, mode="rb") as gz:
            text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
            reader = csv.DictReader(text)
            result["columns"] = list(reader.fieldnames or [])
            currencies: dict[str, int] = {}
            expiries: set[str] = set()
            first_ts: int | None = None
            last_ts: int | None = None
            kept: list[dict[str, str]] = []
            for number, row in enumerate(reader, start=1):
                symbol = row.get("symbol", "")
                currency = symbol.split("-")[0] if "-" in symbol else symbol[:3]
                currencies[currency] = currencies.get(currency, 0) + 1
                if row.get("expiration"):
                    expiries.add(row["expiration"])
                try:
                    ts = int(row.get("timestamp", ""))
                    first_ts = ts if first_ts is None else min(first_ts, ts)
                    last_ts = ts if last_ts is None else max(last_ts, ts)
                except Exception:
                    pass
                if len(kept) < 500:
                    kept.append(row)
                if number >= max_rows:
                    result["rows_scanned"] = number
                    break
            else:
                result["rows_scanned"] = number if "number" in locals() else 0
            result["currencies"] = currencies
            result["unique_expirations_scanned"] = len(expiries)
            result["first_timestamp_us"] = first_ts
            result["last_timestamp_us"] = last_ts
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(sample_path, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=result.get("columns", []))
            writer.writeheader()
            writer.writerows(kept)
        result["sample_path"] = str(sample_path)
        result["sample_sha256"] = hashlib.sha256(sample_path.read_bytes()).hexdigest()
        result["sample_bytes"] = sample_path.stat().st_size
    except Exception as exc:  # pragma: no cover - network diagnostics
        result["error"] = repr(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tardis-rows", type=int, default=100_000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    report: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "public option-surface data availability probe before strategy PnL",
        "tweet": probe_tweet(session),
        "uwa": probe_uwa(session, args.output),
        "tardis": [],
    }
    for date in ("2020/09/01", "2022/01/01", "2023/01/01", "2024/01/01"):
        year, month, day = date.split("/")
        url = f"https://datasets.tardis.dev/v1/deribit/options_chain/{date}/OPTIONS.csv.gz"
        sample = args.output / f"tardis_deribit_options_chain_{year}-{month}-{day}_sample.csv.gz"
        report["tardis"].append(probe_tardis_file(session, url, sample, args.max_tardis_rows))
    path = args.output / "public_option_data_probe.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
    # Data availability, not profitability, determines success.
    usable_tardis = any("columns" in item and "delta" in item["columns"] for item in report["tardis"])
    return 0 if usable_tardis else 2


if __name__ == "__main__":
    raise SystemExit(main())
