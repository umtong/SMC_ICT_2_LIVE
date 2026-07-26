# Sources

- Bybit public MetaTrader 4 hourly archives: `https://public.bybit.com/kline_for_metatrader4/`.
- Bybit V5 public funding history: `GET https://api.bybit.com/v5/market/funding/history`.
- The workflow constructs only 2021-10 through 2023-12 URLs. Source generation rejects every 2024-2026 market period.
- Each downloaded file is hashed and recorded before model fitting.
- If complete historical funding cannot be retrieved, the runner charges an adverse 2bp reserve at every crossed UTC 00:00, 08:00 and 16:00 settlement instead of silently dropping funding.
