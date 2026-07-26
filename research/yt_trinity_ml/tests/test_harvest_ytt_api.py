from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import harvest_ytt_api as harvest  # noqa: E402


def test_authentication_error_is_never_video_unavailable(monkeypatch) -> None:
    calls = 0

    def fake_request(url: str, timeout: float = 50.0, headers=None):
        nonlocal calls
        calls += 1
        return 403, {"error": "unauthorized", "reason": "missing API key"}, {}

    monkeypatch.setattr(harvest, "request_json", fake_request)
    monkeypatch.setattr(harvest.time, "sleep", lambda *_: None)
    result = harvest.fetch_video("F6wDs1HRTSo", attempts=2, pace_seconds=0.0)
    assert calls == 2
    assert result["status"] == "retry_required"
    assert all(row.get("classification") == "transport_authentication_failure" for row in result["attempt_history"])


def test_consistent_native_caption_absence_requires_asr(monkeypatch) -> None:
    def fake_request(url: str, timeout: float = 50.0, headers=None):
        return 200, {
            "error": "TRANSCRIPT_UNAVAILABLE",
            "reason": "No native captions are available",
            "canTranscribeWithAI": True,
        }, {}

    monkeypatch.setattr(harvest, "request_json", fake_request)
    monkeypatch.setattr(harvest.time, "sleep", lambda *_: None)
    result = harvest.fetch_video("0h9lpMUBSlE", attempts=2, pace_seconds=0.0)
    assert result["status"] == "native_no_caption"
    assert result["can_transcribe_with_ai"] is True


def test_native_classification_does_not_equal_content_complete(tmp_path: Path) -> None:
    inventory = [
        {"video_id": "aaaaaaaaaaa", "channel_slug": "chartbro"},
        {"video_id": "bbbbbbbbbbb", "channel_slug": "chartbro"},
    ]
    outcomes = {
        "aaaaaaaaaaa": {
            "status": "ok",
            "segments": [{"index": 0, "start": 0.0, "duration": 1.0, "text": "one"}],
        },
        "bbbbbbbbbbb": {
            "status": "native_no_caption",
            "segments": [],
            "can_transcribe_with_ai": True,
        },
    }
    manifest = harvest.write_checkpoint(tmp_path, "chartbro", inventory, outcomes)
    assert manifest["native_caption_classification_complete"] is True
    assert manifest["transcript_content_complete"] is False
    assert manifest["asr_required_count"] == 1
    rows = [json.loads(line) for line in (tmp_path / "videos.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[1]["content_status"] == "asr_required"
