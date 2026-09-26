"""Unit tests for the rule-based (pattern) detector layer, independent of
the schema layer and the engine's precedence logic (see test_engine.py).
"""

from __future__ import annotations

from data_plane.discovery.pattern_rules import match_all


def _best_category(column: str, sample_values: list[str] | None = None) -> str:
    matches = match_all(column, sample_values)
    assert matches, f"expected at least one detector to match {column!r}"
    best = max(matches, key=lambda d: d.confidence)
    return best.category.value


def test_schema_drift_columns_from_the_real_estate_are_classified() -> None:
    # Claims warehouse schema drift (writers/parquet_writer.py).
    assert _best_category("amount_paid") == "sensitive"
    # Partner v1 flat file abbreviations (writers/partner_writer.py).
    assert _best_category("pat_id") == "direct_identifier"
    assert _best_category("test_cd") == "phi"
    assert _best_category("test_nm") == "phi"
    assert _best_category("result") == "phi"
    assert _best_category("collected_dt") == "quasi_identifier"


def test_pipeline_metadata_wins_over_generic_date_pattern() -> None:
    # delivered_at/delivered_dt/late_arrival are ETL bookkeeping, not a
    # patient-linked date, even though they also match the generic "ends
    # in _at/_dt" date pattern. pipeline_metadata's higher confidence
    # (0.65 > 0.6) must win.
    assert _best_category("delivered_at") == "non_sensitive"
    assert _best_category("delivered_dt") == "non_sensitive"
    assert _best_category("late_arrival") == "non_sensitive"


def test_email_value_pattern_fires_even_with_an_unrelated_column_name() -> None:
    matches = match_all("contact_field", sample_values=["person@example.com", "other@example.org"])
    ids = {m.detector_id for m in matches}
    assert "pattern:email" in ids


def test_unmatched_column_returns_no_detectors() -> None:
    assert match_all("totally_unrecognizable_xyz123") == []


def test_name_detector_does_not_false_positive_on_business_name_fields() -> None:
    # A key, honest limitation this test locks in: the pattern-based name
    # detector is intentionally scoped to a curated list of person-name
    # column names so it does not fire on "plan_name"/"drug_name"/
    # "pharmacy_name"/"facility_name" (business/product names, not people).
    # See docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md.
    for column in ("plan_name", "drug_name", "pharmacy_name", "facility_name", "chain_name"):
        ids = {m.detector_id for m in match_all(column)}
        assert "pattern:person_name" not in ids, column


# ----------------------------------------------------------------------
# Phase 18B (`problems_final_review.md` P3-10, narrowed): entity context
# for the `pattern:npi` fallback, when the caller knows a recognized
# business entity name
# ----------------------------------------------------------------------


def test_npi_detector_boosts_confidence_and_clarifies_reason_with_known_business_entity_context() -> None:
    """Without entity context, `pattern:npi` can only guess -- its own
    reason honestly says so. With `entity="Provider"` (a business entity
    this repository's own schema already recognizes), the fallback
    pattern layer now has real schema-level context to resolve that
    ambiguity, and returns a confidence-boosted, differently-reasoned
    hit instead of the generic guess."""

    plain = match_all("referring-npi")
    plain_npi = next(m for m in plain if m.detector_id == "pattern:npi")
    assert plain_npi.confidence == 0.7
    assert "cannot confirm" in plain_npi.reason

    with_context = match_all("referring-npi", entity="Provider")
    contextual_npi = next(m for m in with_context if m.detector_id == "pattern:npi+entity_context")
    assert contextual_npi.confidence == 0.95
    assert contextual_npi.category == plain_npi.category  # still PII -- context clarifies, doesn't invent safety
    assert "Provider" in contextual_npi.reason
    assert "business/provider entity" in contextual_npi.reason


def test_npi_detector_entity_context_is_case_insensitive_and_covers_both_known_business_entities() -> None:
    for entity in ("provider", "PROVIDER", "Pharmacy", "pharmacy"):
        ids = {m.detector_id for m in match_all("referring-npi", entity=entity)}
        assert "pattern:npi+entity_context" in ids, entity


def test_npi_detector_falls_back_to_the_generic_guess_for_an_unrecognized_or_missing_entity() -> None:
    """The honest, still-open half of P3-10: an entity this repository's
    schema has never heard of (or no entity at all -- a truly novel
    source system) gets the unmodified, lower-confidence guess, exactly
    as before. Entity-name recognition is itself necessarily a fixed,
    finite list, not a general fix."""

    for entity in (None, "Member", "SomeEntirelyNovelSourceSystemEntity"):
        ids = {m.detector_id for m in match_all("referring-npi", entity=entity)}
        assert "pattern:npi" in ids
        assert "pattern:npi+entity_context" not in ids
