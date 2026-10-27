# Session & Token Efficiency

- Do not re-read files already in context unless they've changed.
- Read only the files relevant to the current task, not the whole directory tree.
- Prefer targeted Grep/Glob over opening large files fully when just locating something.
- `memory-bank/activeContext.md` and `memory-bank/progress.md` are imported by CLAUDE.md at session start; read the other memory-bank files on demand.
- At the end of a work session (or after completing 1-2 features), update `memory-bank/progress.md` and `memory-bank/activeContext.md` with current state, then recommend `/clear` or a fresh session for the next feature.
