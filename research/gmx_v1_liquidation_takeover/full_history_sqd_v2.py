from __future__ import annotations

"""Transport-only adapter correcting the PortalClient alias in full_history_sqd."""

import full_history_sqd as history

history.portal = history.nportal


if __name__ == "__main__":
    raise SystemExit(history.main())
