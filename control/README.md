# Control state

This directory is a small Git mirror of durable project state. Google Drive is the live collaborative surface. The coordinator reconciles Drive and Git at meaningful milestones.

- `current-state.md`: concise current state and next exact action.
- `champion.json`: current validated Champion or an explicit null state.
- `task-board.csv`: durable task assignments mirrored from the live Drive board.
- `decisions.md`: append-only durable decisions.

Research lanes must not independently overwrite these files. They write run reports and propose state patches for coordinator merge.
