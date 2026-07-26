from pathlib import Path

from scripts.youtube.research_triad_channels import deduplicate_inventory, parse_vtt


def test_deduplicate_inventory_merges_tabs():
    rows = [
        {
            "channel_key": "easychart",
            "video_id": "abcdefghijk",
            "tab": "videos",
            "flat_timestamp": 1,
        },
        {
            "channel_key": "easychart",
            "video_id": "abcdefghijk",
            "tab": "streams",
            "flat_timestamp": 1,
        },
    ]
    result = deduplicate_inventory(rows)
    assert len(result) == 1
    assert result[0]["tabs"] == ["videos", "streams"]


def test_parse_vtt_removes_markup_and_duplicate_rolling_cues(tmp_path: Path):
    source = tmp_path / "sample.vtt"
    source.write_text(
        """WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "<c>유동성</c> 스윕\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "<c>유동성</c> 스윕\n\n"
        "00:00:02.000 --> 00:00:03.000\n"
        "FVG 확인\n"
        """,
        encoding="utf-8",
    )
    cues = parse_vtt(source)
    assert cues == [
        ("00:00:00.000", "유동성 스윕"),
        ("00:00:02.000", "FVG 확인"),
    ]
