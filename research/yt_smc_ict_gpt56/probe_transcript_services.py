from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

VIDEO_ID = "0h9lpMUBSlE"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"

SERVICES = {
    "yttools": "https://yttools.co/",
    "quicktranscript": "https://quicktranscript.ai/",
    "vidkitt": "https://vidkitt.com/transcript-extractor",
    "theyoutubetranscript": "https://theyoutubetranscript.com/",
    "transcribeyoutube": "https://transcribeyoutube.com/",
    "scriptgrab": "https://www.texttube.online/",
    "transcript_api_com": "https://transcript-api.com/",
    "quicktranscript_api_page": "https://quicktranscript.ai/transcript-api",
}

COMMON_ENDPOINTS = (
    "/api/transcript",
    "/api/transcripts",
    "/api/youtube/transcript",
    "/api/youtube-transcript",
    "/api/extract-transcript",
    "/api/extract",
    "/api/transcribe",
    "/api/v1/transcript",
    "/api/v1/youtube/transcript",
    "/api/v2/youtube/transcript",
)

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def preview(text: str, limit: int = 1800) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def looks_like_transcript(value: Any) -> bool:
    serialized = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    lower = serialized.lower()
    return len(serialized) > 500 and any(
        token in lower
        for token in (
            "transcript",
            "segments",
            "captions",
            "가격",
            "시장",
            "유동성",
            "cisd",
        )
    )


def script_urls(session: requests.Session, page_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for node in soup.find_all("script"):
        src = node.get("src")
        if not src:
            continue
        absolute = urllib.parse.urljoin(page_url, src)
        if urllib.parse.urlparse(absolute).netloc == urllib.parse.urlparse(page_url).netloc:
            urls.append(absolute)
    return list(dict.fromkeys(urls))[:40]


def discover_api_strings(text: str, origin: str) -> list[str]:
    found: list[str] = []
    patterns = (
        r"[\"'](\/api\/[A-Za-z0-9_?&=./{}:\-]+)[\"']",
        r"fetch\(\s*[\"']([^\"']*transcript[^\"']*)[\"']",
        r"axios\.(?:get|post)\(\s*[\"']([^\"']+)[\"']",
        r"[\"'](https://[^\"']+/(?:api|v1|v2)/[^\"']+)[\"']",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            raw = match.group(1).replace("\\/", "/")
            raw = re.sub(r"[),;]+$", "", raw)
            if not raw or len(raw) > 300:
                continue
            absolute = urllib.parse.urljoin(origin, raw)
            if "transcript" in absolute.lower() or "/api/" in absolute.lower():
                found.append(absolute)
    return list(dict.fromkeys(found))


def response_record(response: requests.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    text = response.text
    parsed: Any = None
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        try:
            parsed = response.json()
        except Exception:
            parsed = None
    return {
        "status": response.status_code,
        "content_type": content_type,
        "characters": len(text),
        "looks_like_transcript": looks_like_transcript(parsed if parsed is not None else text),
        "preview": preview(json.dumps(parsed, ensure_ascii=False) if parsed is not None else text),
    }


def attempt_endpoint(session: requests.Session, endpoint: str) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    parsed = urllib.parse.urlparse(endpoint)
    clean_endpoint = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    payloads = [
        {"url": VIDEO_URL},
        {"videoUrl": VIDEO_URL},
        {"video_url": VIDEO_URL},
        {"youtubeUrl": VIDEO_URL},
        {"videoId": VIDEO_ID},
        {"video_id": VIDEO_ID},
    ]
    for method, payload in [("GET", payloads[0]), ("GET", payloads[-1]), ("POST_JSON", payloads[0]), ("POST_JSON", payloads[-1]), ("POST_FORM", payloads[0])]:
        try:
            if method == "GET":
                response = session.get(clean_endpoint, params=payload, timeout=45, allow_redirects=True)
            elif method == "POST_JSON":
                response = session.post(clean_endpoint, json=payload, timeout=60, allow_redirects=True)
            else:
                response = session.post(clean_endpoint, data=payload, timeout=60, allow_redirects=True)
            record = {
                "method": method,
                "payload_keys": sorted(payload.keys()),
                "final_url": response.url,
                **response_record(response),
            }
            attempts.append(record)
            if record["looks_like_transcript"]:
                break
            if response.status_code in {401, 402, 403, 404, 405, 429} and method == "GET":
                continue
        except Exception as exc:
            attempts.append({"method": method, "payload_keys": sorted(payload.keys()), "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.25)
    return attempts


def probe_service(name: str, page_url: str) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.5",
            "Origin": urllib.parse.urlunparse((*urllib.parse.urlparse(page_url)[:2], "", "", "", "")),
            "Referer": page_url,
        }
    )
    out: dict[str, Any] = {"page_url": page_url, "page": None, "scripts": [], "discovered_endpoints": [], "attempts": {}}
    try:
        response = session.get(page_url, timeout=45, allow_redirects=True)
        out["page"] = response_record(response)
        html = response.text
    except Exception as exc:
        out["page"] = {"error": f"{type(exc).__name__}: {exc}"}
        html = ""

    origin = urllib.parse.urlunparse((*urllib.parse.urlparse(page_url)[:2], "", "", "", ""))
    endpoints = [urllib.parse.urljoin(origin, path) for path in COMMON_ENDPOINTS]
    endpoints.extend(discover_api_strings(html, origin))

    for script_url in script_urls(session, page_url, html):
        script_record: dict[str, Any] = {"url": script_url}
        try:
            response = session.get(script_url, timeout=45)
            text = response.text
            script_record.update({"status": response.status_code, "characters": len(text), "preview": preview(text, 300)})
            endpoints.extend(discover_api_strings(text, origin))
        except Exception as exc:
            script_record["error"] = f"{type(exc).__name__}: {exc}"
        out["scripts"].append(script_record)

    # Keep same-origin endpoints and prioritize transcript-specific paths.
    same_origin: list[str] = []
    origin_host = urllib.parse.urlparse(origin).netloc
    for endpoint in endpoints:
        if urllib.parse.urlparse(endpoint).netloc != origin_host:
            continue
        if endpoint not in same_origin:
            same_origin.append(endpoint)
    same_origin.sort(key=lambda value: ("transcript" not in value.lower(), len(value), value))
    same_origin = same_origin[:18]
    out["discovered_endpoints"] = same_origin

    for endpoint in same_origin:
        attempts = attempt_endpoint(session, endpoint)
        out["attempts"][endpoint] = attempts
        if any(item.get("looks_like_transcript") for item in attempts):
            out["working_endpoint"] = endpoint
            break
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifact/transcript_service_probe.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result: dict[str, Any] = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "video_id": VIDEO_ID,
        "video_url": VIDEO_URL,
        "services": {},
    }
    for name, url in SERVICES.items():
        print(f"probing {name}: {url}", flush=True)
        result["services"][name] = probe_service(name, url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
