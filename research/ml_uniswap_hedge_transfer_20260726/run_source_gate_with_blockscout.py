from __future__ import annotations

import probe_uniswap_swaps as core


BLOCKSCOUT_ETH_RPC = "https://eth.blockscout.com/api/eth-rpc"


def main() -> int:
    # Transport-only correction recorded before any market or model outcome.
    # Preserve all scientific constants and append the existing endpoints as failovers.
    core.ENDPOINTS = (BLOCKSCOUT_ETH_RPC,) + tuple(
        endpoint for endpoint in core.ENDPOINTS if endpoint != BLOCKSCOUT_ETH_RPC
    )
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
