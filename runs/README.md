# Run reports

Each lane produces an append-only report named:

`RUN__<epoch>__<lane>__<task>__<timestamp>.md`

A run report records base revision, task, assumptions, inputs, code/data versions, validation, metrics, failures, created artifacts, GitHub branch/commit/PR, Drive paths, and the next exact action. It proposes a state patch but does not directly overwrite shared state.
