# Data retention and provenance

- Preserve original user-provided raw files immutably.
- Do not automatically store full copyrighted videos. Store canonical links, permitted transcripts, metadata, and research notes.
- Store open-access or licensed papers; otherwise retain citation and URL only.
- Every derived artifact records source IDs, transform version, timestamp, and checksum.
- Duplicates are detected by canonical URL and SHA-256. Conflicting duplicates move to quarantine rather than overwriting the original.
- Drive is not a dumping ground: every durable file must be discoverable through a registry or manifest.
- Old snapshots and superseded processed outputs move to archive; current registries remain small and queryable.
