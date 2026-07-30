from __future__ import annotations

"""Transport-only wrapper for the outcome-sealed GMX V1 source gate.

The event ABI, six frozen windows, semantic correction, source delay and all
scientific gates remain owned by the parent modules.  This wrapper changes only
keyless RPC endpoint order, pacing and the initial eth_getLogs chunk so a slow
but technically responsive endpoint cannot consume the whole run budget.
"""

import probe_gmx_v1_liquidations_semantic as semantic

base = semantic.base

# No market outcome has been opened. These are transport-only amendments.
base.ENDPOINTS = (
    "https://arbitrum-one-rpc.publicnode.com",
    "https://arb1.arbitrum.io/rpc",
    "https://arbitrum.blockscout.com/api/eth-rpc",
)
base.MIN_REQUEST_INTERVAL_SECONDS = 0.02
base.BLOCK_TIMESTAMP_BATCH_SIZE = 100

_original_get_logs_adaptive = base.get_logs_adaptive


def _faster_get_logs_adaptive(
    rpc,
    *,
    address: str,
    from_block: int,
    to_block: int,
    topic0: str,
    maximum_chunk: int = 1_500_000,
):
    return _original_get_logs_adaptive(
        rpc,
        address=address,
        from_block=from_block,
        to_block=to_block,
        topic0=topic0,
        maximum_chunk=maximum_chunk,
    )


base.get_logs_adaptive = _faster_get_logs_adaptive


if __name__ == "__main__":
    raise SystemExit(semantic.main())
