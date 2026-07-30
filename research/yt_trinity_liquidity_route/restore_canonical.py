#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

SEGMENTS = ("PRE_2024_2021", "PRE_2024_2022", "PRE_2024_2023", "2024_H1")
SYMBOLS = ("BTCUSDT", "ETHUSDT")


def latest_artifact(repository: str, token: str, name: str) -> dict | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{repository}/actions/artifacts?name={quote(name)}&per_page=100"
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    rows = [row for row in response.json().get("artifacts", []) if not row.get("expired")]
    return max(rows, key=lambda row: row.get("created_at", ""), default=None)


def restore_artifact(repository: str, token: str, name: str, destination: Path) -> bool:
    artifact = latest_artifact(repository, token, name)
    if artifact is None:
        return False
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = requests.get(
        artifact["archive_download_url"],
        headers=headers,
        timeout=240,
        allow_redirects=True,
    )
    response.raise_for_status()
    with tempfile.TemporaryDirectory() as temp_dir:
        archive = Path(temp_dir) / "artifact.zip"
        archive.write_bytes(response.content)
        extracted = Path(temp_dir) / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(extracted)
        manifests = list(extracted.rglob("DATASET_MANIFEST.json"))
        if len(manifests) != 1:
            raise RuntimeError(f"{name}: expected one manifest, found {len(manifests)}")
        source_root = manifests[0].parent
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source_root, destination)
    print(f"restored {name} artifact_id={artifact['id']} digest={artifact.get('digest')}")
    return True


def run(args: argparse.Namespace) -> None:
    repository = args.repository or os.environ.get("GITHUB_REPOSITORY")
    token = args.token or os.environ.get("GH_TOKEN")
    if not repository or not token:
        raise SystemExit("repository and GH token are required")
    data_root = args.data_root.resolve()
    canonical_repo = args.canonical_repo.resolve()
    builder = canonical_repo / "scripts/market_data/build_canonical_bybit.py"
    verifier = canonical_repo / "scripts/market_data/verify_canonical_bybit.py"
    if not builder.is_file() or not verifier.is_file():
        raise SystemExit(f"canonical implementation missing under {canonical_repo}")

    for segment in SEGMENTS:
        for symbol in SYMBOLS:
            destination = data_root / segment / symbol
            if not (destination / "DATASET_MANIFEST.json").exists():
                name = f"canonical-bybit-core-{segment}-{symbol}"
                if not restore_artifact(repository, token, name, destination):
                    print(f"artifact {name} absent; rebuilding exact canonical shard")
                    subprocess.run(
                        [
                            "python",
                            str(builder),
                            "--segment",
                            segment,
                            "--symbol",
                            symbol,
                            "--base-url",
                            "https://api.manepa.jp",
                            "--timeout",
                            "30",
                            "--max-attempts",
                            "8",
                            "--min-request-interval",
                            "0.10",
                            "--out",
                            str(data_root),
                        ],
                        check=True,
                        env={**os.environ, "PYTHONPATH": str(canonical_repo / "scripts/market_data")},
                    )
            subprocess.run(
                ["python", str(verifier), str(destination)],
                check=True,
                env={**os.environ, "PYTHONPATH": str(canonical_repo / "scripts/market_data")},
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--canonical-repo", type=Path, required=True)
    parser.add_argument("--repository")
    parser.add_argument("--token")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
