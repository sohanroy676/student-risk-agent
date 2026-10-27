# Commit Workflow & Message Style

After implementing a feature or fix, and only after tests pass (see testing.md), commit when the user asks or when running the `/commit` or `/new-feature` commands:

1. Run `git status` and `git diff` to review all changes.
2. Stage only the relevant files with `git add <paths>` (never `git add .` blindly if unrelated files changed).
3. Write a Conventional Commits style message:
    - Format: `type(scope): short summary` (summary under 50 chars, imperative mood)
    - Types: feat, fix, refactor, chore, docs, test, perf, style
    - Add a short body (1-3 lines) explaining WHY the change was made, not just what.
    - Example: `fix(auth): handle expired token edge case in refresh flow`
    - Example: `feat(cart): add quantity validation before checkout`
4. Commit the changes.
5. Do NOT run `git push` automatically — always wait for explicit user approval before pushing.
6. Never commit directly to `main`/`master` — work on a feature branch (see git-workflow.md).
