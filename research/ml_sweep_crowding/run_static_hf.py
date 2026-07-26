"""Execute the sealed sweep/crowding engine with source correction 003 only."""
from __future__ import annotations

from . import run as sealed_run
from .source_static_hf import download_bybit_months_static, load_market_static_hf

# Replace only the pre-outcome failed source transport. Model, features,
# labels, account, costs, latency, periods and selection remain sealed.
sealed_run.download_bybit_months = download_bybit_months_static
sealed_run.load_market = load_market_static_hf


def main() -> int:
    return sealed_run.main()


if __name__ == "__main__":
    raise SystemExit(main())
