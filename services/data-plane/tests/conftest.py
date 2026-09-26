"""Repository-wide (`services/data-plane`) pytest configuration.

Phase 18B (`problems_final_review.md` P3-9): three `pytest.skip(...)`
call sites -- one in
`tests/subsetting/test_selection.py::test_select_risk_edge_case_max_members_caps_the_pool`,
two in
`tests/masking/test_dataset_masker_against_real_estate.py::test_partner_feed_pat_id_alias_shares_scope_with_member_id`
-- each guarding a synthetic-data edge
case (e.g. "no partner v2 records generated at this seed/scale") that is
not guaranteed to occur at every seed/scale. None has ever fired in a
real run at this repository's current seed/scale defaults, but because
they are data-dependent rather than environment-dependent, a future
change to the generator could start them skipping silently with no
signal distinguishing "didn't occur this run" from "a generator
regression stopped producing this edge case at all."

`record_skip_guard_fired` (below) is what makes that loud rather than
silent: every one of the three call sites now calls it immediately
before `pytest.skip(...)`, which (a) raises a real `pytest.PytestWarning`
-- visible in every run's "warnings summary," the same place any other
real warning in this suite already surfaces -- and (b) is tallied here
and reported as its own terminal-summary section on every run, so "0/3
guards fired" or "2/3 guards fired" is an explicit, unmissable line in
this package's own test output, not something a reader has to notice is
*absent* from a list of failures.

Exposed as a **fixture**, not a plain module-level import: several
subdirectories under `tests/` (`subsetting/`, `certification/`, etc.)
have their own local `conftest.py`, and this package has no `__init__.py`
files making each test directory a real Python package -- so a bare
`from conftest import record_skip_guard_fired` from a nested test module
resolves to whichever `conftest.py` Python happened to cache first under
the generic module name `conftest`, not necessarily this one. Pytest's
own fixture-injection mechanism (matching by *name*, not by import path)
has no such collision, which is exactly why every other cross-cutting
helper in this style of test suite is a fixture rather than an import.
"""

from __future__ import annotations

import warnings

import pytest

_SKIP_GUARDS_FIRED: list[str] = []


def _record_skip_guard_fired(reason: str) -> None:
    _SKIP_GUARDS_FIRED.append(reason)
    warnings.warn(
        f"data-dependent test guard fired and skipped a real assertion: {reason} "
        "(problems_final_review.md P3-9 -- this is expected to be rare; if this "
        "starts happening on every run, treat it as a possible generator regression, "
        "not a stable skip).",
        stacklevel=2,
    )


@pytest.fixture
def skip_guards_fired_registry() -> list[str]:
    """Test-introspection-only access to the same list
    `record_skip_guard_fired` appends to, for
    `test_skip_guard_recording.py`'s own test of this mechanism. Exposed
    as a fixture rather than a plain module attribute import for the
    same reason `record_skip_guard_fired` itself is (see the module
    docstring's "Exposed as a fixture, not a plain module-level import"
    section)."""

    return _SKIP_GUARDS_FIRED


@pytest.fixture
def record_skip_guard_fired():
    """Call immediately before `pytest.skip(reason)` at any of the three
    data-dependent guard sites this phase's finding names, e.g.::

        def test_foo(record_skip_guard_fired):
            if some_data_dependent_condition:
                record_skip_guard_fired("why")
                pytest.skip("why")

    Raises a real `UserWarning` (shows up in pytest's own "warnings
    summary") and records the reason for this session's terminal-summary
    line."""

    return _record_skip_guard_fired


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001
    terminalreporter.write_sep(
        "=", "data-dependent skip guards (problems_final_review.md P3-9)"
    )
    if _SKIP_GUARDS_FIRED:
        terminalreporter.write_line(
            f"{len(_SKIP_GUARDS_FIRED)}/3 known data-dependent guard(s) fired this run:"
        )
        for reason in _SKIP_GUARDS_FIRED:
            terminalreporter.write_line(f"  - {reason}")
    else:
        terminalreporter.write_line(
            "0/3 known data-dependent guards fired this run -- all three edge cases "
            "occurred for real at the current seed/scale, so every assertion they "
            "guard actually executed."
        )
