"""Execute the sealed sweep/crowding engine with corrected official Bybit V5 transport."""
from __future__ import annotations

from . import run as sealed_run
from .source_v5 import download_bybit_months_v5

# The economic engine imports the acquisition function into module scope.  Replace
# only that failed transport before its CLI loads the unchanged sealed contract.
sealed_run.download_bybit_months = download_bybit_months_v5


def main() -> int:
    return sealed_run.main()


if __name__ == "__main__":
    raise SystemExit(main())
