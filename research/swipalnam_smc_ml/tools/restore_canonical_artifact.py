#!/usr/bin/env python3
"""Restore one recent canonical Bybit GitHub Actions artifact, or fail clearly."""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--segment", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("GITHUB_TOKEN is required")
    name = f"canonical-bybit-core-{args.segment}-{args.symbol}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {args.token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    endpoint = f"https://api.github.com/repos/{args.repository}/actions/artifacts"
    response = requests.get(endpoint, headers=headers, params={"name": name, "per_page": 100}, timeout=30)
    response.raise_for_status()
    artifacts = [item for item in response.json().get("artifacts", []) if not item.get("expired")]
    if not artifacts:
        return 2
    artifacts.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    artifact = artifacts[0]
    download = requests.get(
        f"https://api.github.com/repos/{args.repository}/actions/artifacts/{artifact['id']}/zip",
        headers=headers,
        timeout=180,
        allow_redirects=True,
    )
    download.raise_for_status()
    destination = args.destination_root / args.segment / args.symbol
    with tempfile.TemporaryDirectory(prefix="canonical-artifact-") as temporary:
        archive = Path(temporary) / "artifact.zip"
        archive.write_bytes(download.content)
        extracted = Path(temporary) / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(extracted)
        manifests = list(extracted.rglob("DATASET_MANIFEST.json"))
        if len(manifests) != 1:
            raise RuntimeError(f"expected one DATASET_MANIFEST.json in {name}; found {len(manifests)}")
        source = manifests[0].parent
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    print(f"restored {name} artifact_id={artifact['id']} to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
