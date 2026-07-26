from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

import probe as base


def download_prefix_without_range(
    session: requests.Session,
    url: str,
    target: Path,
    maximum_bytes: int,
) -> dict[str, Any]:
    """Stream a normal GET and retain only the bounded compressed prefix.

    Tardis' keyless first-of-month dataset endpoint rejected HTTP Range with
    403 even though the same files are documented as freely downloadable via a
    normal GET. This changes only transport; the date, files, row cap, schema
    checks and no-PnL boundary remain frozen.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=(30, 600)) as response:
        status = response.status_code
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length", "0") or 0)
        content_range = response.headers.get("Content-Range")
        reported_total = base.parse_content_range(content_range)
        if reported_total is None and content_length:
            reported_total = content_length
        written = 0
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                remaining = maximum_bytes - written
                if remaining <= 0:
                    break
                payload = chunk[:remaining]
                handle.write(payload)
                written += len(payload)
                if written >= maximum_bytes:
                    break

    return {
        "http_status": status,
        "transport": "normal_get_locally_capped",
        "content_length_header": content_length,
        "content_range_header": content_range,
        "reported_total_bytes": reported_total,
        "retrieved_bytes": written,
        "complete_file_retrieved": reported_total is not None and written >= reported_total,
        "retrieved_sha256": base.sha256_file(target),
    }


def main() -> int:
    base.download_prefix = download_prefix_without_range
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
