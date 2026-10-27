# Testing Requirements

After implementing any feature or fix:

1. Check if tests already exist for the changed code.
2. If no tests exist, write tests covering:
    - The main expected behavior (happy path)
    - Edge cases (empty input, null/undefined, boundary values, large inputs)
    - Error/failure paths (invalid input, network failure, etc. where relevant)
3. Write tests "as if trying to break the feature" — genuinely adversarial, not just re-confirming the code does what it does.
4. Run the FULL test suite (not just new tests) to catch regressions.
5. If any test fails, debug and fix the root cause before proceeding. Never comment out or delete a failing test to make the suite pass.
6. Only after all tests pass, proceed to the commit workflow.

Test framework, location, and naming are defined in `memory-bank/tech-stack.md` (tests/ mirrors app/, e.g. `tests/features/test_*.py`; UI tests in `web/e2e/*.spec.ts`) — follow that convention exactly rather than guessing.
