from __future__ import annotations

import probe_uniswap_swaps_bounded as bounded


BLOCKSCOUT_ETH_RPC = "https://eth.blockscout.com/api/eth-rpc"


def main() -> int:
    # Transport-only corrections were recorded before any market or model outcome.
    # Preserve every scientific constant and use Blockscout first, with the existing
    # endpoints as deterministic failovers under the bounded historical-log contract.
    bounded.base.ENDPOINTS = (BLOCKSCOUT_ETH_RPC,) + tuple(
        endpoint
        for endpoint in bounded.base.ENDPOINTS
        if endpoint != BLOCKSCOUT_ETH_RPC
    )
    return bounded.main()


if __name__ == "__main__":
    raise SystemExit(main())
