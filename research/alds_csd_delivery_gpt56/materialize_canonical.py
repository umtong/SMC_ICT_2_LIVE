#!/usr/bin/env python3
"""Materialize and verify the immutable BTC/ETH canonical Bybit shards."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import gdown

ARCHIVES = (
    ("BTCUSDT", "PRE_2024_2021", "1kzyUwgZfWNlZwIXGIgAKQhFHZmzlVHlM", "7b54adac09cb9aadb9208288f23167f154e40fe430da1be85794a38bf401e3ca"),
    ("ETHUSDT", "PRE_2024_2021", "1TQi1khEWNYHL692Y2xeW3l6-P9Tcwv6A", "b2ff98c7ea8968ec942bdf79a69fcd75d37871ca9ca9d6c42778ecf098945295"),
    ("BTCUSDT", "PRE_2024_2022", "1lEZQCE-T4OXcGVaLN9HFAekCnXaUmeQ6", "273995bf7efd905c147237ff14978b92ef65f4703b290986ba6fab5fe5e3e42c"),
    ("ETHUSDT", "PRE_2024_2022", "1bP0MizmZhSwhEOkf6YodfuCxbMZZYYu7", "681cb5c21826f05a12e40b25818c40d1be46cf4b394676998d8a6856180271da"),
    ("BTCUSDT", "PRE_2024_2023", "1HIJ4ARuF99IujRC6fzNiXo2d4tItkVMt", "ee145ba1dd51fe24357940a4a6a9ffe99f52a45f983c7e191ff38dece6ec3a46"),
    ("ETHUSDT", "PRE_2024_2023", "1F8lghO2sG_b2PeHkvr3UQE5nGdCUGoIR", "87dbd84278f6cfd93c841e2312429915aa3a4877e931abf77650ae5d3506f322"),
    ("BTCUSDT", "2024_H1", "1RMgFypk0P4WX99WJRN1FWkqOJICf2VC3", "95c932c4ce6e397738219e0bf5ad94defbbadb7dab215716fdd65438a4484eac"),
    ("ETHUSDT", "2024_H1", "19ZE-pM5YseslNAL99KLZGKqUuQtVP3Xa", "58a10d224918d078b5738d37d9b0fbb20d9448f20a875e83b68d224ef3f9cef9"),
    ("BTCUSDT", "2024_H2", "12M6ZthEtG5GwndvoowlgmhEf8Yhbio6V", "048d550c45dff8dcd82df275764d648e79f8940df6fa1d156877f54b1e8fbcf3"),
    ("ETHUSDT", "2024_H2", "1-K5nE6sVJYSrRSY2dUfDyxcdAHxEs0YJ", "aa7b411c7b55d70be3eed60d2d34d17343f6fe17219cdd2b9418c94921580310"),
    ("BTCUSDT", "2025_H1", "13ewfXYY9mr7qU8YlxJq90MRkQZzIFj6k", "fa4ba248f74208f68a48a968fa6fbce939b16e76e94d22dc4a5683aa9597cde4"),
    ("ETHUSDT", "2025_H1", "15ng-iWym4oNj-Urmv4ZnRdGu_vpM7lWs", "5d6045dc5dafea748e62da98b27f58273f67e19c90f9797601b3aa97b81e9c2b"),
    ("BTCUSDT", "2025_H2", "1d8yIseheJ-IrZNNAXlIB69koDflN61Yl", "da65aa01c4ea1c0838c545a70213e8d7ab51b3f7a4089a9b28e2b6a7f2e2d176"),
    ("ETHUSDT", "2025_H2", "1hqNk1pSLF4vf0OmCDMaQcw7xqIoe-UUK", "def68deb10b29c3fe0f3ce88254025b3076463a7f5a1bcea0ac8670f72eca9ff"),
    ("BTCUSDT", "2026_H1", "1skEcgUHeykzFD3c8eFUblwFgo_oZEXLe", "f103098b57d12e7bc6ca3c3d002fe1699dc265e9d72e296414de341156ba549d"),
    ("ETHUSDT", "2026_H1", "13gwTwb_Saxe5xj5fiuLRFHA2DjrdGLzF", "1b178986ee20f20f23d1eed048ef8403f8c6d5e2cd3b3e965f99e8ab1bd08418"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def materialize(cache: Path, root: Path) -> list[dict[str, str]]:
    cache.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    evidence: list[dict[str, str]] = []
    for symbol, segment, file_id, expected_archive in ARCHIVES:
        dataset_id = f"DS-BYBIT-LINEAR-{symbol}-{segment}-CANONICAL-V1"
        archive = cache / f"{dataset_id}.zip"
        if not archive.exists() or sha256(archive) != expected_archive:
            archive.unlink(missing_ok=True)
            downloaded = gdown.download(id=file_id, output=str(archive), quiet=False)
            if not downloaded:
                raise RuntimeError(f"download failed: {dataset_id}")
        actual_archive = sha256(archive)
        if actual_archive != expected_archive:
            raise RuntimeError(f"archive hash mismatch: {dataset_id}: {actual_archive}")

        destination = root / symbol / segment
        shutil.rmtree(destination, ignore_errors=True)
        destination.mkdir(parents=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)

        manifest_path = destination / "DATASET_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dataset_id") != dataset_id:
            raise RuntimeError(f"dataset identity mismatch: {dataset_id}")
        expected_manifest = (destination / "DATASET_MANIFEST.sha256").read_text(encoding="utf-8").split()[0]
        actual_manifest = sha256(manifest_path)
        if actual_manifest != expected_manifest:
            raise RuntimeError(f"manifest hash mismatch: {dataset_id}")
        item = {
            "dataset_id": dataset_id,
            "drive_file_id": file_id,
            "archive_sha256": actual_archive,
            "manifest_sha256": actual_manifest,
        }
        evidence.append(item)
        print(json.dumps(item), flush=True)
    (root / "MATERIALIZATION.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    materialize(args.cache, args.root)


if __name__ == "__main__":
    main()
