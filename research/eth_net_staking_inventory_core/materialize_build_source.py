from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPLACEMENTS = [
    (
        '    "deposit_data_signature",\n}',
        '    "deposit_data_signature",\n    "deposit_proof",\n}',
    ),
    (
        '    signatures = [normalize_text(value) for value in table["deposit_data_signature"].to_pylist()]\n',
        '    signatures = [normalize_text(value) for value in table["deposit_data_signature"].to_pylist()]\n'
        '    proofs = table["deposit_proof"].to_pylist()\n',
    ),
    (
        '    event_keys = {\n'
        '        f"{root}:{pubkey}:{signature}"\n'
        '        for root, pubkey, signature in zip(roots, pubkeys, signatures, strict=True)\n'
        '    }\n',
        '    event_keys: set[str] = set()\n'
        '    for root, pubkey, signature, proof in zip(\n'
        '        roots, pubkeys, signatures, proofs, strict=True\n'
        '    ):\n'
        '        proof_parts = [normalize_text(item) for item in (proof or [])]\n'
        '        proof_hash = hashlib.sha256("|".join(proof_parts).encode()).hexdigest()\n'
        '        event_keys.add(f"{root}:{pubkey}:{signature}:{proof_hash}")\n',
    ),
    (
        '\n\ndef inspect_day(day: date, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], set[str], set[str], set[str]]:\n',
        '\n\ndef net_inventory_gwei(deposit_gwei: int, release_gwei: int) -> int:\n'
        '    return int(deposit_gwei) - int(release_gwei)\n'
        '\n\ndef inventory_totals_gwei(deposit_values: Any, release_values: Any) -> tuple[int, int, int]:\n'
        '    deposits = [int(value) for value in deposit_values]\n'
        '    releases = [int(value) for value in release_values]\n'
        '    if len(deposits) != len(releases):\n'
        '        raise ValueError("deposit/release chronology length mismatch")\n'
        '    net_values = [\n'
        '        net_inventory_gwei(deposit, release)\n'
        '        for deposit, release in zip(deposits, releases, strict=True)\n'
        '    ]\n'
        '    return sum(deposits), sum(releases), sum(net_values)\n'
        '\n\ndef inspect_day(day: date, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], set[str], set[str], set[str]]:\n',
    ),
    (
        '        "principal_amount_eth",\n',
        '        "principal_amount_gwei",\n        "principal_amount_eth",\n',
    ),
    (
        '    merged[deposit_columns] = merged[deposit_columns].fillna(0)\n',
        '    merged[deposit_columns] = merged[deposit_columns].fillna(0)\n'
        '    for column in (\n'
        '        "deposit_event_count",\n'
        '        "deposit_amount_gwei",\n'
        '        "deposit_unique_pubkeys",\n'
        '        "deposit_unique_credentials",\n'
        '    ):\n'
        '        merged[column] = merged[column].astype("int64")\n',
    ),
    (
        '    merged["principal_release_eth"] = merged["principal_amount_eth"]\n'
        '    merged["net_locked_eth"] = merged["deposit_eth"] - merged["principal_release_eth"]\n',
        '    merged["principal_release_gwei"] = merged["principal_amount_gwei"].astype("int64")\n'
        '    merged["principal_release_eth"] = merged["principal_release_gwei"] / 1e9\n'
        '    merged["net_locked_gwei"] = [\n'
        '        net_inventory_gwei(deposit, release)\n'
        '        for deposit, release in zip(\n'
        '            merged["deposit_amount_gwei"],\n'
        '            merged["principal_release_gwei"],\n'
        '            strict=True,\n'
        '        )\n'
        '    ]\n'
        '    merged["net_locked_eth"] = merged["net_locked_gwei"] / 1e9\n',
    ),
    (
        '    total_deposit_gwei = sum(item["total_gwei"] for item in daily_rows)\n'
        '    total_principal_eth = float(merged["principal_release_eth"].sum())\n'
        '    total_deposit_eth = total_deposit_gwei / 1e9\n'
        '    total_net_eth = float(merged["net_locked_eth"].sum())\n'
        '    if abs((total_deposit_eth - total_principal_eth) - total_net_eth) > 1e-6:\n'
        '        raise ValueError("net-staking amount conservation failed")\n',
        '    raw_deposit_gwei = sum(int(item["total_gwei"]) for item in daily_rows)\n'
        '    total_deposit_gwei, total_principal_gwei, total_net_gwei = inventory_totals_gwei(\n'
        '        merged["deposit_amount_gwei"], merged["principal_release_gwei"]\n'
        '    )\n'
        '    if net_inventory_gwei(total_deposit_gwei, total_principal_gwei) != total_net_gwei:\n'
        '        raise ValueError("net-staking integer-Gwei conservation failed")\n'
        '    total_deposit_eth = total_deposit_gwei / 1e9\n'
        '    total_principal_eth = total_principal_gwei / 1e9\n'
        '    total_net_eth = total_net_gwei / 1e9\n',
    ),
    (
        '        "deposit_total_eth": total_deposit_eth,\n'
        '        "deposit_unique_pubkeys": len(pubkeys),\n',
        '        "raw_deposit_total_gwei": raw_deposit_gwei,\n'
        '        "raw_deposit_total_eth": raw_deposit_gwei / 1e9,\n'
        '        "aligned_deposit_total_gwei": total_deposit_gwei,\n'
        '        "deposit_total_eth": total_deposit_eth,\n'
        '        "deposit_unique_pubkeys": len(pubkeys),\n',
    ),
    (
        '        "principal_release_total_eth": total_principal_eth,\n'
        '        "net_locked_total_eth": total_net_eth,\n',
        '        "principal_release_total_gwei": total_principal_gwei,\n'
        '        "principal_release_total_eth": total_principal_eth,\n'
        '        "net_locked_total_gwei": total_net_gwei,\n'
        '        "net_locked_total_eth": total_net_eth,\n',
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    text = (root / "build_source.py").read_text()
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"expected one source occurrence, found {count}: {old[:60]!r}")
        text = text.replace(old, new)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "build_source.py").write_text(text)
    shutil.copy2(root / "test_build_source.py", args.out / "test_build_source.py")
    print("materialized deposit-proof, common-window and integer-Gwei source reader")


if __name__ == "__main__":
    main()
