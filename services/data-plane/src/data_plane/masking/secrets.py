"""HMAC secret key resolution for the masking engine.

Per `docs/adr/0006-deterministic-masking-strategy.md`, masking of
identifiers is `masked = f(real_value, scope, secret_key)`. This module is
the *only* place in `data_plane.masking` that reads that key, so there is
exactly one code path to audit for "does this ever hardcode or log a real
secret" (see `SECURITY.md` rule 2 and rule 4 -- a real deployment would
swap this module for a call into the security/governance plane's secrets
provider adapter; this module documents that seam without building the
adapter itself, which is out of scope for this phase -- see
`problems_phase_03.md`).

The key is **never** hardcoded here and **never** written to any file this
module controls. It is resolved, in order:

1. The `TDM_MASKING_HMAC_KEY` environment variable.
2. A `TDM_MASKING_HMAC_KEY=...` line in a `.env` file, checked in the
   current working directory, this package's own service directory
   (`services/data-plane/`), and the repository root -- all three are
   covered by the repository's root `.gitignore` (`.env`, `.env.*`), so a
   developer can keep a local key there without risking a commit. This is
   a deliberately tiny, dependency-free parser (not `python-dotenv`) --
   see `services/data-plane/.env.example` for the documented convention.

If neither is set, `resolve_hmac_key` raises `MissingMaskingKeyError` with
instructions, rather than silently generating or defaulting a key -- a
masking run with a key nobody recorded is not reproducible, which breaks
ADR-0006's determinism guarantee just as badly as no key at all.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import secrets as _stdlib_secrets

ENV_VAR = "TDM_MASKING_HMAC_KEY"

#: Minimum acceptable key length in bytes (of the UTF-8-encoded value).
#: 16 bytes = 128 bits; short of that is not a meaningful secret. This is
#: a floor, not a recommendation -- `generate_dev_key` produces 32 bytes
#: (256 bits) of hex.
MIN_KEY_BYTES = 16


class MissingMaskingKeyError(RuntimeError):
    """Raised when no HMAC key can be resolved from the environment or a
    local `.env` file. Carries a message with concrete remediation steps
    rather than just "not set", because this is the error a developer
    running the CLI for the first time will actually hit.
    """


class WeakMaskingKeyError(RuntimeError):
    """Raised when a resolved key is implausibly short to be a real secret
    (e.g. someone set `TDM_MASKING_HMAC_KEY=x` while testing). Catches an
    honest mistake before it produces a masking run that *looks* keyed but
    offers little real protection.
    """


def generate_dev_key() -> str:
    """Generate a throwaway, cryptographically random hex key for local
    development/testing only.

    WARNING: this key is generated in memory and returned to the caller.
    It is never written to disk by this function. Anyone who runs this
    twice gets two different keys -- there is no persistence, by design,
    so this can never accidentally become "the" key a real masking run
    depends on. Use `--generate-dev-key` on the masking CLI to print one
    for local export; do not use a key generated this way for anything
    beyond local experimentation, and never commit it anywhere.
    """

    return _stdlib_secrets.token_hex(32)  # 256 bits


def _read_dotenv_value(path: Path, var: str) -> str | None:
    """Read a single `KEY=value` line from a `.env`-style file. Minimal by
    design (no quoting/escaping/multiline support) -- this repository's
    `.env.example` files are all simple `KEY=value` lines, and adding a
    real parser dependency for one lookup is not warranted.
    """

    if not path.exists() or not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == var:
            return value.strip().strip('"').strip("'")
    return None


def _default_search_dirs() -> Iterable[Path]:
    here = Path(__file__).resolve()
    # services/data-plane/src/data_plane/masking/secrets.py -> services/data-plane
    service_root = here.parents[3]
    repo_root = here.parents[5] if len(here.parents) > 5 else service_root
    seen: set[Path] = set()
    for candidate in (Path.cwd(), service_root, repo_root):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def resolve_hmac_key(*, search_dirs: Iterable[Path] | None = None) -> bytes:
    """Resolve the masking HMAC key as raw bytes.

    Raises `MissingMaskingKeyError` if unset anywhere, and
    `WeakMaskingKeyError` if the resolved value is suspiciously short.
    Never returns a hardcoded default -- there is no such thing as a
    "default" secret key in this codebase (see `SECURITY.md` rule 2).
    """

    import os

    value = os.environ.get(ENV_VAR)
    source = "environment variable"
    if not value:
        for directory in search_dirs if search_dirs is not None else _default_search_dirs():
            value = _read_dotenv_value(directory / ".env", ENV_VAR)
            if value:
                source = f"{directory / '.env'}"
                break

    if not value:
        raise MissingMaskingKeyError(
            f"{ENV_VAR} is not set. The masking engine refuses to run "
            "without an explicit key (ADR-0006 requires deterministic "
            "masking to be *keyed*, and a run with no recorded key is not "
            "reproducible).\n"
            "To fix this for local development:\n"
            "  1. Generate a throwaway dev key:\n"
            "       python -m data_plane.masking.cli --generate-dev-key\n"
            "  2. Export it for this shell session only, e.g.:\n"
            f"       export {ENV_VAR}=<the printed value>\n"
            "     ...or copy services/data-plane/.env.example to "
            "services/data-plane/.env (gitignored) and paste it in.\n"
            "Never hardcode a key in source, and never commit a .env "
            "file -- see SECURITY.md."
        )

    encoded = value.encode("utf-8")
    if len(encoded) < MIN_KEY_BYTES:
        raise WeakMaskingKeyError(
            f"{ENV_VAR} resolved from {source} is only {len(encoded)} bytes "
            f"long; a real key should be at least {MIN_KEY_BYTES} bytes. "
            "Generate a proper key with "
            "'python -m data_plane.masking.cli --generate-dev-key'."
        )
    return encoded


__all__ = [
    "ENV_VAR",
    "MIN_KEY_BYTES",
    "MissingMaskingKeyError",
    "WeakMaskingKeyError",
    "generate_dev_key",
    "resolve_hmac_key",
]
