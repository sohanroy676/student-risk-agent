---
description: Implement a feature end-to-end on a branch with tests, review and commit
argument-hint: <feature description>
---

# /new-feature $ARGUMENTS

1. Restate acceptance criteria (inputs/outputs, edge cases, what "done" looks like) before writing code. If the request is vague, ask for the missing specifics first.
2. Check `memory-bank/architecture.md` and `memory-bank/systemPatterns.md` for conventions, and `ROADMAP.md` to confirm the feature's priority/scope matches the plan.
3. Create a feature branch (`.claude/rules/git-workflow.md`).
4. Implement with minimal, targeted changes.
5. Write/update tests per `.claude/rules/testing.md` and run the full suite.
6. Run `ruff check . && mypy app` and `ruff format .`; fix all warnings.
7. Self-review per `.claude/rules/code-quality-review.md`.
8. Commit per `.claude/rules/commit-style.md`.
9. Update `memory-bank/progress.md` and `activeContext.md`, and update ROADMAP.md to move this feature out of "Now"/"Next" (CHANGELOG.md is regenerated via `/commit`, step 7).
10. Summarize the change in plain English and note it's ready for review/merge (do not push or merge without approval).
