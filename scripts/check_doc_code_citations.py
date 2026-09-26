#!/usr/bin/env python
"""A small, real, proportionate automated cross-check for
`docs/problems/problems_final_review.md` P2-9 ("ROADMAP.md's Phase 16 section and
docs/tutorial/guide/ chapters cite real code paths ... with no
automated cross-check").

What this deliberately IS: a grep-based script that extracts two kinds
of citations from `ROADMAP.md`, `docs/interview/*.md`, and
`docs/tutorial/guide/*.md` --

1. backtick-quoted dotted Python module/attribute paths rooted at one
   of this repository's four real top-level packages (``control_plane``,
   ``data_plane``, ``governance_service``, ``healthcare_tdm_contracts``),
   e.g. `` `data_plane.spark.masking_job.run_claims_masking_job` ``
2. backtick-quoted HTTP route citations, e.g.
   `` `POST /api/v1/lifecycle/scheduler/run-due` ``

-- and checks each one against the real source tree: a module path must
resolve to a real ``.py`` file (after stripping any trailing
class/function/constant attribute names, since a citation like
``data_plane.masking.dataset_masker.mask_estate`` cites a function, not
a module), and a route citation's method+path must match a real
``@router.<method>(...)`` decorator (accounting for each router's
``prefix`` and the app-level ``/api/v1`` mount) in
``services/control-plane/src/control_plane/api/v1/*.py``.

What this deliberately is NOT: a general documentation-linting system,
a doc-freshness CI gate that runs on every PR, or a claim that every
citation in every doc file is covered (only the four package roots and
the one API surface P2-9 named are checked) -- matching the finding's
own ask for "a lightweight periodic ... grep-based check," not a
disproportionate new tooling investment.

Usage::

    python scripts/check_doc_code_citations.py

Exits 0 and prints a summary if every citation resolves; exits 1 and
lists every citation that does not resolve, with the file:line it came
from, if any do not.
"""

from __future__ import annotations

import importlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DOC_GLOBS = [
    "ROADMAP.md",
    "docs/interview/*.md",
    "docs/tutorial/guide/*.md",
]

#: Top-level packages this check resolves citations against. Each of
#: this monorepo's four Python packages is installed editable into the
#: same environment (a real `pytest`/`python` run from this repository
#: can `import data_plane` etc. regardless of which package's tests are
#: running), so citations are resolved by actually importing the module
#: and `getattr`-walking any trailing attribute -- real symbol
#: resolution, not a filesystem-path guess that could be fooled by a
#: directory that merely happens to exist.
PACKAGE_ROOTS = ("control_plane", "data_plane", "governance_service", "healthcare_tdm_contracts")

#: Router files whose real @router.<method>("<path>") decorators + each
#: router's own `prefix=` argument are checked against `POST /api/v1/...`
#: style citations. Deliberately just this one service's API surface --
#: the only one any doc file actually cites by route -- not an attempt to
#: generalize to the frontend or governance-service (which has no live
#: routes to cite; see P2-11).
API_V1_DIR = (
    REPO_ROOT / "services" / "control-plane" / "src" / "control_plane" / "api" / "v1"
)
API_V1_PREFIX = "/api/v1"

MODULE_PATH_RE = re.compile(
    r"`((?:control_plane|data_plane|governance_service|healthcare_tdm_contracts)"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`"
)
ROUTE_RE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/api/v1/[A-Za-z0-9/_{}\-]*)`")
ROUTER_PREFIX_RE = re.compile(r'router\s*=\s*APIRouter\(\s*(?:prefix\s*=\s*"([^"]*)")?')
ROUTE_DECORATOR_RE = re.compile(
    r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"'
)


@dataclass(frozen=True)
class Citation:
    kind: str  # "module" or "route"
    value: str
    doc_path: str
    line_no: int


def iter_citations() -> list[Citation]:
    citations: list[Citation] = []
    for pattern in DOC_GLOBS:
        for doc_path in sorted(REPO_ROOT.glob(pattern)):
            text = doc_path.read_text(encoding="utf-8")
            rel = doc_path.relative_to(REPO_ROOT).as_posix()
            for line_no, line in enumerate(text.splitlines(), start=1):
                for match in MODULE_PATH_RE.finditer(line):
                    citations.append(Citation("module", match.group(1), rel, line_no))
                for match in ROUTE_RE.finditer(line):
                    citations.append(
                        Citation("route", f"{match.group(1)} {match.group(2)}", rel, line_no)
                    )
    return citations


LOGGER_NAME_RE = re.compile(r'logging\.getLogger\(\s*"([^"]+)"\s*\)')

#: The `services/*/src` directories this check greps for
#: `logging.getLogger("...")` calls, so a citation naming a *logger*
#: (e.g. `` `control_plane.request` ``, `` `control_plane.lifecycle.scheduler` ``
#: -- a `logging` namespace string, not an importable Python module) is
#: correctly recognized as real rather than flagged as a broken module
#: path. Logger names deliberately look like dotted module paths (that
#: is the stdlib `logging` convention this repository follows) but are
#: not required to resolve to an actual importable module -- e.g.
#: `control_plane.main`'s `_request_logger` is named `"control_plane.request"`,
#: not `"control_plane.main"`.
SOURCE_DIRS = [
    REPO_ROOT / "services" / "control-plane" / "src",
    REPO_ROOT / "services" / "data-plane" / "src",
    REPO_ROOT / "services" / "governance-service" / "src",
    REPO_ROOT / "libs" / "contracts" / "src",
]


def known_logger_names() -> set[str]:
    names: set[str] = set()
    for source_dir in SOURCE_DIRS:
        for py_file in source_dir.rglob("*.py"):
            names.update(LOGGER_NAME_RE.findall(py_file.read_text(encoding="utf-8")))
    return names


def module_path_resolves(dotted: str, logger_names: set[str] | None = None) -> bool:
    """A citation may name a module (``data_plane.spark.masking_job``) or
    an attribute inside one (``data_plane.spark.masking_job.run_claims_masking_job``,
    or even a nested ``Class.method`` chain like
    ``control_plane.domain.evidence.EvidenceRepository.build_evidence_package``).
    This resolves it the same way Python itself would: import the
    longest prefix that is actually importable, then `getattr`-walk any
    remaining trailing segments as attributes. Real symbol resolution,
    not a filesystem-path guess -- a directory that happens to exist but
    was never actually a valid import, or an attribute that was renamed
    inside a still-real module, is correctly rejected either way.

    ``logger_names`` (see :func:`known_logger_names`) is checked first as
    a literal, exact match -- a citation naming a real `logging` logger
    rather than an importable module."""

    if logger_names is not None and dotted in logger_names:
        return True

    parts = dotted.split(".")
    if parts[0] not in PACKAGE_ROOTS:
        return False

    module = None
    split_at = len(parts)
    for split_at in range(len(parts), 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:split_at]))
            break
        except ImportError:
            continue
    if module is None:
        return False

    obj = module
    for attr in parts[split_at:]:
        try:
            obj = getattr(obj, attr)
        except AttributeError:
            return False
    return True


def real_routes() -> set[tuple[str, str]]:
    """The real ``(METHOD, full_path)`` pairs this service actually
    serves, derived from each router file's own ``prefix=`` and
    ``@router.<method>(...)`` decorators -- not hand-maintained, so it
    cannot itself drift from the source it reads."""

    routes: set[tuple[str, str]] = set()
    for py_file in sorted(API_V1_DIR.glob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        prefix_match = ROUTER_PREFIX_RE.search(text)
        router_prefix = prefix_match.group(1) if prefix_match and prefix_match.group(1) else ""
        for method, path in ROUTE_DECORATOR_RE.findall(text):
            full_path = f"{API_V1_PREFIX}{router_prefix}{path}"
            routes.add((method.upper(), full_path))
    return routes


def route_resolves(citation_value: str, routes: set[tuple[str, str]]) -> bool:
    method, path = citation_value.split(" ", 1)
    # Docs use varying placeholder names for the same path parameter
    # (`{version_id}` vs `{id}`, etc.) -- normalize any `{...}` segment
    # to a single wildcard token before comparing, since the parameter
    # *name* is documentation style, not part of the real route.
    normalized_cited = re.sub(r"\{[^}]*\}", "{}", path)
    for real_method, real_path in routes:
        if real_method != method.upper():
            continue
        if re.sub(r"\{[^}]*\}", "{}", real_path) == normalized_cited:
            return True
    return False


def main() -> int:
    citations = iter_citations()
    routes = real_routes()
    logger_names = known_logger_names()

    broken: list[Citation] = []
    checked_modules = 0
    checked_routes = 0
    for citation in citations:
        if citation.kind == "module":
            checked_modules += 1
            if not module_path_resolves(citation.value, logger_names):
                broken.append(citation)
        else:
            checked_routes += 1
            if not route_resolves(citation.value, routes):
                broken.append(citation)

    print(
        f"checked {checked_modules} module-path citations and "
        f"{checked_routes} route citations across {len(list(REPO_ROOT.glob('docs/tutorial/guide/*.md'))) + len(list(REPO_ROOT.glob('docs/interview/*.md'))) + 1} doc files"
    )

    if broken:
        print(f"\n{len(broken)} citation(s) do not resolve against the current source tree:\n")
        for citation in broken:
            print(f"  {citation.doc_path}:{citation.line_no}: `{citation.value}` ({citation.kind})")
        return 1

    print("all citations resolve against the current source tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
