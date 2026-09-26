"""Intentional dangling-reference injection, for negative testing only.

The Phase 4 spec is explicit: "prevent dangling relationships
*unless intentionally injected for negative testing*." Everything else in
this package (`closure.py`, `validation.py`) is built to guarantee the
former; this module is the deliberate, opt-in escape hatch for the
latter -- e.g. to hand a downstream consumer-test-suite a subset that is
*known* to contain a specific kind of broken reference, so that suite can
verify it handles one correctly, without waiting for a 2% chance edge case
to show up in a random sample.

This is never invoked by default. A caller must explicitly ask for it
(`SubsetSelectionCriteria.negative_testing=True` and a call to
`inject_negative_test_orphan`), and every injection is fully accounted for
in the resulting `SubsetManifest.injected_negative_test_orphan_counts` so
it is never mistaken for an unnoticed bug -- see `validation.py`.
"""

from __future__ import annotations

from data_plane.subsetting.closure import ClosureResult, DanglingReference, _values

#: Relationships this module currently knows how to break on request. Kept
#: small and explicit rather than generic/reflective, so every supported
#: injection is a deliberate, reviewed piece of code, not something that
#: could accidentally corrupt an unrelated relationship.
SUPPORTED_RELATIONSHIPS = ("claim.provider_id",)


def inject_negative_test_orphan(
    closure: ClosureResult, *, relationship: str = "claim.provider_id", count: int = 1
) -> list[DanglingReference]:
    """Deliberately remove `count` Provider rows that selected Claims still
    reference, mutating `closure.selected` in place so the written subset
    genuinely contains the dangling reference (not just a manifest claim
    about one). Returns the `DanglingReference`s created, each tagged
    `category="negative_test_injection"` so `validation.py` reports them
    as intentional rather than as an engine bug or a coincidental
    pre-existing source orphan.

    Only `"claim.provider_id"` is supported today -- see
    `SUPPORTED_RELATIONSHIPS`. Raises `ValueError` for anything else
    rather than silently no-op'ing.
    """

    if relationship not in SUPPORTED_RELATIONSHIPS:
        raise ValueError(
            f"Unsupported negative-test relationship {relationship!r}; supported: {SUPPORTED_RELATIONSHIPS}"
        )
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    selected = closure.selected
    claims = selected.claim.all_rows()
    provider_ids_in_use = _values(claims, "provider_id")
    removable = [p for p in selected.provider if str(p.get("provider_id")) in provider_ids_in_use]
    if not removable:
        return []

    to_remove = removable[:count]
    remove_ids = {str(p["provider_id"]) for p in to_remove}
    selected.provider = [p for p in selected.provider if str(p.get("provider_id")) not in remove_ids]

    injected: list[DanglingReference] = []
    for claim in claims:
        provider_id = claim.get("provider_id")
        if provider_id is not None and str(provider_id) in remove_ids:
            injected.append(
                DanglingReference(
                    relationship="claim.provider_id",
                    missing_id=str(provider_id),
                    category="negative_test_injection",
                )
            )
    return injected


__all__ = ["SUPPORTED_RELATIONSHIPS", "inject_negative_test_orphan"]
