#!/usr/bin/env python3
"""Collect authored public YouTube page text without loading or retaining media."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


WS = re.compile(r"\s+")


def clean(value: Any, limit: int = 50_000) -> str:
    text = WS.sub(" ", str(value or "")).strip()
    return text[:limit]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_inventory(path: Path, shard_index: int, shard_count: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: (row["channel_slug"], row["video_id"]))
    selected = [row for index, row in enumerate(rows) if index % shard_count == shard_index]
    if not selected:
        raise RuntimeError("empty shard")
    return selected


def extract(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const player = window.ytInitialPlayerResponse || {};
          const details = player.videoDetails || {};
          const micro = player.microformat?.playerMicroformatRenderer || {};
          const meta = (selector) => document.querySelector(selector)?.content || '';
          const text = (selector) => document.querySelector(selector)?.innerText || '';
          const chapters = [...document.querySelectorAll('ytd-macro-markers-list-item-renderer, ytd-chapter-renderer')]
            .map(node => node.innerText || '').filter(Boolean);
          const links = [...document.querySelectorAll('#description a, #description-inline-expander a')]
            .map(node => ({text: node.innerText || '', href: node.href || ''})).slice(0, 100);
          return {
            document_title: document.title,
            meta_title: meta('meta[name="title"]') || meta('meta[property="og:title"]'),
            meta_description: meta('meta[name="description"]') || meta('meta[property="og:description"]'),
            canonical: document.querySelector('link[rel="canonical"]')?.href || '',
            player_title: details.title || '',
            short_description: details.shortDescription || '',
            length_seconds: details.lengthSeconds || null,
            author: details.author || '',
            channel_id: details.channelId || '',
            view_count: details.viewCount || null,
            keywords: details.keywords || [],
            publish_date: micro.publishDate || '',
            upload_date: micro.uploadDate || '',
            category: micro.category || '',
            owner_channel_name: micro.ownerChannelName || '',
            description_dom: text('#description-inline-expander') || text('#description'),
            chapters,
            description_links: links,
            body_prefix: (document.body?.innerText || '').slice(0, 30000),
          };
        }"""
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    inventory = load_inventory(args.inventory, args.shard_index, args.shard_count)
    rows: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36",
            viewport={"width": 1440, "height": 1000},
        )
        context.add_cookies([
            {"name": "CONSENT", "value": "YES+cb.20210328-17-p0.en+FX+917", "domain": ".youtube.com", "path": "/"},
            {"name": "PREF", "value": "hl=ko&gl=KR", "domain": ".youtube.com", "path": "/"},
        ])
        page = context.new_page()
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"media", "image", "font"}
            else route.continue_(),
        )
        for position, item in enumerate(inventory, start=1):
            video_id = item["video_id"]
            url = f"https://www.youtube.com/watch?v={video_id}&hl=ko&gl=KR"
            started = time.monotonic()
            row = dict(item)
            row.update({"page_status": "failed", "page_error": None})
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=50_000)
                page.wait_for_timeout(2500)
                payload = extract(page)
                challenge = "로그인하여 봇이 아님을 확인" in payload.get("body_prefix", "") or "confirm you’re not a bot" in payload.get("body_prefix", "").lower()
                row.update({
                    "page_status": "ok" if any(payload.get(key) for key in ("player_title", "meta_title", "short_description", "meta_description")) else "metadata_missing",
                    "http_status": response.status if response else None,
                    "final_url": page.url,
                    "challenge_detected": challenge,
                    "document_title": clean(payload.get("document_title")),
                    "title": clean(payload.get("player_title") or payload.get("meta_title") or item.get("title")),
                    "short_description": clean(payload.get("short_description")),
                    "meta_description": clean(payload.get("meta_description")),
                    "description_dom": clean(payload.get("description_dom")),
                    "length_seconds": payload.get("length_seconds"),
                    "author": clean(payload.get("author")),
                    "channel_id_from_page": clean(payload.get("channel_id")),
                    "view_count": payload.get("view_count"),
                    "keywords": [clean(value, 500) for value in payload.get("keywords", []) if clean(value, 500)],
                    "publish_date": clean(payload.get("publish_date")),
                    "upload_date_from_page": clean(payload.get("upload_date")),
                    "category": clean(payload.get("category")),
                    "chapters": [clean(value, 2000) for value in payload.get("chapters", []) if clean(value, 2000)],
                    "description_links": payload.get("description_links", []),
                    "body_prefix": clean(payload.get("body_prefix"), 30_000),
                })
            except Exception as exc:
                row["page_error"] = f"{type(exc).__name__}: {exc}"
            row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            canonical = {
                key: row.get(key)
                for key in (
                    "video_id", "channel_slug", "title", "short_description", "meta_description",
                    "description_dom", "chapters", "keywords", "publish_date", "upload_date_from_page",
                )
            }
            row["authored_text_sha256"] = hashlib.sha256(
                json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            rows.append(row)
            (args.output / "pages.jsonl").write_text(
                "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in rows),
                encoding="utf-8",
            )
            print(json.dumps({"position": position, "video_id": video_id, "status": row["page_status"], "challenge": row.get("challenge_detected")}, ensure_ascii=False), flush=True)
        browser.close()
    raw = (args.output / "pages.jsonl").read_bytes()
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "source_sha": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "inventory_count": len(inventory),
        "completed_count": len(rows),
        "status_counts": {
            status: sum(row["page_status"] == status for row in rows)
            for status in sorted({row["page_status"] for row in rows})
        },
        "challenge_count": sum(bool(row.get("challenge_detected")) for row in rows),
        "pages_sha256": hashlib.sha256(raw).hexdigest(),
        "built_at_utc": utc_now(),
        "media_loaded": False,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
