"""Rate-limited official Bybit V5 public client and page-level provenance."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import requests

try:
    from .canonical_spec import sha256_bytes
except ImportError:  # direct script execution
    from canonical_spec import sha256_bytes


class SourceError(RuntimeError):
    """Permanent official-source, request-contract, pagination or coverage failure."""


class RetryableSourceError(RuntimeError):
    """Transient network, rate-limit or server failure."""


@dataclass(frozen=True)
class PageAudit:
    stream: str
    path: str
    params: Mapping[str, Any]
    sha256: str
    bytes: int
    rows: int
    first_timestamp_ms: int | None
    last_timestamp_ms: int | None


class BybitPublicClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.bybit.com",
        timeout_s: int = 30,
        min_request_interval_s: float = 0.08,
        max_attempts: int = 8,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.min_request_interval_s = max(0.0, min_request_interval_s)
        self.max_attempts = max(1, max_attempts)
        self.session = requests.Session()
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_request_interval_s:
            time.sleep(self.min_request_interval_s - elapsed)

    def get(self, path: str, params: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_s)
                self._last_request_at = time.monotonic()
                status = response.status_code
                if status == 403:
                    raise SourceError("Bybit HTTP 403 access block; changing retry timing cannot repair it")
                if status == 429 or status >= 500:
                    raise RetryableSourceError(f"Bybit transient HTTP {status}")
                if status >= 400:
                    raise SourceError(f"Bybit permanent HTTP {status}: {response.text[:240]}")
                raw = response.content
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RetryableSourceError("Bybit returned a non-JSON success response") from exc
                if int(payload.get("retCode", -1)) != 0:
                    raise SourceError(
                        f"Bybit retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}"
                    )
                return payload, raw
            except SourceError:
                raise
            except (requests.RequestException, RetryableSourceError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                delay = min(60.0, 0.75 * (2 ** (attempt - 1))) + random.random() * 0.25
                time.sleep(delay)
        raise SourceError(f"request failed after {self.max_attempts} attempts: {url}: {last_error}")


def page_audit(
    *, stream: str, path: str, params: Mapping[str, Any], raw: bytes, timestamps: Sequence[int]
) -> PageAudit:
    return PageAudit(
        stream=stream,
        path=path,
        params=dict(params),
        sha256=sha256_bytes(raw),
        bytes=len(raw),
        rows=len(timestamps),
        first_timestamp_ms=min(timestamps) if timestamps else None,
        last_timestamp_ms=max(timestamps) if timestamps else None,
    )
