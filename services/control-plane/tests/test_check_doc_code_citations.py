"""Real, executed proof for `problems_final_review.md` P2-9 ("ROADMAP.md's
Phase 16 section and docs/tutorial/guide/ chapters cite real code paths
... with no automated cross-check"): `scripts/check_doc_code_citations.py`
is a real, runnable cross-check that greps every module-path/route
citation out of `ROADMAP.md`, `docs/interview/*.md`, and
`docs/tutorial/guide/*.md` and verifies each one against the real source
tree, rather than trusting that a human reviewer caught every one.

`scripts/` is not an installed package (deliberately -- see
`test_run_scheduled_maintenance.py`'s own docstring for why), so this
test loads the script directly from its file path, the same way.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "check_doc_code_citations.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_doc_code_citations", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: `Citation`'s `from __future__ import
    # annotations` dataclass fields are resolved by looking the module up
    # in `sys.modules` by name -- without this, that lookup fails since
    # the module isn't registered under its own name yet (same fix as
    # `test_run_scheduled_maintenance.py`'s `_load_script`).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_real_doc_citation_resolves_against_the_current_source_tree() -> None:
    """The actual, current state of this repository's docs: every module
    path and route this script extracts from `ROADMAP.md`,
    `docs/interview/*.md`, and `docs/tutorial/guide/*.md` resolves. This
    is the real cross-check firing for real, not a mock -- if a future
    phase renames a module or route cited by any of these doc files
    without updating the citation, this test starts failing."""

    script = _load_script()
    assert script.main() == 0


def test_module_path_resolves_rejects_a_renamed_or_deleted_module() -> None:
    """The negative case: a citation naming a module that does not (or
    no longer) exists must be rejected, not silently accepted -- this is
    what makes the check a real guardrail against a future rename/delete,
    not just a script that always reports success."""

    script = _load_script()
    logger_names = script.known_logger_names()
    assert script.module_path_resolves("data_plane.spark.masking_job") is True
    assert script.module_path_resolves("data_plane.spark.masking_job.run_claims_masking_job") is True
    assert script.module_path_resolves("data_plane.spark.this_module_was_never_real") is False
    assert script.module_path_resolves("control_plane.this_module_was_never_real.at_all") is False
    # A real `logging.getLogger("control_plane.request")` name resolves
    # via the logger-name fallback even though it is not itself an
    # importable module (`control_plane.main`'s `_request_logger`).
    assert script.module_path_resolves("control_plane.request", logger_names) is True
    assert script.module_path_resolves("control_plane.this_logger_was_never_real", logger_names) is False


def test_route_resolves_rejects_a_renamed_or_deleted_route() -> None:
    """Same negative case for the HTTP-route half of the check: a real
    route (any parameter-name spelling) resolves; a route that was
    renamed, moved to a different router, or never existed does not."""

    script = _load_script()
    routes = script.real_routes()
    assert script.route_resolves("POST /api/v1/lifecycle/scheduler/run-due", routes) is True
    # Placeholder-name spelling must not matter -- only the real route's
    # own shape does.
    assert (
        script.route_resolves(
            "POST /api/v1/lifecycle/dataset-versions/{some_other_name}/access", routes
        )
        is True
    )
    assert script.route_resolves("POST /api/v1/lifecycle/scheduler/this-was-never-real", routes) is False
    assert script.route_resolves("DELETE /api/v1/lifecycle/scheduler/run-due", routes) is False
