"""Real, executed proof for `docs/problems/problems_final_review.md` P3-9: the
`record_skip_guard_fired` fixture (`tests/conftest.py`) actually raises a
visible warning and records the reason -- this is the mechanism that
makes the three data-dependent `pytest.skip(...)` call sites loud rather
than silent, and this test proves the mechanism itself works, not just
that it is wired up at the three call sites.

Deliberately uses only pytest fixtures (`record_skip_guard_fired`,
`skip_guards_fired_registry`), never a plain `import conftest` -- see
`tests/conftest.py`'s own module docstring for why a bare module import
of a same-named `conftest.py` is unsafe in this package (multiple
sibling `conftest.py` files, no `__init__.py` packages).
"""

from __future__ import annotations

import pytest


def test_record_skip_guard_fired_raises_a_visible_warning(record_skip_guard_fired) -> None:
    with pytest.warns(UserWarning, match="data-dependent test guard fired"):
        record_skip_guard_fired("a fabricated reason, for this test only")


def test_record_skip_guard_fired_appends_to_the_session_registry(
    record_skip_guard_fired, skip_guards_fired_registry
) -> None:
    before = len(skip_guards_fired_registry)
    with pytest.warns(UserWarning):
        record_skip_guard_fired("another fabricated reason, for this test only")
    assert len(skip_guards_fired_registry) == before + 1
    assert skip_guards_fired_registry[-1] == "another fabricated reason, for this test only"
