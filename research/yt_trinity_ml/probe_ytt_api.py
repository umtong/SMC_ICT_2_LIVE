#!/usr/bin/env python3
"""Register an ephemeral free key and prove authenticated transcript transport."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://api.youtubetotext.com"
HEADERS = {"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"}
SAMPLES = {
    "known_positive_control": "F6wDs1HRTSo",
    "swipalnam_sample": "UmEPMyzjQS8",
    "chartbro_sample": "0h9lpMUBSlE",
    "indicator_sensei_sample": "wIhgAp-XNTA",
}


def request_json(request: urllib.request.Request) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            return int(response.status), json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw.decode("utf-8", "replace")[:2000]}
        return int(exc.code), payload


def main() -> int:
    status, registration = request_json(
        urllib.request.Request(f"{BASE}/free/register", data=b"", method="POST", headers=HEADERS)
    )
    if status not in {200, 201} or not isinstance(registration, dict):
        raise SystemExit(f"free-key registration failed: {status} {registration}")
    api_key = str(registration.get("api_key") or "")
    if not api_key.startswith("ytt_free_"):
        raise SystemExit(f"invalid free-key response: {registration}")
    auth = {**HEADERS, "X-API-Key": api_key}
    rows: list[dict[str, Any]] = []
    for index, (name, video_id) in enumerate(SAMPLES.items()):
        if index:
            time.sleep(6.4)
        request = urllib.request.Request(f"{BASE}/full_transcript/{video_id}?meta=true", headers=auth)
        status, payload = request_json(request)
        transcript = payload.get("transcript") if isinstance(payload, dict) else None
        rows.append(
            {
                "name": name,
                "video_id": video_id,
                "status_code": status,
                "segment_count": len(transcript) if isinstance(transcript, list) else 0,
                "language_code": payload.get("language_code") if isinstance(payload, dict) else None,
                "source_type": payload.get("source_type") if isinstance(payload, dict) else None,
                "error": payload.get("error") if isinstance(payload, dict) else None,
                "reason": payload.get("reason") if isinstance(payload, dict) else None,
                "can_transcribe_with_ai": payload.get("canTranscribeWithAI") if isinstance(payload, dict) else None,
                "first_segments": transcript[:3] if isinstance(transcript, list) else [],
            }
        )
    positive = next(row for row in rows if row["name"] == "known_positive_control")
    result = {
        "schema_version": 1,
        "tier": registration.get("tier"),
        "daily_fetch_cap": registration.get("daily_fetch_cap"),
        "positive_control_pass": positive["segment_count"] >= 100,
        "rows": rows,
    }
    Path("YTT_AUTH_PROBE.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["positive_control_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
