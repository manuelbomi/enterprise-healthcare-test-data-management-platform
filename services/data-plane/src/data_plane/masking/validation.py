"""Masking validation: automated checks that a masking run actually did
what it claims.

This is the "implement masking validation" requirement of the Phase 3
promptbook -- a lightweight, in-package set of checks, not the full
"Certified test dataset pipeline" (`ROADMAP.md` Phase 6) or the
independent-verifier certification `ARCHITECTURE.md` section 2.2
describes for a later phase (see `problems_phase_03.md` P3-1 for that
scope boundary, explicit on purpose: `ARCHITECTURE.md` warns
certification must not "simply trust this module's own claims about what
it did," so a later phase's real certifier should not import this module
as its source of truth -- it exists for this phase's own tests and the
CLI's human-readable summary).
"""

from __future__ import annotations

from dataclasses import dataclass, field


class ReferentialIntegrityError(AssertionError):
    """A masked identifier did not map consistently within its scope."""


class RawValueLeakedError(AssertionError):
    """A raw, unmasked sensitive value was found in masked output."""


class CollisionError(AssertionError):
    """Two distinct real values masked to the same output within a scope
    that requires distinct outputs (a token collision -- see
    `token_vault.HmacTokenVault`'s configurable `token_hex_length`)."""


@dataclass
class ValidationReport:
    checks_run: list[str] = field(default_factory=list)
    passed: bool = True
    failures: list[str] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks_run.append(name)
        if not ok:
            self.passed = False
            self.failures.append(f"{name}: {detail}" if detail else name)


def assert_referential_integrity(
    linkage_samples: dict[tuple[str, str, str], dict[str, str]],
) -> None:
    """Given `MaskingRunReport.linkage_samples` (per-column samples of
    `{original: masked}` for every `preserve_linkage=True` column), verify
    that every column sharing the same *scope* maps a given original value
    to the same masked value. This is the direct, empirical check of this
    phase's headline requirement: a member ID masks to the same token in
    every dataset/source system it appears in.

    Raises `ReferentialIntegrityError` on the first inconsistency found,
    rather than returning a bool, because a referential-integrity failure
    in this platform's core value proposition is a hard stop, not a
    warning (see `ARCHITECTURE.md` section 3.1).
    """

    # Group samples by scope isn't available here (linkage_samples is
    # keyed by column, not scope) -- callers that want a cross-*column*
    # check pass in an already-scope-grouped mapping. See
    # `validate_masking_run` for how the two-level check is assembled
    # from a `MaskingRunReport` plus `data_plane.masking.policy`.
    by_original: dict[str, str] = {}
    for samples in linkage_samples.values():
        for original, masked in samples.items():
            if original in by_original and by_original[original] != masked:
                raise ReferentialIntegrityError(
                    f"Original value {original!r} masked inconsistently: "
                    f"{by_original[original]!r} vs {masked!r}"
                )
            by_original[original] = masked


def assert_no_raw_values_leaked(
    masked_text_blobs: list[str], raw_values: set[str], *, min_length: int = 4
) -> None:
    """Verify none of `raw_values` (known-sensitive originals: real SSNs,
    emails, names, member IDs pulled from the *unmasked* estate before a
    masking run) appear verbatim inside any of `masked_text_blobs` (the
    masked output files' raw text). Skips values shorter than
    `min_length` to avoid false positives on short, low-entropy strings
    that could plausibly recur by chance (e.g. a two-letter state code).
    """

    for raw in raw_values:
        if raw is None or len(str(raw)) < min_length:
            continue
        needle = str(raw)
        for blob in masked_text_blobs:
            if needle in blob:
                raise RawValueLeakedError(f"Raw value {needle!r} found in masked output")


def assert_no_collisions(mapping: dict[str, str]) -> None:
    """Verify `mapping` (original -> masked, for one scope) is injective:
    no two distinct originals produced the same masked value. A collision
    here would mean two different real people/claims/etc. became
    indistinguishable after masking, which silently corrupts referential
    integrity in the *other* direction (over-merging rather than
    breaking joins) -- just as serious as failing to link correctly."""

    seen: dict[str, str] = {}
    for original, masked in mapping.items():
        if masked in seen and seen[masked] != original:
            raise CollisionError(
                f"Masked value {masked!r} produced by both {seen[masked]!r} and {original!r}"
            )
        seen[masked] = original


def validate_masking_run(
    *,
    linkage_samples: dict[tuple[str, str, str], dict[str, str]],
    masked_text_blobs: list[str] | None = None,
    raw_values: set[str] | None = None,
) -> ValidationReport:
    """Run every available check against one masking run's output and
    return a single report instead of raising, so a CLI/test can inspect
    every failure at once rather than stopping at the first one."""

    report = ValidationReport()

    try:
        assert_referential_integrity(linkage_samples)
        report.record("referential_integrity", True)
    except ReferentialIntegrityError as exc:
        report.record("referential_integrity", False, str(exc))

    for key, samples in linkage_samples.items():
        try:
            assert_no_collisions(samples)
            report.record(f"no_collisions:{key[0]}.{key[1]}.{key[2]}", True)
        except CollisionError as exc:
            report.record(f"no_collisions:{key[0]}.{key[1]}.{key[2]}", False, str(exc))

    if masked_text_blobs is not None and raw_values is not None:
        try:
            assert_no_raw_values_leaked(masked_text_blobs, raw_values)
            report.record("no_raw_values_leaked", True)
        except RawValueLeakedError as exc:
            report.record("no_raw_values_leaked", False, str(exc))

    return report


__all__ = [
    "CollisionError",
    "RawValueLeakedError",
    "ReferentialIntegrityError",
    "ValidationReport",
    "assert_no_collisions",
    "assert_no_raw_values_leaked",
    "assert_referential_integrity",
    "validate_masking_run",
]
