# Durable decisions

## 2026-07-25 — Fresh canonical project

- `umtong/SMC_ICT_2_LIVE` starts without importing strategy state or Champion claims from other repositories.
- GitHub is the versioned public project layer; Google Drive is the private high-frequency data and live-state layer.
- Private Drive identifiers are not committed to the public repository.
- External sources are registered once and reused; duplicate search and download are avoided through canonical URL and SHA-256 matching.
- Multiple chats may work concurrently, but only the coordinator merges shared state.
